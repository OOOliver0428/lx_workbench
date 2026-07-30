#!/usr/bin/env bash
set -Eeuo pipefail

readonly UNIT_DIR="/etc/systemd/system"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Usage:
  sudo bash ./deploy/systemd/install.sh /absolute/project/path [app-user] [node-bin]

Example:
  sudo bash ./deploy/systemd/install.sh /home/appuser/solution-department-weekly-report appuser
EOF
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

[[ "${EUID}" -eq 0 ]] || fail "run this installer with sudo"
[[ "$#" -ge 1 && "$#" -le 3 ]] || {
  usage
  exit 2
}

PROJECT_DIR="$(realpath -- "$1")"
APP_USER="${2:-appuser}"
NODE_BIN="${3:-}"

[[ -d "${PROJECT_DIR}" ]] || fail "project directory does not exist: ${PROJECT_DIR}"
[[ "${PROJECT_DIR}" != *[[:space:]]* ]] || fail "project path must not contain whitespace"
[[ "${APP_USER}" =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || fail "invalid service user: ${APP_USER}"
getent passwd "${APP_USER}" >/dev/null || fail "Linux user does not exist: ${APP_USER}"

[[ -f "${PROJECT_DIR}/server.py" ]] || fail "server.py was not found"
[[ -f "${PROJECT_DIR}/.env" ]] || fail "create and configure ${PROJECT_DIR}/.env first"
[[ -x "${PROJECT_DIR}/.venv/bin/python" ]] || fail "run 'uv sync --frozen --no-dev' first"
[[ -x "${PROJECT_DIR}/.venv/bin/alembic" ]] || fail "Alembic is missing from the project virtualenv"
[[ -f "${PROJECT_DIR}/frontend/package.json" ]] || fail "frontend/package.json was not found"
[[ -d "${PROJECT_DIR}/frontend/node_modules" ]] || fail "run 'npm ci' in frontend first"
[[ -f "${PROJECT_DIR}/frontend/node_modules/vinext/dist/cli.js" ]] || fail "Vinext runtime is missing"
[[ -d "${PROJECT_DIR}/frontend/dist" ]] || fail "run 'npm run build' in frontend first"

if [[ -z "${NODE_BIN}" ]]; then
  NODE_BIN="$(runuser -u "${APP_USER}" -- sh -lc 'command -v node' 2>/dev/null || true)"
fi
[[ -n "${NODE_BIN}" && -x "${NODE_BIN}" ]] || {
  fail "node was not found for ${APP_USER}; pass its absolute path as the third argument"
}
NODE_BIN="$(realpath -- "${NODE_BIN}")"
NODE_BIN_DIR="$(dirname -- "${NODE_BIN}")"

install -d -m 0750 -o "${APP_USER}" -g "${APP_USER}" \
  "${PROJECT_DIR}/data" \
  "${PROJECT_DIR}/backups"
chown "${APP_USER}:${APP_USER}" "${PROJECT_DIR}/.env"
chmod 0600 "${PROJECT_DIR}/.env"

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

project_escaped="$(escape_sed_replacement "${PROJECT_DIR}")"
user_escaped="$(escape_sed_replacement "${APP_USER}")"
node_escaped="$(escape_sed_replacement "${NODE_BIN}")"
node_dir_escaped="$(escape_sed_replacement "${NODE_BIN_DIR}")"
temporary_dir="$(mktemp -d)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

render_unit() {
  local source_file="$1"
  local destination_name="$2"
  sed \
    -e "s|@@PROJECT_DIR@@|${project_escaped}|g" \
    -e "s|@@APP_USER@@|${user_escaped}|g" \
    -e "s|@@NODE_BIN@@|${node_escaped}|g" \
    -e "s|@@NODE_BIN_DIR@@|${node_dir_escaped}|g" \
    "${source_file}" >"${temporary_dir}/${destination_name}"
  install -m 0644 "${temporary_dir}/${destination_name}" "${UNIT_DIR}/${destination_name}"
}

render_unit \
  "${SCRIPT_DIR}/solution-workspace-backend.service.in" \
  "solution-workspace-backend.service"
render_unit \
  "${SCRIPT_DIR}/solution-workspace-frontend.service.in" \
  "solution-workspace-frontend.service"
install -m 0644 \
  "${SCRIPT_DIR}/solution-workspace.target" \
  "${UNIT_DIR}/solution-workspace.target"

systemd-analyze verify \
  "${UNIT_DIR}/solution-workspace-backend.service" \
  "${UNIT_DIR}/solution-workspace-frontend.service" \
  "${UNIT_DIR}/solution-workspace.target"
systemctl daemon-reload
systemctl enable solution-workspace.target
systemctl restart solution-workspace-backend.service solution-workspace-frontend.service
systemctl start solution-workspace.target

printf '\nInstalled and started Solution Workspace.\n'
printf '  Frontend: http://SERVER_IP:5174/\n'
printf '  Backend:  http://SERVER_IP:8787/docs\n\n'
systemctl --no-pager --full status \
  solution-workspace-backend.service \
  solution-workspace-frontend.service || true
