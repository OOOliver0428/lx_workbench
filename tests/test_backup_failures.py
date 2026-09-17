from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from app import backup
from app.config import get_settings


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "source.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE alembic_version(version_num TEXT)")
        db.execute("INSERT INTO alembic_version VALUES ('test-revision')")
        db.commit()
    monkeypatch.setenv("MVP_DATABASE_URL", f"sqlite:///{path.as_posix()}")
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def test_invalid_source_does_not_publish_backup(database, tmp_path):
    database.write_bytes(b"not a SQLite database")
    output = tmp_path / "backups"
    with pytest.raises(sqlite3.DatabaseError):
        backup.create_backup(output)
    assert list(output.iterdir()) == []
    assert database.read_bytes() == b"not a SQLite database"


def test_manifest_publish_failure_cleans_only_new_backup(database, tmp_path, monkeypatch):
    output = tmp_path / "backups"
    output.mkdir()
    previous = output / "mvp-previous.db"
    previous.write_bytes(b"old backup")
    original_replace = backup.os.replace

    def fail_manifest(source, destination):
        if str(destination).endswith(".manifest.json"):
            raise OSError("simulated full disk")
        original_replace(source, destination)

    monkeypatch.setattr(backup.os, "replace", fail_manifest)
    with pytest.raises(OSError, match="full disk"):
        backup.create_backup(output)
    assert list(output.iterdir()) == [previous]
    assert previous.read_bytes() == b"old backup"


def test_disappearing_source_is_not_recreated(database, tmp_path, monkeypatch):
    original_connect = backup.sqlite3.connect

    def disappear(path, *args, **kwargs):
        if kwargs.get("uri"):
            database.unlink()
        return original_connect(path, *args, **kwargs)

    monkeypatch.setattr(backup.sqlite3, "connect", disappear)
    with pytest.raises(sqlite3.OperationalError):
        backup.create_backup(tmp_path / "backups")
    assert not database.exists()
    assert list((tmp_path / "backups").iterdir()) == []


def test_invalid_retention_rejected_before_any_write(tmp_path, monkeypatch, capsys):
    output = tmp_path / "not-created"
    monkeypatch.setattr(
        "sys.argv", ["backup", "--output-dir", str(output), "--retention-days", "0"]
    )
    with pytest.raises(SystemExit) as result:
        backup.main()
    assert result.value.code == 2
    assert not output.exists()
    assert "未执行备份或清理" in capsys.readouterr().err


def test_backup_cli_failure_has_actionable_message(database, tmp_path, monkeypatch, capsys):
    database.unlink()
    monkeypatch.setattr("sys.argv", ["backup", "--output-dir", str(tmp_path / "backups")])
    with pytest.raises(SystemExit) as result:
        backup.main()
    assert result.value.code == 1
    message = capsys.readouterr().err
    assert "E_BACKUP" in message
    assert "原数据库未修改" in message
    assert "Traceback" not in message
