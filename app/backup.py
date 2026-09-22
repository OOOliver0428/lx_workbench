from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app.config import get_settings


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError("在线备份命令只支持本机文件型 SQLite 数据库")
    return Path(url.database).expanduser().resolve()


def create_backup(output_dir: Path) -> tuple[Path, Path]:
    source_path = resolve_database_path(get_settings().database_url)
    if not source_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{source_path}")

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target_path = output_dir / f"mvp-{timestamp}.db"
    temporary_path = output_dir / f".{target_path.name}.tmp"
    manifest_path = output_dir / f"{target_path.name}.manifest.json"

    manifest_temp = output_dir / f".{manifest_path.name}.tmp"
    deadline = time.monotonic() + 120

    def check_deadline(_status: int, _remaining: int, _total: int) -> None:
        if time.monotonic() > deadline:
            raise TimeoutError("备份超过 120 秒；检查数据库是否被长事务占用或磁盘是否过慢")

    # mode=ro prevents silently creating an empty source if it disappears after
    # the file check. Exclusively create the private destination before SQLite opens it.
    descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    published = False
    manifest_published = False
    try:
        with (
            closing(sqlite3.connect(f"{source_path.as_uri()}?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(temporary_path)) as destination,
        ):
            source.backup(destination, pages=256, progress=check_deadline, sleep=0.1)
            destination.commit()
        with closing(sqlite3.connect(temporary_path)) as check:
            integrity = check.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise sqlite3.DatabaseError(f"备份完整性检查失败：{integrity}")
            table_count = check.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
            ).fetchone()[0]
            alembic_row = check.execute(
                "SELECT version_num FROM alembic_version LIMIT 1"
            ).fetchone()
        manifest = {
            "createdAt": datetime.now(UTC).isoformat(),
            "databaseFile": target_path.name,
            "sha256": sha256_file(temporary_path),
            "sizeBytes": temporary_path.stat().st_size,
            "tableCount": table_count,
            "schemaRevision": alembic_row[0] if alembic_row else None,
        }
        with temporary_path.open("rb+") as database_file:
            os.fsync(database_file.fileno())
        with manifest_temp.open("x", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, ensure_ascii=False, indent=2)
            manifest_file.flush()
            os.fsync(manifest_file.fileno())
        os.replace(temporary_path, target_path)
        published = True
        os.replace(manifest_temp, manifest_path)
        manifest_published = True
        if os.name == "posix":
            directory_fd = os.open(output_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        manifest_temp.unlink(missing_ok=True)
        if published:
            target_path.unlink(missing_ok=True)
        if manifest_published:
            manifest_path.unlink(missing_ok=True)
        raise
    return target_path, manifest_path


def prune_old_backups(output_dir: Path, retention_days: int) -> list[Path]:
    if retention_days < 1:
        raise ValueError("本机备份保留天数必须至少为 1")
    output_dir = output_dir.expanduser().resolve()
    cutoff = time.time() - retention_days * 24 * 60 * 60
    removed: list[Path] = []
    for backup_path in output_dir.glob("mvp-*.db"):
        if not backup_path.is_file() or backup_path.stat().st_mtime >= cutoff:
            continue
        manifest_path = backup_path.with_name(f"{backup_path.name}.manifest.json")
        backup_path.unlink()
        removed.append(backup_path)
        if manifest_path.is_file():
            manifest_path.unlink()
            removed.append(manifest_path)
    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description="创建一致的 SQLite 在线备份")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--retention-days", type=int)
    args = parser.parse_args()
    if args.retention_days is not None and args.retention_days < 1:
        parser.error("--retention-days 必须至少为 1；未执行备份或清理")
    try:
        backup_path, manifest_path = create_backup(args.output_dir)
    except (OSError, sqlite3.Error, RuntimeError, ValueError) as error:
        print(f"备份未完成 [E_BACKUP]：{error}", file=sys.stderr)
        print(
            "原数据库未修改。检查数据路径、读写权限、磁盘空间和数据库占用后重试。", file=sys.stderr
        )
        raise SystemExit(1) from None
    print(f"备份完成：{backup_path}")
    print(f"校验清单：{manifest_path}")
    if args.retention_days is not None:
        try:
            removed = prune_old_backups(args.output_dir, args.retention_days)
        except OSError as error:
            print(f"新备份已生成，但清理旧备份失败 [E_RETENTION]：{error}", file=sys.stderr)
            raise SystemExit(1) from None
        print(f"已清理过期本机备份文件：{len(removed)} 个")


if __name__ == "__main__":
    main()
