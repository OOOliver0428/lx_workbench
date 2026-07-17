import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import server


class WeeklyReportServerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database = server.DATABASE
        self.original_backup_dir = server.BACKUP_DIR
        server.DATABASE = Path(self.temp_dir.name) / "weekly_report.db"
        server.BACKUP_DIR = Path(self.temp_dir.name) / "backups"
        server.initialize_database()
        self.state = {
            "solutionWeeklyReportsV1": [
                {
                    "id": "report-1",
                    "week": "2026-W29",
                    "person": "张涛",
                    "project": "华东政务项目",
                    "category": "客户项目",
                    "summary": "完成总体方案评审",
                    "output": "总体方案 V3",
                    "hours": 8,
                    "next": "",
                }
            ],
            "solutionDepartmentSummariesV1": {},
            "solutionManagedPeopleV1": [{"id": "p1", "name": "张涛", "role": "解决方案"}],
            "solutionManagedProjectsV1": [{"id": "j1", "name": "华东政务项目"}],
            "solutionWeeklySnapshotsV1": {
                "2026-W29": {
                    "people": [{"id": "p1", "name": "张涛"}],
                    "projects": [{"id": "j1", "name": "华东政务项目"}],
                    "savedAt": "2026-07-19T12:00:00Z",
                }
            },
        }
        with server.connect_database() as connection:
            server.upsert_state(connection, self.state)

    def tearDown(self):
        server.DATABASE = self.original_database
        server.BACKUP_DIR = self.original_backup_dir
        self.temp_dir.cleanup()

    def test_summary_contains_person_deliverable_and_hours(self):
        summary = server.build_automated_summary(
            "2026-W29",
            self.state["solutionWeeklyReportsV1"],
            self.state["solutionWeeklySnapshotsV1"],
        )
        self.assertIn("张涛（8 小时）", summary)
        self.assertIn("交付物：总体方案 V3", summary)
        self.assertIn("累计投入 8 小时", summary)

    def test_monday_catch_up_summarizes_then_backs_up_once(self):
        now = datetime(2026, 7, 20, 0, 11, tzinfo=server.CHINA_TIMEZONE)
        completed = server.run_due_automation(now=now)
        self.assertEqual(completed, ["summary:2026-W29", "backup:2026-W29"])

        database_backup = server.BACKUP_DIR / "解决方案部门周报备份_after_2026-W29.db"
        json_backup = server.BACKUP_DIR / "解决方案部门周报备份_after_2026-W29.json"
        self.assertTrue(database_backup.is_file())
        self.assertTrue(json_backup.is_file())
        with sqlite3.connect(database_backup) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            backup_state = server.read_state(connection)
        self.assertIn("张涛（8 小时）", backup_state["solutionDepartmentSummariesV1"]["2026-W29"])

        payload = json.loads(json_backup.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], "solution-department-weekly-report")
        self.assertEqual(payload["version"], 2)
        self.assertEqual(set(payload["data"]), set(server.ARCHIVE_STATE_KEYS))
        modified_time = database_backup.stat().st_mtime_ns
        self.assertEqual(server.run_due_automation(now=now), [])
        self.assertEqual(database_backup.stat().st_mtime_ns, modified_time)


if __name__ == "__main__":
    unittest.main()
