#!/usr/bin/env bash
set -Eeuo pipefail
umask 0027

readonly UNIT_DIR="/etc/systemd/system"
readonly CONFIG_DIR="/etc/solution-workspace"
readonly OPS_BIN="/usr/local/sbin/solution-workspace"
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
Low-level systemd installer. For a fresh Ubuntu server, use:
  sudo bash deploy/ubuntu/install.sh --public-host SERVER_IP

Usage:
  sudo bash deploy/systemd/install.sh \
    PROJECT_DIR BACKEND_USER FRONTEND_USER NODE_BIN ENV_FILE DATA_DIR \
    BACKUP_DIR FRONTEND_PORT BACKEND_PORT
EOF
}

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535))
}

[[ "${1:-}" != "-h" && "${1:-}" != "--help" ]] || {
  usage
  exit 0
}
[[ "${EUID}" -eq 0 ]] || fail "run this installer with sudo"
[[ "$#" -eq 9 ]] || {
  usage
  exit 2
}

PROJECT_DIR="$(realpath -- "$1")"
BACKEND_USER="$2"
FRONTEND_USER="$3"
NODE_BIN="$(realpath -- "$4")"
ENV_FILE="$(realpath -- "$5")"
DATA_DIR="$(realpath -- "$6")"
BACKUP_DIR="$(realpath -- "$7")"
FRONTEND_PORT="$8"
BACKEND_PORT="$9"

for account_name in "${BACKEND_USER}" "${FRONTEND_USER}"; do
  getent passwd "${account_name}" >/dev/null || fail "Linux user does not exist: ${account_name}"
  [[ "$(id -u "${account_name}")" -ne 0 ]] || fail "service user must not be root"
done
BACKEND_GROUP="$(id -gn "${BACKEND_USER}")"
FRONTEND_GROUP="$(id -gn "${FRONTEND_USER}")"
APP_HOME="$(getent passwd "${BACKEND_USER}" | cut -d: -f6)"
LOCK_FILE="${CONFIG_DIR}/ops.lock"

[[ -d "${PROJECT_DIR}" ]] || fail "project directory does not exist: ${PROJECT_DIR}"
[[ "${PROJECT_DIR}" == /opt/* \
  && "${PROJECT_DIR}" != *[[:space:]]* \
  && "${PROJECT_DIR}" != *"'"* ]] || {
  fail "project path must be a whitespace-free path below /opt"
}
[[ "$(stat -c '%u' "${PROJECT_DIR}")" -eq 0 ]] || fail "project must be owned by root"
[[ -f "${PROJECT_DIR}/server.py" ]] || fail "server.py was not found"
[[ -f "${ENV_FILE}" ]] || fail "runtime environment file was not found: ${ENV_FILE}"
[[ -x "${PROJECT_DIR}/.venv/bin/python" ]] || fail "run 'uv sync --frozen --no-dev' first"
[[ -x "${PROJECT_DIR}/.venv/bin/alembic" ]] || fail "Alembic is missing from the virtualenv"
[[ -f "${PROJECT_DIR}/frontend/package.json" ]] || fail "frontend/package.json was not found"
[[ -d "${PROJECT_DIR}/frontend/node_modules" ]] || fail "run 'npm ci' in frontend first"
[[ -f "${PROJECT_DIR}/frontend/node_modules/vinext/dist/cli.js" ]] || fail "Vinext runtime is missing"
[[ -d "${PROJECT_DIR}/frontend/dist" ]] || fail "run 'npm run build' in frontend first"
[[ -x "${NODE_BIN}" ]] || fail "node executable was not found: ${NODE_BIN}"
valid_port "${FRONTEND_PORT}" || fail "invalid frontend port"
valid_port "${BACKEND_PORT}" || fail "invalid backend port"
[[ "${FRONTEND_PORT}" != "${BACKEND_PORT}" ]] || fail "frontend and backend ports must differ"

NODE_BIN_DIR="$(dirname -- "${NODE_BIN}")"
install -d -m 0750 -o "${BACKEND_USER}" -g "${BACKEND_GROUP}" "${DATA_DIR}"
install -d -m 0755 -o root -g root "${BACKUP_DIR}"
install -d -m 0750 -o "${BACKEND_USER}" -g "${BACKEND_GROUP}" \
  "${BACKUP_DIR}/scheduled"
chown root:"${BACKEND_GROUP}" "${ENV_FILE}"
chmod 0640 "${ENV_FILE}"

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

project_escaped="$(escape_sed_replacement "${PROJECT_DIR}")"
backend_user_escaped="$(escape_sed_replacement "${BACKEND_USER}")"
backend_group_escaped="$(escape_sed_replacement "${BACKEND_GROUP}")"
frontend_user_escaped="$(escape_sed_replacement "${FRONTEND_USER}")"
frontend_group_escaped="$(escape_sed_replacement "${FRONTEND_GROUP}")"
node_escaped="$(escape_sed_replacement "${NODE_BIN}")"
node_dir_escaped="$(escape_sed_replacement "${NODE_BIN_DIR}")"
env_escaped="$(escape_sed_replacement "${ENV_FILE}")"
data_escaped="$(escape_sed_replacement "${DATA_DIR}")"
backup_escaped="$(escape_sed_replacement "${BACKUP_DIR}")"
lock_escaped="$(escape_sed_replacement "${LOCK_FILE}")"
frontend_port_escaped="$(escape_sed_replacement "${FRONTEND_PORT}")"
backend_port_escaped="$(escape_sed_replacement "${BACKEND_PORT}")"
temporary_dir="$(mktemp -d)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

render_unit() {
  local source_file="$1"
  local destination_name="$2"
  sed \
    -e "s|@@PROJECT_DIR@@|${project_escaped}|g" \
    -e "s|@@BACKEND_USER@@|${backend_user_escaped}|g" \
    -e "s|@@BACKEND_GROUP@@|${backend_group_escaped}|g" \
    -e "s|@@FRONTEND_USER@@|${frontend_user_escaped}|g" \
    -e "s|@@FRONTEND_GROUP@@|${frontend_group_escaped}|g" \
    -e "s|@@NODE_BIN@@|${node_escaped}|g" \
    -e "s|@@NODE_BIN_DIR@@|${node_dir_escaped}|g" \
    -e "s|@@ENV_FILE@@|${env_escaped}|g" \
    -e "s|@@DATA_DIR@@|${data_escaped}|g" \
    -e "s|@@BACKUP_DIR@@|${backup_escaped}|g" \
    -e "s|@@LOCK_FILE@@|${lock_escaped}|g" \
    -e "s|@@FRONTEND_PORT@@|${frontend_port_escaped}|g" \
    -e "s|@@BACKEND_PORT@@|${backend_port_escaped}|g" \
    "${source_file}" >"${temporary_dir}/${destination_name}"
}

render_unit \
  "${SCRIPT_DIR}/solution-workspace-backend.service.in" \
  "solution-workspace-backend.service"
render_unit \
  "${SCRIPT_DIR}/solution-workspace-frontend.service.in" \
  "solution-workspace-frontend.service"
render_unit \
  "${SCRIPT_DIR}/solution-workspace-backup.service.in" \
  "solution-workspace-backup.service"
cp -- "${SCRIPT_DIR}/solution-workspace.target" "${temporary_dir}/solution-workspace.target"
cp -- "${SCRIPT_DIR}/solution-workspace-backup.timer" \
  "${temporary_dir}/solution-workspace-backup.timer"

install -d -m 0750 -o root -g "${BACKEND_GROUP}" "${CONFIG_DIR}"
touch "${LOCK_FILE}"
chown root:"${BACKEND_GROUP}" "${LOCK_FILE}"
chmod 0660 "${LOCK_FILE}"

# Verify all rendered units before replacing any known-good installed unit.
systemd-analyze verify \
  "${temporary_dir}/solution-workspace-backend.service" \
  "${temporary_dir}/solution-workspace-frontend.service" \
  "${temporary_dir}/solution-workspace-backup.service" \
  "${temporary_dir}/solution-workspace-backup.timer" \
  "${temporary_dir}/solution-workspace.target"

for unit_name in \
  solution-workspace-backend.service \
  solution-workspace-frontend.service \
  solution-workspace-backup.service \
  solution-workspace-backup.timer \
  solution-workspace.target; do
  install -m 0644 "${temporary_dir}/${unit_name}" "${UNIT_DIR}/${unit_name}"
done

cat >"${CONFIG_DIR}/deploy.conf" <<EOF
PROJECT_DIR='${PROJECT_DIR}'
APP_USER='${BACKEND_USER}'
FRONTEND_USER='${FRONTEND_USER}'
APP_HOME='${APP_HOME}'
NODE_BIN='${NODE_BIN}'
ENV_FILE='${ENV_FILE}'
DATA_DIR='${DATA_DIR}'
BACKUP_DIR='${BACKUP_DIR}'
FRONTEND_PORT='${FRONTEND_PORT}'
BACKEND_PORT='${BACKEND_PORT}'
UV_PYTHON_INSTALL_DIR='/opt/solution-workspace-runtime/python'
UV_CACHE_DIR='/var/cache/solution-workspace/uv'
LOCK_FILE='${LOCK_FILE}'
EOF
chown root:"${BACKEND_GROUP}" "${CONFIG_DIR}/deploy.conf"
chmod 0640 "${CONFIG_DIR}/deploy.conf"
install -m 0755 -o root -g root "${PROJECT_DIR}/deploy/ubuntu/ops.sh" "${OPS_BIN}"

systemctl daemon-reload
systemctl enable solution-workspace.target
systemctl enable solution-workspace-backup.timer
systemctl restart solution-workspace-backend.service solution-workspace-frontend.service
systemctl start solution-workspace.target
systemctl start solution-workspace-backup.timer

printf '\nInstalled and started Solution Workspace.\n'
printf '  Frontend: http://SERVER_IP:%s/\n' "${FRONTEND_PORT}"
printf '  Backend:  loopback-only port %s\n' "${BACKEND_PORT}"
printf '  Ops:      sudo solution-workspace help\n\n'
systemctl --no-pager --full status \
  solution-workspace-backend.service \
  solution-workspace-frontend.service \
  solution-workspace-backup.timer || true
