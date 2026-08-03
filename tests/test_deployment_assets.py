from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_ubuntu_install_keeps_runtime_state_outside_the_checkout() -> None:
    installer = read("deploy/ubuntu/install.sh")

    assert 'readonly ENV_FILE="${CONFIG_DIR}/app.env"' in installer
    assert 'readonly DATA_DIR="/var/lib/solution-workspace"' in installer
    assert 'readonly BACKUP_DIR="/var/backups/solution-workspace"' in installer
    assert "MVP_DATABASE_URL=${DATABASE_URL}" in installer
    assert "MVP_LLM_CONFIG_SECRET=${llm_secret}" in installer
    assert 'if [[ ! -f "${ENV_FILE}" ]]' in installer
    assert 'PROJECT_DIR="/opt/solution-workspace"' in installer
    assert 'readonly BACKEND_USER="solution-workspace"' in installer
    assert 'readonly FRONTEND_USER="solution-workspace-web"' in installer
    assert "uv sync --frozen --no-dev --python 3.12" in installer
    assert "npm ci --no-audit --no-fund" in installer
    assert 'chown -R root:root "${PROJECT_DIR}"' in installer


def test_systemd_units_keep_backend_private_and_schedule_verified_backups() -> None:
    backend = read("deploy/systemd/solution-workspace-backend.service.in")
    frontend = read("deploy/systemd/solution-workspace-frontend.service.in")
    backup = read("deploy/systemd/solution-workspace-backup.service.in")
    timer = read("deploy/systemd/solution-workspace-backup.timer")

    assert "--host 127.0.0.1" in backend
    assert "EnvironmentFile=@@ENV_FILE@@" in backend
    assert "ReadWritePaths=@@DATA_DIR@@" in backend
    assert "User=@@BACKEND_USER@@" in backend
    assert "User=@@FRONTEND_USER@@" in frontend
    assert "MVP_INTERNAL_API_BASE_URL=http://127.0.0.1:@@BACKEND_PORT@@" in frontend
    assert "python -m app.backup" in backup
    assert "flock --wait 600 @@LOCK_FILE@@" in backup
    assert "--retention-days 30" in backup
    assert "ReadWritePaths=@@DATA_DIR@@ @@BACKUP_DIR@@ @@LOCK_FILE@@" in backup
    assert "Persistent=true" in timer
    assert "Asia/Shanghai" in timer


def test_ops_database_switch_has_backup_validation_and_rollback_guards() -> None:
    operations = read("deploy/ubuntu/ops.sh")

    assert "verify_database" in operations
    assert "acquire_lock" in operations
    assert 'create_backup "${rollback_dir}"' in operations
    assert "database must stay inside" in operations
    assert 'run_app_env "${ALEMBIC_BIN}" upgrade head' in operations
    assert "clone_sqlite_database" in operations
    assert "move_database_bundle" in operations
    assert "promote-db" in operations
    assert "rollback_switch" in operations
    assert "new database failed service startup or health checks" in operations


def test_deployment_manual_covers_both_trial_database_outcomes() -> None:
    manual = read("docs/UBUNTU_DEPLOYMENT.md")

    assert "试用数据不要带入正式环境" in manual
    assert "保留全部试用数据并提升为正式库" in manual
    assert "当前版本只完成了 SQLite" in manual
    assert "MVP_LLM_CONFIG_SECRET" in manual
    assert "严禁试用库和正式库同时开放写入" in manual
