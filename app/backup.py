from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
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
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target_path = output_dir / f"mvp-{timestamp}.db"
    temporary_path = output_dir / f".{target_path.name}.tmp"
    manifest_path = output_dir / f"{target_path.name}.manifest.json"

    with (
        closing(sqlite3.connect(source_path)) as source,
        closing(sqlite3.connect(temporary_path)) as destination,
    ):
        source.backup(destination)
        destination.commit()
    with closing(sqlite3.connect(temporary_path)) as check:
        integrity = check.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise sqlite3.DatabaseError(f"备份完整性检查失败：{integrity}")
        table_count = check.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        alembic_row = check.execute("SELECT version_num FROM alembic_version LIMIT 1").fetchone()

    os.replace(temporary_path, target_path)
    manifest = {
        "createdAt": datetime.now(UTC).isoformat(),
        "databaseFile": target_path.name,
        "sha256": sha256_file(target_path),
        "sizeBytes": target_path.stat().st_size,
        "tableCount": table_count,
        "schemaRevision": alembic_row[0] if alembic_row else None,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target_path, manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="创建一致的 SQLite 在线备份")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    backup_path, manifest_path = create_backup(args.output_dir)
    print(f"备份完成：{backup_path}")
    print(f"校验清单：{manifest_path}")


if __name__ == "__main__":
    main()
