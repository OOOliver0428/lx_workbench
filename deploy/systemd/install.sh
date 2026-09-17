#!/usr/bin/env bash
set -Eeuo pipefail
umask 0027

readonly UNIT_DIR="/etc/systemd/system"
readonly CONFIG_DIR="/etc/solution-workspace"
readonly OPS_BIN="/usr/local/sbin/solution-workspace"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
# shellcheck source=../lib/diagnostics.sh
source "${SCRIPT_DIR}/../lib/diagnostics.sh"

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

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535))
}

[[ "${1:-}" != "-h" && "${1:-}" != "--help" ]] || {
  usage
  exit 0
}
[[ "${EUID}" -eq 0 ]] || fail "权限不足，请使用 sudo 执行安装脚本。"
[[ "$#" -eq 9 ]] || {
  usage
  exit 2
}
workspace_stage "检查 systemd 安装参数" "新服务器请运行 deploy/ubuntu/install.sh；底层服务安装器需要完整的 9 个参数。" E_SERVICE_CONFIG

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
  getent passwd "${account_name}" >/dev/null || fail "服务账号不存在：${account_name}"
  [[ "$(id -u "${account_name}")" -ne 0 ]] || fail "应用服务不能使用 root 账号。"
done
BACKEND_GROUP="$(id -gn "${BACKEND_USER}")"
FRONTEND_GROUP="$(id -gn "${FRONTEND_USER}")"
APP_HOME="$(getent passwd "${BACKEND_USER}" | cut -d: -f6)"
LOCK_FILE="${CONFIG_DIR}/ops.lock"

[[ -d "${PROJECT_DIR}" ]] || fail "部署目录不存在：${PROJECT_DIR}"
[[ "${PROJECT_DIR}" == /opt/* \
  && "${PROJECT_DIR}" != *[[:space:]]* \
  && "${PROJECT_DIR}" != *"'"* ]] || {
  fail "部署路径必须位于 /opt 下，且不能包含空白或单引号。"
}
[[ "$(stat -c '%u' "${PROJECT_DIR}")" -eq 0 ]] || fail "部署目录必须由 root 持有。"
[[ -f "${PROJECT_DIR}/server.py" ]] || fail "缺少 server.py，请核对代码部署是否完整。"
[[ -f "${ENV_FILE}" ]] || fail "缺少运行配置：${ENV_FILE}；迁机请恢复原配置，勿重新生成加密密钥。"
[[ -x "${PROJECT_DIR}/.venv/bin/python" ]] || fail "Python 虚拟环境缺失；请先完成锁定依赖安装。"
[[ -x "${PROJECT_DIR}/.venv/bin/alembic" ]] || fail "Python 虚拟环境中缺少 Alembic，请检查依赖安装结果。"
[[ -f "${PROJECT_DIR}/frontend/package.json" ]] || fail "缺少 frontend/package.json，请核对发布代码。"
[[ -d "${PROJECT_DIR}/frontend/node_modules" ]] || fail "前端依赖未安装，请通过安装或更新流程以专用账号构建。"
[[ -f "${PROJECT_DIR}/frontend/node_modules/vinext/dist/cli.js" ]] || fail "缺少 Vinext 运行时，请检查前端依赖是否完整。"
[[ -d "${PROJECT_DIR}/frontend/dist" ]] || fail "前端生产构建缺失，请先完成构建。"
[[ -x "${NODE_BIN}" ]] || fail "Node.js 不存在或不可执行：${NODE_BIN}"
valid_port "${FRONTEND_PORT}" || fail "前端端口必须在 1–65535 之间。"
valid_port "${BACKEND_PORT}" || fail "后端端口必须在 1–65535 之间。"
FRONTEND_PORT="$((10#${FRONTEND_PORT}))"
BACKEND_PORT="$((10#${BACKEND_PORT}))"
[[ "${FRONTEND_PORT}" != "${BACKEND_PORT}" ]] || fail "前后端端口不能相同，请分别指定。"
for config_path in "${PROJECT_DIR}" "${NODE_BIN}" "${ENV_FILE}" "${DATA_DIR}" "${BACKUP_DIR}" "${APP_HOME}"; do
  [[ "${config_path}" =~ ^/[A-Za-z0-9_./-]+$ ]] || fail "服务路径包含不支持的字符：${config_path}；请使用无空格的常规绝对路径。" E_SERVICE_CONFIG
done
[[ "${BACKEND_USER}" != "${FRONTEND_USER}" ]] || fail "前后端必须使用不同的专用账号。" E_SERVICE_CONFIG
[[ -f "${PROJECT_DIR}/frontend/dist/server/index.js" ]] || fail "缺少前端生产构建入口；请完成构建后再安装服务。" E_BUILD
workspace_init_log systemd
SYSTEMD_MUTATED=false
workspace_on_failure() {
  if [[ "${SYSTEMD_MUTATED}" == true ]]; then
    systemctl stop solution-workspace.target solution-workspace-backup.timer \
      solution-workspace-backup.service solution-workspace-backend.service \
      solution-workspace-frontend.service || true
    WORKSPACE_STATE="服务安装失败，已尝试停服；请检查 systemctl status 和日志。数据库与配置保留。"
  else
    WORKSPACE_STATE="服务文件尚未替换，本次底层安装未启停应用。"
  fi
}

install -d -m 0750 -o root -g "${BACKEND_GROUP}" "${CONFIG_DIR}"
# The parent update/install holds fd 9. Reuse that open lock description rather
# than reopening the same lock and deadlocking against our own parent process.
if [[ "$(readlink "/proc/$$/fd/9" 2>/dev/null || true)" != "${LOCK_FILE}" ]]; then
  exec 9>>"${LOCK_FILE}"
fi
flock --wait 300 9 || fail "等待部署锁超时；请等待其他更新或备份任务结束。" E_LOCK

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
workspace_cleanup() { rm -rf -- "${temporary_dir}"; }

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
workspace_stage "校验生成的服务文件" "修复 systemd 校验错误后重试；不要跳过校验直接覆盖服务文件。" E_UNIT_VERIFY
workspace_run systemd-analyze verify \
  "${temporary_dir}/solution-workspace-backend.service" \
  "${temporary_dir}/solution-workspace-frontend.service" \
  "${temporary_dir}/solution-workspace-backup.service" \
  "${temporary_dir}/solution-workspace-backup.timer" \
  "${temporary_dir}/solution-workspace.target"

workspace_stage "安装服务文件和运维组件" "检查 /etc/systemd/system 与 /usr/local 的空间和权限。" E_SERVICE_INSTALL
SYSTEMD_MUTATED=true
for unit_name in \
  solution-workspace-backend.service \
  solution-workspace-frontend.service \
  solution-workspace-backup.service \
  solution-workspace-backup.timer \
  solution-workspace.target; do
  install -m 0644 "${temporary_dir}/${unit_name}" "${UNIT_DIR}/${unit_name}.next"
  mv -f -- "${UNIT_DIR}/${unit_name}.next" "${UNIT_DIR}/${unit_name}"
done

cat >"${CONFIG_DIR}/deploy.conf.next" <<EOF
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
chown root:"${BACKEND_GROUP}" "${CONFIG_DIR}/deploy.conf.next"
chmod 0640 "${CONFIG_DIR}/deploy.conf.next"
mv -f -- "${CONFIG_DIR}/deploy.conf.next" "${CONFIG_DIR}/deploy.conf"
install -d -m 0755 -o root -g root /usr/local/lib/solution-workspace
install -m 0644 -o root -g root "${PROJECT_DIR}/deploy/lib/diagnostics.sh" \
  /usr/local/lib/solution-workspace/diagnostics.sh.next
mv -f /usr/local/lib/solution-workspace/diagnostics.sh.next /usr/local/lib/solution-workspace/diagnostics.sh
# Rename over the running script instead of truncating its open file descriptor.
install -m 0755 -o root -g root "${PROJECT_DIR}/deploy/ubuntu/ops.sh" "${OPS_BIN}.next"
mv -f -- "${OPS_BIN}.next" "${OPS_BIN}"

workspace_stage "启动应用及自动备份" "执行 sudo solution-workspace status 和 logs 检查启动失败原因。" E_SERVICE_START
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
