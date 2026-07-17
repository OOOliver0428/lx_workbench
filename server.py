#!/usr/bin/env python3
"""解决方案部门周报：零依赖的本地网页服务与 SQLite 数据库。"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import socket
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "weekly_report.db"
BACKUP_DIR = ROOT / "backups"
MAX_BODY_SIZE = 20 * 1024 * 1024
CHINA_TIMEZONE = timezone(timedelta(hours=8))
SUMMARY_TIME = (23, 50)
BACKUP_TIME = (0, 10)
ARCHIVE_STATE_KEYS = {
    "personalReports": "solutionWeeklyReportsV1",
    "departmentSummaries": "solutionDepartmentSummariesV1",
    "managedPeople": "solutionManagedPeopleV1",
    "managedProjects": "solutionManagedProjectsV1",
    "weeklySnapshots": "solutionWeeklySnapshotsV1",
}


def connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS app_state (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS automation_runs (
            job_name TEXT NOT NULL,
            scheduled_for TEXT NOT NULL,
            period_key TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            detail_json TEXT,
            PRIMARY KEY(job_name, scheduled_for)
        )
        """
    )
    connection.commit()
    return connection


def initialize_database() -> None:
    with connect_database():
        pass


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_state(connection: sqlite3.Connection) -> dict[str, object]:
    rows = connection.execute("SELECT key, value_json FROM app_state ORDER BY key").fetchall()
    state: dict[str, object] = {}
    for key, value_json in rows:
        try:
            state[key] = json.loads(value_json)
        except json.JSONDecodeError:
            continue
    return state


def upsert_state(connection: sqlite3.Connection, state: dict[str, object]) -> None:
    updated_at = utc_now_text()
    rows = [
        (key, json.dumps(value, ensure_ascii=False, separators=(",", ":")), updated_at)
        for key, value in state.items()
    ]
    connection.executemany(
        """
        INSERT INTO app_state(key, value_json, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value_json = excluded.value_json,
            updated_at = excluded.updated_at
        """,
        rows,
    )


def archive_payload_from_state(state: dict[str, object], backup_id: str) -> dict[str, object]:
    defaults: dict[str, object] = {
        "personalReports": [],
        "departmentSummaries": {},
        "managedPeople": [],
        "managedProjects": [],
        "weeklySnapshots": {},
    }
    data = {
        field: state.get(storage_key, defaults[field])
        for field, storage_key in ARCHIVE_STATE_KEYS.items()
    }
    return {
        "schema": "solution-department-weekly-report",
        "version": 2,
        "backupId": backup_id,
        "exportedAt": utc_now_text(),
        "data": data,
    }


class WeeklyReportHandler(BaseHTTPRequestHandler):
    server_version = "WeeklyReportServer/1.0"

    def log_message(self, format_string: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            self.send_json({"ok": True, "database": DATABASE.name})
            return
        if path == "/api/state":
            self.get_state()
            return
        if path == "/api/automation":
            self.get_automation_status()
            return
        self.serve_static(path)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path != "/api/import":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = self.read_json_body()
        if payload is None:
            return
        state = payload.get("state")
        required_keys = set(ARCHIVE_STATE_KEYS.values())
        if not isinstance(state, dict) or set(state) != required_keys:
            self.send_json(
                {"error": "state must contain the five complete archive keys"},
                HTTPStatus.BAD_REQUEST,
            )
            return
        try:
            with connect_database() as connection:
                connection.execute("BEGIN IMMEDIATE")
                upsert_state(connection, state)
        except (sqlite3.Error, TypeError, ValueError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        self.send_json({"ok": True, "keys": sorted(state)})

    def do_PUT(self) -> None:
        path = urlsplit(self.path).path
        prefix = "/api/state/"
        if not path.startswith(prefix) or len(path) == len(prefix):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        key = unquote(path[len(prefix):])
        if "/" in key or not key or len(key) > 200:
            self.send_json({"error": "invalid key"}, HTTPStatus.BAD_REQUEST)
            return
        payload = self.read_json_body()
        if payload is None:
            return
        if set(payload) != {"value"}:
            self.send_json({"error": "body must contain only value"}, HTTPStatus.BAD_REQUEST)
            return
        value_json = json.dumps(payload["value"], ensure_ascii=False, separators=(",", ":"))
        updated_at = datetime.now(timezone.utc).isoformat()
        with connect_database() as connection:
            connection.execute(
                """
                INSERT INTO app_state(key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, value_json, updated_at),
            )
        self.send_json({"ok": True, "key": key, "updatedAt": updated_at})

    def get_state(self) -> None:
        with connect_database() as connection:
            rows = connection.execute(
                "SELECT key, value_json, updated_at FROM app_state ORDER BY key"
            ).fetchall()
        data: dict[str, object] = {}
        latest_updated_at = None
        for key, value_json, updated_at in rows:
            try:
                data[key] = json.loads(value_json)
            except json.JSONDecodeError:
                continue
            if latest_updated_at is None or updated_at > latest_updated_at:
                latest_updated_at = updated_at
        self.send_json({"data": data, "updatedAt": latest_updated_at})

    def get_automation_status(self) -> None:
        with connect_database() as connection:
            rows = connection.execute(
                """
                SELECT job_name, scheduled_for, period_key, status, completed_at, detail_json
                FROM automation_runs
                ORDER BY scheduled_for DESC, job_name
                LIMIT 12
                """
            ).fetchall()
        runs = []
        for job_name, scheduled_for, period_key, status, completed_at, detail_json in rows:
            try:
                detail = json.loads(detail_json) if detail_json else None
            except json.JSONDecodeError:
                detail = None
            runs.append({
                "job": job_name,
                "scheduledFor": scheduled_for,
                "period": period_key,
                "status": status,
                "completedAt": completed_at,
                "detail": detail,
            })
        self.send_json({
            "timezone": "Asia/Shanghai (UTC+8)",
            "summarySchedule": "Sunday 23:50",
            "backupSchedule": "Monday 00:10",
            "runs": runs,
        })

    def read_json_body(self) -> dict[str, object] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_SIZE:
            self.send_json({"error": "invalid body size"}, HTTPStatus.BAD_REQUEST)
            return None
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return None
        if not isinstance(payload, dict):
            self.send_json({"error": "JSON object required"}, HTTPStatus.BAD_REQUEST)
            return None
        return payload

    def serve_static(self, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else unquote(request_path).lstrip("/")
        target = (ROOT / relative).resolve()
        try:
            target.relative_to(ROOT)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store" if target.suffix == ".html" else "public, max-age=300")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def numeric_hours(value: object) -> float:
    try:
        hours = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(hours, 1) if hours > 0 else 0.0


def format_hours(value: object) -> str:
    hours = numeric_hours(value)
    return str(int(hours)) if hours.is_integer() else f"{hours:.1f}"


def unique_strings(values: list[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def iso_week_label(week_key: str) -> str:
    year_text, week_text = week_key.split("-W")
    start = datetime.fromisocalendar(int(year_text), int(week_text), 1)
    end = start + timedelta(days=6)
    return f"{year_text} 年第 {int(week_text)} 周 · {start:%m/%d}—{end:%m/%d}"


def build_automated_summary(
    week_key: str,
    reports: list[dict[str, object]],
    weekly_snapshots: dict[str, object],
) -> str:
    entries = [item for item in reports if isinstance(item, dict) and item.get("week") == week_key]
    label = iso_week_label(week_key)
    if not entries:
        return f"{label}\n解决方案部门周报摘要\n\n本周尚未收到个人周报数据。"
    category_order = ["客户项目", "方案与资产", "售前支撑", "内部建设", "内部协同", "学习与培训", "其他事项"]
    sections: list[str] = []
    for category in category_order:
        category_items = [item for item in entries if str(item.get("category") or "其他事项") == category]
        if not category_items:
            continue
        project_names = unique_strings([item.get("project") or category for item in category_items])
        project_lines: list[str] = []
        for project_index, project in enumerate(project_names, 1):
            project_items = [item for item in category_items if str(item.get("project") or category).strip() == project]
            project_hours = sum(numeric_hours(item.get("hours")) for item in project_items)
            people = unique_strings([item.get("person") for item in project_items])
            person_lines: list[str] = []
            for person in people:
                person_items = [item for item in project_items if str(item.get("person") or "").strip() == person]
                summaries = "；".join(unique_strings([item.get("summary") for item in person_items]))
                outputs = "、".join(unique_strings([item.get("output") or item.get("deliverable") for item in person_items])) or "历史数据未填写"
                person_hours = sum(numeric_hours(item.get("hours")) for item in person_items)
                person_lines.append(f"   - {person}（{format_hours(person_hours)} 小时）：{summaries}；交付物：{outputs}")
            project_lines.append(f"{project_index}. {project}（合计 {format_hours(project_hours)} 小时）\n" + "\n".join(person_lines))
        sections.append(f"{category}\n" + "\n".join(project_lines))
    people = unique_strings([item.get("person") for item in entries])
    deliverables = unique_strings([item.get("output") or item.get("deliverable") for item in entries])
    total_hours = sum(numeric_hours(item.get("hours")) for item in entries)
    snapshot = weekly_snapshots.get(week_key, {}) if isinstance(weekly_snapshots, dict) else {}
    projects = snapshot.get("projects", []) if isinstance(snapshot, dict) else []
    project_names = {str(project.get("name")) for project in projects if isinstance(project, dict)}
    covered_projects = len({str(item.get("project")) for item in entries if str(item.get("project")) in project_names})
    risks = unique_strings([
        f"- {item.get('person')}：{item.get('summary')}"
        for item in entries
        if any(keyword in str(item.get("summary") or "") for keyword in ("待", "风险", "协调", "阻塞", "问题", "下周"))
    ])
    overview = (
        f"本周共收到 {len(people)} 位成员的个人周报，自动拆分为 {len(entries)} 条事项，"
        f"覆盖 {covered_projects} 个在跟项目，形成 {len(deliverables)} 项交付物，累计投入 {format_hours(total_hours)} 小时。"
    )
    risk_text = "\n".join(risks) if risks else "- 暂未识别到明确的待协调或风险事项"
    return f"{label}\n解决方案部门周报摘要\n\n{overview}\n\n" + "\n\n".join(sections) + f"\n\n需关注事项\n{risk_text}"


def most_recent_schedule(now: datetime, weekday: int, hour: int, minute: int) -> datetime:
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) - timedelta(days=(now.weekday() - weekday) % 7)
    if candidate > now:
        candidate -= timedelta(days=7)
    return candidate


def week_key_for_date(value: datetime) -> str:
    iso_year, iso_week, _ = value.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def run_summary_job(scheduled_for: datetime, period_key: str) -> bool:
    scheduled_text = scheduled_for.isoformat()
    with connect_database() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT status FROM automation_runs WHERE job_name=? AND scheduled_for=?",
            ("weekly_summary", scheduled_text),
        ).fetchone()
        if existing and existing[0] == "completed":
            return False
        started_at = utc_now_text()
        connection.execute(
            """
            INSERT OR REPLACE INTO automation_runs
            (job_name, scheduled_for, period_key, status, started_at, completed_at, detail_json)
            VALUES (?, ?, ?, 'running', ?, NULL, NULL)
            """,
            ("weekly_summary", scheduled_text, period_key, started_at),
        )
        state = read_state(connection)
        reports = state.get("solutionWeeklyReportsV1", [])
        snapshots = state.get("solutionWeeklySnapshotsV1", {})
        if not isinstance(reports, list):
            reports = []
        reports = [item for item in reports if isinstance(item, dict)]
        if not isinstance(snapshots, dict):
            snapshots = {}
        summary = build_automated_summary(period_key, reports, snapshots)
        summaries = state.get("solutionDepartmentSummariesV1", {})
        if not isinstance(summaries, dict):
            summaries = {}
        summaries = {**summaries, period_key: summary}
        upsert_state(connection, {"solutionDepartmentSummariesV1": summaries})
        detail = {"reports": len([item for item in reports if item.get("week") == period_key]), "summaryLength": len(summary)}
        connection.execute(
            """
            UPDATE automation_runs
            SET status='completed', completed_at=?, detail_json=?
            WHERE job_name=? AND scheduled_for=?
            """,
            (utc_now_text(), json.dumps(detail, ensure_ascii=False), "weekly_summary", scheduled_text),
        )
    print(f"自动汇总完成：{period_key}")
    return True


def run_backup_job(scheduled_for: datetime, period_key: str) -> bool:
    scheduled_text = scheduled_for.isoformat()
    with connect_database() as connection:
        existing = connection.execute(
            "SELECT status FROM automation_runs WHERE job_name=? AND scheduled_for=?",
            ("weekly_backup", scheduled_text),
        ).fetchone()
        if existing and existing[0] == "completed":
            return False
        connection.execute(
            """
            INSERT OR REPLACE INTO automation_runs
            (job_name, scheduled_for, period_key, status, started_at, completed_at, detail_json)
            VALUES (?, ?, ?, 'running', ?, NULL, NULL)
            """,
            ("weekly_backup", scheduled_text, period_key, utc_now_text()),
        )
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"解决方案部门周报备份_after_{period_key}"
    database_target = BACKUP_DIR / f"{stem}.db"
    json_target = BACKUP_DIR / f"{stem}.json"
    database_temp = BACKUP_DIR / f".{stem}.db.tmp"
    json_temp = BACKUP_DIR / f".{stem}.json.tmp"
    try:
        if database_temp.exists():
            database_temp.unlink()
        with connect_database() as source, sqlite3.connect(database_temp) as destination:
            source.backup(destination)
        with sqlite3.connect(database_temp) as check_connection:
            integrity = check_connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise sqlite3.DatabaseError(f"backup integrity check failed: {integrity}")
        os.replace(database_temp, database_target)
        with sqlite3.connect(database_target) as backup_connection:
            payload = archive_payload_from_state(read_state(backup_connection), f"scheduled-{period_key}")
        json_temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(json_temp, json_target)
        detail = {"database": database_target.name, "json": json_target.name, "integrity": integrity}
        with connect_database() as connection:
            connection.execute(
                """
                UPDATE automation_runs
                SET status='completed', completed_at=?, detail_json=?
                WHERE job_name=? AND scheduled_for=?
                """,
                (utc_now_text(), json.dumps(detail, ensure_ascii=False), "weekly_backup", scheduled_text),
            )
    except Exception as error:
        with connect_database() as connection:
            connection.execute(
                """
                UPDATE automation_runs SET status='failed', completed_at=?, detail_json=?
                WHERE job_name=? AND scheduled_for=?
                """,
                (utc_now_text(), json.dumps({"error": str(error)}, ensure_ascii=False), "weekly_backup", scheduled_text),
            )
        raise
    print(f"自动备份完成：{database_target.name}、{json_target.name}")
    return True


def run_due_automation(
    now: datetime | None = None,
    summary_time: tuple[int, int] = SUMMARY_TIME,
    backup_time: tuple[int, int] = BACKUP_TIME,
) -> list[str]:
    local_now = now or datetime.now(CHINA_TIMEZONE)
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=CHINA_TIMEZONE)
    summary_schedule = most_recent_schedule(local_now, 6, *summary_time)
    backup_schedule = most_recent_schedule(local_now, 0, *backup_time)
    jobs = [
        (summary_schedule, "summary", week_key_for_date(summary_schedule)),
        (backup_schedule, "backup", week_key_for_date(backup_schedule - timedelta(days=1))),
    ]
    completed: list[str] = []
    for scheduled_for, job_type, period_key in sorted(jobs, key=lambda item: item[0]):
        if job_type == "summary" and run_summary_job(scheduled_for, period_key):
            completed.append(f"summary:{period_key}")
        if job_type == "backup" and run_backup_job(scheduled_for, period_key):
            completed.append(f"backup:{period_key}")
    return completed


def automation_loop(
    stop_event: threading.Event,
    summary_time: tuple[int, int],
    backup_time: tuple[int, int],
    interval_seconds: int,
) -> None:
    while not stop_event.is_set():
        try:
            run_due_automation(summary_time=summary_time, backup_time=backup_time)
        except Exception as error:
            print(f"自动任务执行失败：{error}")
        stop_event.wait(interval_seconds)


def parse_clock(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except (ValueError, AttributeError) as error:
        raise argparse.ArgumentTypeError("时间格式应为 HH:MM") from error
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise argparse.ArgumentTypeError("时间必须在 00:00 到 23:59 之间")
    return hour, minute


def local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return probe.getsockname()[0]
    except OSError:
        return "这台电脑的局域网 IP"
    finally:
        probe.close()


def main() -> None:
    global DATABASE, BACKUP_DIR
    parser = argparse.ArgumentParser(description="启动解决方案部门周报共享服务")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认允许局域网访问")
    parser.add_argument("--port", type=int, default=8787, help="服务端口，默认 8787")
    parser.add_argument("--database", type=Path, help="数据库文件路径，默认使用项目目录下的 weekly_report.db")
    parser.add_argument("--backup-dir", type=Path, help="备份目录，默认使用项目目录下的 backups")
    parser.add_argument("--summary-time", type=parse_clock, default=SUMMARY_TIME, metavar="HH:MM", help="周日自动汇总时间，默认 23:50")
    parser.add_argument("--backup-time", type=parse_clock, default=BACKUP_TIME, metavar="HH:MM", help="周一自动备份时间，默认 00:10")
    parser.add_argument("--scheduler-interval", type=int, default=30, help="定时任务检查间隔秒数，默认 30")
    parser.add_argument("--no-scheduler", action="store_true", help="禁用定时任务，仅用于测试或维护")
    args = parser.parse_args()
    if args.database:
        DATABASE = args.database.expanduser().resolve()
    if args.backup_dir:
        BACKUP_DIR = args.backup_dir.expanduser().resolve()
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    initialize_database()
    server = ThreadingHTTPServer((args.host, args.port), WeeklyReportHandler)
    stop_event = threading.Event()
    scheduler_thread = None
    if not args.no_scheduler:
        scheduler_thread = threading.Thread(
            target=automation_loop,
            args=(stop_event, args.summary_time, args.backup_time, max(5, args.scheduler_interval)),
            name="weekly-report-automation",
            daemon=True,
        )
        scheduler_thread.start()
    print("解决方案部门周报已启动")
    print(f"本机访问：http://127.0.0.1:{args.port}")
    print(f"同一网络的其他人访问：http://{local_ip()}:{args.port}")
    print(f"数据库文件：{DATABASE}")
    print(f"自动汇总：每周日 {args.summary_time[0]:02d}:{args.summary_time[1]:02d}")
    print(f"自动备份：每周一 {args.backup_time[0]:02d}:{args.backup_time[1]:02d}，目录 {BACKUP_DIR}")
    print("按 Control+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        stop_event.set()
        if scheduler_thread:
            scheduler_thread.join(timeout=3)
        server.server_close()


if __name__ == "__main__":
    main()
