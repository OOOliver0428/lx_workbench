"""Run the production Bash workflow with real Git bundles in temporary trees.
Systemd, package downloads and privileged ownership are simulated.
Runnable on Linux with stdlib only: python3 tests/test_ops_runtime.py.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = (ROOT / "deploy/ubuntu/ops.sh").read_text(encoding="utf-8")
COMMON = (ROOT / "deploy/lib/diagnostics.sh").read_text(encoding="utf-8")


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"), "requires Linux Bash")
class OperationsRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="workspace-ops-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.project = self.root / "release"
        self.events = self.root / "events"
        self.events.touch()
        self.environment = os.environ | {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "LANG": "C.UTF-8",
        }
        self.git("init", "-b", "main", str(self.project), cwd=self.root)
        self.git("config", "user.name", "Deployment test")
        self.git("config", "user.email", "deployment@example.invalid")
        (self.project / "frontend").mkdir()
        (self.project / "frontend/package.json").write_text("{}\n")
        (self.project / "server.py").write_text("# test\n")
        (self.project / "app").mkdir()
        (self.project / "app/__init__.py").touch()
        (self.project / ".gitignore").write_text(".venv/\nfrontend/node_modules/\nfrontend/dist/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.data = self.root / "data"
        self.data.mkdir()
        (self.data / "active.db").write_bytes(b"test database")
        self.backups = self.root / "backups"
        self.backups.mkdir()
        self.envfile = self.root / "app.env"
        self.envfile.write_text(f"MVP_DATABASE_URL=sqlite:///{self.data}/active.db\n")
        self.exe("chown", "exit 0")
        self.exe("stat", 'if [[ "$1 $2" == "-c %u" ]]; then echo 0; else /usr/bin/stat "$@"; fi')
        self.exe(
            "install",
            """args=()
while (($#)); do
  case "$1" in -o|-g) shift 2 ;; *) args+=("$1"); shift ;; esac
done
exec /usr/bin/install "${args[@]}"
""",
        )
        self.exe("runuser", 'while [[ "$1" != -- ]]; do shift; done; shift; exec "$@"')
        self.exe(
            "systemctl",
            """echo "systemctl $*" >> "$FIX/events"
case "$1" in
  stop) echo inactive > "$FIX/state" ;;
  start|restart) [[ ! -e "$FIX/fail-restart" ]] || exit 1; echo active > "$FIX/state" ;;
  show) cat "$FIX/state" ;;
  is-active|is-enabled) [[ "$(cat "$FIX/state")" == active ]] ;;
esac
""",
        )
        (self.root / "state").write_text("active\n")
        self.exe("curl", '[[ "$(cat "$FIX/state")" == active ]]')
        self.exe("uv", 'echo uv >> "$FIX/events"; [[ ! -e "$FIX/fail-uv" ]]')
        self.exe(
            "npm",
            """echo "npm $*" >> "$FIX/events"
[[ ! -e "$FIX/fail-npm" ]] || { echo 'npm ERR! ENOTFOUND package source'; exit 2; }
directory="$2"
if [[ "$3" == ci ]]; then
 mkdir -p "$directory/node_modules/vinext/dist"
 touch "$directory/node_modules/vinext/dist/cli.js"
else
 mkdir -p "$directory/dist/server"
 touch "$directory/dist/server/index.js"
fi
""",
        )
        self.exe("flock", '[[ ! -e "$FIX/fail-lock" ]] || exit 1; exec /usr/bin/flock "$@"')
        virtualenv = self.project / ".venv/bin"
        virtualenv.mkdir(parents=True)
        self.exe_at(
            virtualenv / "python",
            """echo backup >> "$FIX/events"
[[ ! -e "$FIX/fail-backup" ]] || exit 1
while [[ "${1:-}" != --output-dir ]]; do shift; done
printf 'snapshot' > "$2/mvp-test.db"
""",
        )
        self.exe_at(
            virtualenv / "alembic",
            """echo "alembic $*" >> "$FIX/events"
[[ ! -e "$FIX/fail-migrate" ]] || exit 1
""",
        )
        self.common = self.root / "diagnostics.sh"
        self.common.write_text(COMMON)
        self.runner = self.root / "ops.sh"
        # Keep update decisions and traps; replace machine paths and identities.
        functions = OPS[OPS.index("MAINTENANCE_STARTED=false") :]
        functions = functions.replace(
            "/var/lib/solution-workspace-releases", str(self.root / "releases")
        ).replace("/root/.npm/_cacache", str(self.root / "absent-cache"))
        variables = {
            "PROJECT_DIR": self.project,
            "APP_USER": "test",
            "FRONTEND_USER": "test-web",
            "APP_GROUP": "test",
            "FRONTEND_GROUP": "test-web",
            "ENV_FILE": self.envfile,
            "DATA_DIR": self.data,
            "BACKUP_DIR": self.backups,
            "SCHEDULED_BACKUP_DIR": self.backups,
            "APP_HOME": self.root,
            "FRONTEND_HOME": self.root,
            "NODE_BIN": "/bin/true",
            "PYTHON_BIN": virtualenv / "python",
            "ALEMBIC_BIN": virtualenv / "alembic",
            "RUNUSER_BIN": self.bin / "runuser",
            "NPM_CACHE_DIR": self.root / "npm-cache",
            "UV_PYTHON_INSTALL_DIR": self.root,
            "UV_CACHE_DIR": self.root,
            "LOCK_FILE": self.root / "lock",
            "FRONTEND_PORT": "5174",
            "BACKEND_PORT": "8787",
        }
        prefix = "set -Eeuo pipefail\nsource " + shlex.quote(str(self.common)) + "\n"
        prefix += "\n".join(f"{key}={shlex.quote(str(value))}" for key, value in variables.items())
        prefix += '\nCOMMAND="$1"; shift\n'
        self.runner.write_text(prefix + functions)

    def exe_at(self, path, body):
        path.write_text(
            f"#!/usr/bin/env bash\nset -eu\nFIX={shlex.quote(str(self.root))}\n{body}\n"
        )
        path.chmod(0o755)

    def exe(self, name, body):
        self.exe_at(self.bin / name, body)

    def git(self, *args, cwd=None):
        return subprocess.check_output(
            ["git", "-C", str(cwd or self.project), *args],
            env=self.environment,
            text=True,
            stderr=subprocess.PIPE,
        )

    def bundle(self, *, extra_branch=False, full=False):
        installer = self.project / "deploy/systemd/install.sh"
        installer.parent.mkdir(parents=True)
        installer.write_text("#!/bin/bash\nsystemctl start solution-workspace.target\n")
        (self.project / "frontend/package.json").write_text('{"version":"2"}\n')
        self.git("add", ".")
        self.git("commit", "-qm", "candidate")
        self.target = self.git("rev-parse", "HEAD").strip()
        args = ["refs/heads/main"] if full else [f"{self.base}..refs/heads/main"]
        if extra_branch:
            self.git("branch", "dev")
            args.append("refs/heads/dev")
        self.package = self.root / "release.bundle"
        self.git("bundle", "create", str(self.package), *args)
        self.checksum()
        self.git("reset", "--hard", self.base)
        return self.package

    def checksum(self, text=None):
        digest = hashlib.sha256(self.package.read_bytes()).hexdigest()
        self.package.with_suffix(".bundle.sha256").write_text(
            text if text is not None else f"{digest}  {self.package.name}\n"
        )

    def run_ops(self, *args):
        return subprocess.run(
            ["bash", str(self.runner), *map(str, args)],
            cwd=self.root,
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=30,
        )

    def assert_preflight_rejection(self, result, code):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(code, result.stderr)
        self.assertNotIn("systemctl stop", self.events.read_text())
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)

    def test_offline_update_and_same_version_noop(self):
        self.bundle()
        result = self.run_ops("update", "--offline", self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.target)
        self.assertEqual((self.root / "state").read_text().strip(), "active")
        events = self.events.read_text()
        self.assertLess(events.index("npm"), events.index("systemctl stop"))
        self.assertLess(events.index("backup\n"), events.index("alembic upgrade"))
        self.assertTrue(list(self.backups.glob("updates/*/app.env.before")))
        self.events.write_text("")
        result = self.run_ops("update", "--offline", self.package)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("无需更新", result.stdout)
        self.assertNotIn("npm", self.events.read_text())
        self.assertNotIn("systemctl", self.events.read_text())

    def test_missing_checksum(self):
        self.bundle()
        self.package.with_suffix(".bundle.sha256").unlink()
        self.assert_preflight_rejection(
            self.run_ops("update", "--offline", self.package), "E_CHECKSUM_FILE"
        )

    def test_corrupted_checksum(self):
        self.bundle()
        self.checksum("0" * 64 + "  release.bundle\n")
        self.assert_preflight_rejection(
            self.run_ops("update", "--offline", self.package), "E_CHECKSUM_MISMATCH"
        )

    def test_checksum_cannot_select_another_path(self):
        self.bundle()
        self.checksum("0" * 64 + "  /etc/passwd\n")
        self.assert_preflight_rejection(
            self.run_ops("update", "--offline", self.package), "E_CHECKSUM_FORMAT"
        )

    def test_multiple_branches_require_selection(self):
        self.bundle(extra_branch=True)
        self.assert_preflight_rejection(
            self.run_ops("update", "--offline", self.package), "E_BUNDLE_BRANCH"
        )
        selected = self.run_ops("update", "--offline", self.package, "--branch", "main")
        self.assertEqual(selected.returncode, 0, selected.stdout + selected.stderr)

    def test_wrong_branch(self):
        self.bundle()
        self.assert_preflight_rejection(
            self.run_ops("update", "--offline", self.package, "--branch", "missing"),
            "E_BUNDLE_BRANCH",
        )

    def test_non_fast_forward_rejected(self):
        self.bundle()
        (self.project / "other").write_text("diverged")
        self.git("add", ".")
        self.git("commit", "-qm", "other branch")
        self.base = self.git("rev-parse", "HEAD").strip()
        self.assert_preflight_rejection(
            self.run_ops("update", "--offline", self.package), "E_NOT_FORWARD"
        )

    def test_missing_incremental_base(self):
        self.bundle()
        other = self.root / "empty"
        self.git("init", str(other), cwd=self.root)
        prepare = OPS[OPS.index("prepare_offline_bundle() {") : OPS.index("\ndoctor() {")]
        prepare = prepare.replace(
            "/var/lib/solution-workspace-releases", str(self.root / "releases")
        )
        program = (
            f'set -Eeuo pipefail\nsource "{self.common}"\nPROJECT_DIR="{other}"\nbranch=\n'
            + prepare
            + f'\nprepare_offline_bundle "{self.package}"'
        )
        result = subprocess.run(
            ["bash", "-c", program],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertIn("E_BUNDLE_VERIFY", result.stderr)

    def test_build_failure_keeps_current_services(self):
        self.bundle()
        (self.root / "fail-npm").touch()
        self.assert_preflight_rejection(
            self.run_ops("update", "--offline", self.package), "E_FRONTEND_BUILD"
        )

    def test_backup_failure_restores_unchanged_release(self):
        self.bundle()
        (self.root / "fail-backup").touch()
        result = self.run_ops("update", "--offline", self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("原服务及备份定时器已恢复", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.base)

    def test_failed_restart_never_claims_recovery(self):
        self.bundle()
        (self.root / "fail-backup").touch()
        (self.root / "fail-restart").touch()
        result = self.run_ops("update", "--offline", self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("服务恢复未通过检查", result.stderr)
        self.assertNotIn("已恢复并通过", result.stderr)

    def test_backup_failure_does_not_start_previously_stopped_application(self):
        self.bundle()
        (self.root / "state").write_text("inactive\n")
        (self.root / "fail-backup").touch()
        result = self.run_ops("update", "--offline", self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("操作前已停止", result.stderr)
        self.assertNotIn("systemctl start", self.events.read_text())

    def test_migration_failure_keeps_services_stopped_and_backup(self):
        self.bundle()
        (self.root / "fail-migrate").touch()
        result = self.run_ops("update", "--offline", self.package)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("E_MIGRATION", result.stderr)
        self.assertIn("回滚快照", result.stderr)
        self.assertIn("不要重复更新", result.stderr)
        self.assertEqual((self.root / "state").read_text().strip(), "inactive")
        self.assertTrue(list(self.backups.glob("updates/*/mvp-test.db")))

    def test_lock_failure(self):
        self.bundle()
        (self.root / "fail-lock").touch()
        self.assert_preflight_rejection(self.run_ops("update", "--offline", self.package), "E_LOCK")

    def test_bad_cli_argument_does_not_run_update(self):
        self.assert_preflight_rejection(self.run_ops("update", "--offline"), "E_ARGUMENT")

    def test_old_bundle_path_call_remains_compatible(self):
        self.bundle()
        result = self.run_ops("update", self.package, "main")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), self.target)

    def test_signal_after_database_change_keeps_maintenance(self):
        program = self.runner.read_text().split('case "${COMMAND}" in\n  doctor)')[0]
        self.runner.write_text(
            program + "\nMAINTENANCE_STARTED=true\nDATA_MAY_HAVE_CHANGED=true\nkill -TERM $$\n"
        )
        result = self.run_ops("update")
        self.assertEqual(result.returncode, 143, result.stdout + result.stderr)
        self.assertIn("E_INTERRUPTED", result.stderr)
        self.assertEqual((self.root / "state").read_text().strip(), "inactive")

    def test_switch_migration_failure_restores_original_config_and_files(self):
        target = self.data / "imported.db"
        target.write_bytes(b"imported database")
        before = self.envfile.read_bytes()
        # Exercise real rename/recovery/control flow; model SQLite validation and
        # cloning separately from the real SQLite backup tests.
        overrides = """
verify_database() { return 0; }
secure_database_permissions() { return 0; }
checkpoint_database() { return 0; }
clone_sqlite_database() { cp -- "$1" "$2"; }
"""
        self.runner.write_text(
            self.runner.read_text().replace(
                'case "${COMMAND}" in\n  doctor)', overrides + 'case "${COMMAND}" in\n  doctor)'
            )
        )
        (self.root / "fail-migrate").touch()
        result = self.run_ops("switch-db", target)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.envfile.read_bytes(), before)
        self.assertEqual(target.read_bytes(), b"imported database")
        self.assertIn("原数据库及配置已恢复", result.stderr)
        self.assertEqual((self.root / "state").read_text().strip(), "active")

    def test_source_tag_installs_exact_commit_even_when_main_advanced(self):
        self.bundle()
        self.git("reset", "--hard", self.target)
        self.git("tag", "v-test", self.base)
        self.git("checkout", "v-test")
        install_text = (ROOT / "deploy/ubuntu/install.sh").read_text(encoding="utf-8")
        materialize = install_text.split('log "Materializing a root-owned release checkout"')[1]
        materialize = materialize.split('chown -R root:root "${PROJECT_DIR}"')[0]
        destination = self.root / "installed"
        program = (
            f'set -Eeuo pipefail\nsource "{self.common}"\n'
            f'SOURCE_DIR="{self.project}"\nPROJECT_DIR="{destination}"\n' + materialize
        )
        result = subprocess.run(
            ["bash", "-c", program],
            env=self.environment,
            text=True,
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=destination).strip(), self.base)

    def test_partial_database_move_stays_stopped_without_overwriting_files(self):
        target = self.data / "imported.db"
        target.write_bytes(b"original import")
        overrides = """
verify_database() { return 0; }
secure_database_permissions() { return 0; }
checkpoint_database() { return 0; }
clone_sqlite_database() { cp -- "$1" "$2"; }
move_database_bundle() { mv -- "$1" "$2"; return 1; }
"""
        self.runner.write_text(
            self.runner.read_text().replace(
                'case "${COMMAND}" in\n  doctor)', overrides + 'case "${COMMAND}" in\n  doctor)'
            )
        )
        result = self.run_ops("switch-db", target)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("文件移动未完整结束", result.stderr)
        self.assertEqual((self.root / "state").read_text().strip(), "inactive")
        self.assertEqual(
            next(self.data.glob("imported.db.pre-switch-*")).read_bytes(), b"original import"
        )

    def test_disk_failure_happens_before_stopping_services(self):
        self.bundle()
        self.exe(
            "df",
            'printf "Filesystem 1B-blocks Used Available Use%% Mounted\\n'
            'fixture 100 99 1 99%% /\\n"',
        )
        self.assert_preflight_rejection(self.run_ops("update", "--offline", self.package), "E_DISK")

    def use_real_python(self):
        self.exe_at(self.project / ".venv/bin/python", 'exec /usr/bin/python3 "$@"')

    def test_doctor_missing_database_does_not_create_it(self):
        self.use_real_python()
        database = self.data / "active.db"
        database.unlink()
        result = self.run_ops("doctor")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("E_DOCTOR", result.stderr)
        self.assertIn("未创建或迁移数据库", result.stderr)
        self.assertEqual(list(self.data.iterdir()), [])
        self.assertNotIn("systemctl start", self.events.read_text())
        self.assertNotIn("systemctl stop", self.events.read_text())

    def test_database_diagnostics_preserve_contents_and_journal_mode(self):
        self.use_real_python()
        database = self.data / "active.db"
        database.unlink()
        with closing(sqlite3.connect(database)) as db:
            db.execute("CREATE TABLE alembic_version(version_num TEXT)")
            db.execute("INSERT INTO alembic_version VALUES ('test-revision')")
            db.commit()
        before = database.read_bytes()
        for command in ("doctor", "db-info"):
            with self.subTest(command=command):
                result = self.run_ops(command)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("test-revision", result.stdout)
                self.assertEqual(database.read_bytes(), before)
                self.assertEqual(list(self.data.iterdir()), [database])
                self.assertNotIn("alembic", self.events.read_text())

    def test_doctor_rejects_invalid_database_location(self):
        self.envfile.write_text("MVP_DATABASE_URL=sqlite:///relative.db\n")
        result = self.run_ops("doctor")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("E_DOCTOR", result.stderr)
        self.assertIn("SQLite 绝对路径", result.stderr)

    def test_diagnostics_redacts_credentials(self):
        program = (
            f'source "{self.common}"; printf "%s\\n" '
            "'https://user:private-token@example.invalid password=secret-value "
            "Authorization=Bearer abcdef' | workspace_redact"
        )
        result = subprocess.run(
            ["bash", "-c", program], text=True, capture_output=True, env=self.environment
        )
        self.assertNotIn("private-token", result.stdout)
        self.assertNotIn("secret-value", result.stdout)
        self.assertNotIn("abcdef", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
