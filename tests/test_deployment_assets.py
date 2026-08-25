from __future__ import annotations

import os
import shutil
import stat
import subprocess
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
    assert "MVP_API_MAX_BODY_BYTES=262144" in installer
    assert "MVP_LOGIN_MAX_CONCURRENT_VERIFICATIONS=2" in installer
    assert "MVP_LLM_GLOBAL_TOKENS_PER_DAY=1000000" in installer
    assert 'if [[ ! -f "${ENV_FILE}" ]]' in installer
    assert 'PROJECT_DIR="/opt/solution-workspace"' in installer
    assert 'readonly BACKEND_USER="solution-workspace"' in installer
    assert 'readonly FRONTEND_USER="solution-workspace-web"' in installer
    assert "uv sync --frozen --no-dev --python 3.12" in installer
    assert "ci --include=dev --prefer-offline --no-audit --no-fund" in installer
    assert 'runuser -u "${FRONTEND_USER}"' in installer
    assert 'env -i' in installer
    assert 'npm_config_cache="${NPM_CACHE_DIR}"' in installer
    assert "/root/.npm/_cacache" in installer
    assert "curl flock openssl runuser systemctl" in installer
    assert "bootstrap_command in realpath git systemctl" in installer
    assert 'chown -R root:root "${PROJECT_DIR}"' in installer
    assert 'chmod -R u=rwX,go=rX "${PROJECT_DIR}"' in installer
    assert 'chmod -R go-w "${PROJECT_DIR}"' not in installer
    assert 'find "${PROJECT_DIR}/app" -type f ! -readable -print -quit' in installer
    assert "aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967" in installer
    assert "4d4fa08d95b06642e5800df6a22bd71455f23f988269e18da2847971d8c0bf31" in installer
    assert "sha256sum --check --strict" in installer
    assert 'sh "${temporary_uv_installer}"' not in installer
    assert 'install -d -m 0755 -o root -g root "${BACKUP_DIR}"' in installer


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
    assert "MVP_MAX_REQUEST_BODY_BYTES=262144" in frontend
    assert "python -m app.backup" in backup
    assert "@@BACKUP_DIR@@/scheduled" in backup
    assert "flock --wait 600 @@LOCK_FILE@@" in backup
    assert "--retention-days 30" in backup
    assert "ReadWritePaths=@@DATA_DIR@@ @@BACKUP_DIR@@/scheduled @@LOCK_FILE@@" in backup
    assert "Persistent=true" in timer
    assert "Asia/Shanghai" in timer


def test_ops_database_switch_has_backup_validation_and_rollback_guards() -> None:
    operations = read("deploy/ubuntu/ops.sh")

    assert "verify_database" in operations
    assert "acquire_lock" in operations
    assert 'create_backup "${rollback_dir}"' in operations
    assert "database must be a direct child" in operations
    assert 'run_app_env "${ALEMBIC_BIN}" upgrade head' in operations
    assert "clone_sqlite_database" in operations
    assert "move_database_bundle" in operations
    assert "promote-db" in operations
    assert "rollback_switch" in operations
    assert "trap 'switch_error_trap 130' INT" in operations
    assert "trap 'switch_error_trap 143' TERM" in operations
    assert "systemctl stop solution-workspace-backup.timer || return 1" in operations
    assert "systemctl start solution-workspace.target || return 1" in operations
    assert "new database failed service startup or health checks" in operations
    assert "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" in operations
    assert '"${RUNUSER_BIN}" -u "${APP_USER}"' in operations
    assert '[[ "$#" -eq 0 ]] || fail "usage: solution-workspace backup"' in operations
    assert 'create_backup "${SCHEDULED_BACKUP_DIR}"' in operations
    assert "secure_database_permissions" in operations
    assert "os.O_NOFOLLOW" in operations
    assert "os.fstat(database_fd)" in operations
    assert "os.fchown(database_fd" in operations
    assert "os.fchmod(database_fd" in operations
    switch_start = operations.index("switch_database()")
    assert operations.index("stop_for_maintenance", switch_start) < operations.index(
        'secure_database_permissions "${target_path}"', switch_start
    )
    post_stop = operations.index(
        'target_path="$(realpath --canonicalize-missing -- "${requested_path}")"',
        operations.index("stop_for_maintenance", switch_start),
    )
    assert operations.index(
        '[[ "${target_path}" != "${current_path}" ]]', post_stop
    ) < operations.index(
        'secure_database_permissions "${target_path}"', post_stop
    )


def test_update_stages_frontend_before_stopping_the_running_release() -> None:
    operations = read("deploy/ubuntu/ops.sh")

    stage_message = (
        "Installing and building the candidate frontend while the current version is online"
    )
    update_case = operations.index("  update)")
    stage_position = operations.index(stage_message, update_case)
    stop_position = operations.index("stop_for_maintenance", stage_position)

    assert stage_position < stop_position
    assert "ci --include=dev --prefer-offline --no-audit --no-fund" in operations
    assert "run_as_frontend npm" in operations
    assert '"${FRONTEND_USER}" -- env -i' in operations
    assert 'npm_config_cache="${NPM_CACHE_DIR}"' in operations
    assert "/root/.npm/_cacache" in operations
    assert "umask 0022" in operations[stage_position:stop_position]
    assert "validate_staged_frontend" in operations
    assert "tar --no-same-owner --no-same-permissions" in operations
    assert (
        "candidate frontend install/build failed; the current version is still online"
        in operations
    )
    assert "swap_frontend_runtime" in operations
    assert "FRONTEND_RUNTIME_BACKUP=" in operations
    assert "FRONTEND_RUNTIME_SWAPPED=false" in operations
    assert "set_frontend_runtime_state in_progress" in operations
    assert "set_frontend_runtime_state true" in operations
    assert 'sync -f "${update_dir}/update.env"' in operations
    assert 'sync -f "${update_dir}"' in operations
    assert "trap 'update_failed 130' INT" in operations
    assert "trap 'update_failed 143' TERM" in operations
    assert '"${RUNUSER_BIN}" -u "${FRONTEND_USER}"' in operations
    assert 'frontend/dist/server/index.js"' in operations
    assert 'chmod -R u=rwX,go=rX "${PROJECT_DIR}"' in operations
    assert 'chmod -R go-w "${PROJECT_DIR}"' not in operations
    assert 'find "${PROJECT_DIR}/app" -type f ! -readable -print -quit' in operations


def test_release_permission_normalization_restores_runtime_read_access(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        return

    release_dir = tmp_path / "release"
    package_dir = release_dir / "app" / "services"
    package_dir.mkdir(parents=True)
    source_file = package_dir / "dashboard.py"
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    package_dir.chmod(0o700)
    source_file.chmod(0o600)

    subprocess.run(
        ["chmod", "-R", "u=rwX,go=rX", str(release_dir)],
        check=True,
    )

    assert package_dir.stat().st_mode & stat.S_IXOTH
    assert source_file.stat().st_mode & stat.S_IROTH
    assert not source_file.stat().st_mode & stat.S_IWOTH


def test_candidate_build_chain_does_not_continue_after_install_failure(tmp_path: Path) -> None:
    if os.name == "nt":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    fake_npm = tmp_path / "npm"
    fake_npm.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == ci ]]; then exit 23; fi\n"
        "touch \"${BUILD_MARKER}\"\n",
        encoding="utf-8",
    )
    fake_npm.chmod(0o755)
    build_marker = tmp_path / "build-ran"
    success_marker = tmp_path / "candidate-succeeded"
    environment = os.environ.copy()
    environment.update(
        {
            "BUILD_MARKER": str(build_marker),
            "FAKE_NPM": str(fake_npm),
            "SUCCESS_MARKER": str(success_marker),
        }
    )
    subprocess.run(
        [
            bash,
            "-c",
            'if ! ( "$FAKE_NPM" ci && "$FAKE_NPM" run build '
            '&& touch "$SUCCESS_MARKER" ); then :; fi',
        ],
        check=True,
        env=environment,
    )

    assert not build_marker.exists()
    assert not success_marker.exists()


def test_deployment_manual_covers_both_trial_database_outcomes() -> None:
    manual = read("docs/UBUNTU_DEPLOYMENT.md")

    assert "试用数据不要带入正式环境" in manual
    assert "保留全部试用数据并提升为正式库" in manual
    assert "当前版本只完成了 SQLite" in manual
    assert "MVP_LLM_CONFIG_SECRET" in manual
    assert "严禁试用库和正式库同时开放写入" in manual


def test_deployment_manual_covers_bundle_and_dependency_escape_paths() -> None:
    manual = read("docs/UBUNTU_DEPLOYMENT.md")

    assert "GitHub 不可达时使用增量 bundle" in manual
    assert "bundle 只替代 GitHub 代码传输" in manual
    assert "服务器当前提交号..main" in manual
    assert "solution-workspace.next" in manual
    assert 'test -s "$candidate"' in manual
    assert '/usr/local/sbin/solution-workspace update "$bundle" main' in manual
    assert "不能直接调用旧版 `update`" in manual
    assert "FRONTEND_RUNTIME_SWAPPED" in manual
    assert "--include=dev --prefer-offline" in manual


def test_windows_bundle_tool_is_checkout_safe_and_self_verifying() -> None:
    wrapper = read("生成离线升级包.cmd")
    tool = read("scripts/New-OfflineUpdateBundle.ps1")

    assert "New-OfflineUpdateBundle.ps1" in wrapper
    assert "fetch" in tool
    assert '"refs/remotes/$Remote/$Branch"' in tool
    assert '"${remoteRef}:refs/heads/$Branch"' in tool
    assert '"bundle", "verify", $bundlePath' in tool
    assert "bundle list-heads" in tool
    assert "Get-FileHash" in tool
    assert '[string]$BaseRef = "v0.1.0"' in tool
    assert "merge-base" in tool
    assert "$baseCommit..refs/heads/$Branch" in tool
    assert "FullHistory" in tool
    assert "git switch" not in tool
    assert "git merge" not in tool
    assert "outputs\\offline-updates" in tool


def test_windows_launcher_refreshes_stale_frontend_dependencies() -> None:
    launcher = read("scripts/windows-test.ps1")

    assert "function Ensure-FrontendDependencies" in launcher
    assert 'Join-Path $FrontendRoot "package-lock.json"' in launcher
    assert 'Join-Path $RunRoot "frontend-package-lock.sha256"' in launcher
    assert 'Join-Path $ProjectRoot ".run\\npm-cache"' in launcher
    assert "Get-FileHash" in launcher
    assert "npm ci" in launcher
    assert "--cache $NpmCacheRoot" in launcher
    assert "--include=dev" in launcher
    assert "--prefer-offline" in launcher
    assert "--no-audit" in launcher
    assert "Ensure-FrontendDependencies -NpmPath $npm.Source" in launcher
