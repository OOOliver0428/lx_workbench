#!/usr/bin/env bash
set -Eeuo pipefail
umask 0022
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
# shellcheck source=../lib/diagnostics.sh
source "${SCRIPT_DIR}/../lib/diagnostics.sh"
DEFAULT_SOURCE_DIR="$(realpath -- "${SCRIPT_DIR}/../..")"
readonly DEFAULT_SOURCE_DIR
readonly CONFIG_DIR="/etc/solution-workspace"
readonly ENV_FILE="${CONFIG_DIR}/app.env"
readonly DATA_DIR="/var/lib/solution-workspace"
readonly BACKUP_DIR="/var/backups/solution-workspace"
readonly SCHEDULED_BACKUP_DIR="${BACKUP_DIR}/scheduled"
readonly PYTHON_RUNTIME_DIR="/opt/solution-workspace-runtime/python"
readonly UV_CACHE_DIR="/var/cache/solution-workspace/uv"
readonly NPM_CACHE_DIR="/var/cache/solution-workspace/npm"
readonly BACKEND_USER="solution-workspace"
readonly FRONTEND_USER="solution-workspace-web"
readonly FRONTEND_HOME="/var/lib/solution-workspace-web-home"
readonly UV_VERSION="0.11.32"
readonly NODE_VERSION="22.23.1"

SOURCE_DIR="${DEFAULT_SOURCE_DIR}"
PROJECT_DIR="/opt/solution-workspace"
PUBLIC_HOST=""
FRONTEND_PORT="5174"
BACKEND_PORT="8787"
DATABASE_URL=""
INSTALL_PACKAGES="true"
REPAIR_STOPPED_INSTALL="false"

usage() {
  cat <<'EOF'
Ubuntu one-command deployment for Solution Workspace MVP.

Usage:
  sudo bash deploy/ubuntu/install.sh --public-host HOST [options]

Options:
  --source-dir PATH        Source release checkout (main branch or a version tag)
  --install-dir PATH       Root-owned release checkout below /opt
                           (default: /opt/solution-workspace)
  --public-host HOST       Required server IP or DNS name allowed by backend
  --frontend-port PORT     Browser-facing port (default: 5174)
  --backend-port PORT      Loopback-only backend port (default: 8787)
  --database-url URL       Initial SQLite URL; only used when app.env is absent
  --skip-system-packages   Require Node.js, uv and OS packages to exist already
  --repair-stopped-install Repair an incomplete, fully stopped /opt deployment
  -h, --help               Show this help

Example:
  sudo bash deploy/ubuntu/install.sh --public-host 10.20.30.40
EOF
}

valid_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535))
}

version_at_least() {
  local actual="$1"
  local required="$2"
  [[ "$(printf '%s\n%s\n' "${required}" "${actual}" | sort -V | head -n1)" == "${required}" ]]
}

ensure_service_account() {
  local account_name="$1"
  local account_home="$2"
  local passwd_entry uid_value uid_min shell_value home_value
  uid_min="$(awk '$1 == "UID_MIN" { print $2; exit }' /etc/login.defs)"
  uid_min="${uid_min:-1000}"

  if ! getent passwd "${account_name}" >/dev/null; then
    useradd \
      --system \
      --create-home \
      --home-dir "${account_home}" \
      --shell /usr/sbin/nologin \
      "${account_name}"
  fi

  passwd_entry="$(getent passwd "${account_name}")"
  uid_value="$(cut -d: -f3 <<<"${passwd_entry}")"
  home_value="$(cut -d: -f6 <<<"${passwd_entry}")"
  shell_value="$(cut -d: -f7 <<<"${passwd_entry}")"
  ((uid_value > 0 && uid_value < uid_min)) || {
    fail "${account_name} must be a non-root system account"
  }
  [[ "${home_value}" == "${account_home}" ]] || {
    fail "${account_name} has unexpected home ${home_value}; expected ${account_home}"
  }
  [[ "${shell_value}" == "/usr/sbin/nologin" || "${shell_value}" == "/bin/false" ]] || {
    fail "${account_name} must use nologin or false as its shell"
  }
}

while [[ "$#" -gt 0 ]]; do
  case "$1" in
    --source-dir)
      [[ "$#" -ge 2 ]] || fail "--source-dir requires a value"
      SOURCE_DIR="$2"
      shift 2
      ;;
    --install-dir)
      [[ "$#" -ge 2 ]] || fail "--install-dir requires a value"
      PROJECT_DIR="$2"
      shift 2
      ;;
    --public-host)
      [[ "$#" -ge 2 ]] || fail "--public-host requires a value"
      PUBLIC_HOST="$2"
      shift 2
      ;;
    --frontend-port)
      [[ "$#" -ge 2 ]] || fail "--frontend-port requires a value"
      FRONTEND_PORT="$2"
      shift 2
      ;;
    --backend-port)
      [[ "$#" -ge 2 ]] || fail "--backend-port requires a value"
      BACKEND_PORT="$2"
      shift 2
      ;;
    --database-url)
      [[ "$#" -ge 2 ]] || fail "--database-url requires a value"
      DATABASE_URL="$2"
      shift 2
      ;;
    --skip-system-packages)
      INSTALL_PACKAGES="false"
      shift
      ;;
    --repair-stopped-install)
      REPAIR_STOPPED_INSTALL="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

[[ "${EUID}" -eq 0 ]] || fail "权限不足，请使用 sudo 执行安装脚本。"
[[ -r /etc/os-release ]] || fail "无法读取 /etc/os-release，不能确认操作系统。"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || fail "此安装器仅支持 Ubuntu；其他系统需要适配部署流程。"
[[ -d /run/systemd/system ]] || fail "未检测到正在运行的 systemd；请在 Ubuntu 主机中安装，容器或未启用 systemd 的 WSL 不适用。" E_PLATFORM
for bootstrap_command in realpath git systemctl; do
  command -v "${bootstrap_command}" >/dev/null 2>&1 || {
    fail "安装前缺少 ${bootstrap_command} 命令，请先补齐系统工具。"
  }
done
workspace_init_log install
workspace_stage "检查安装参数、源码和现有部署" "新服务器使用 --public-host 指定 IP 或域名；已有部署应使用 update，修复安装必须先停服。" E_INSTALL_CHECK

SOURCE_DIR="$(realpath -- "${SOURCE_DIR}")"
PROJECT_DIR="$(realpath --canonicalize-missing -- "${PROJECT_DIR}")"
[[ -d "${SOURCE_DIR}/.git" ]] || fail "源码目录不是 Git 仓库，请先克隆完整的发布代码。"
[[ -f "${SOURCE_DIR}/uv.lock" ]] || fail "源码目录 ${SOURCE_DIR} 缺少 uv.lock，不能安装未锁定的依赖。"
[[ -f "${SOURCE_DIR}/frontend/package-lock.json" ]] || fail "源码缺少 frontend/package-lock.json，请核对发布内容。"
[[ "${SOURCE_DIR}" != *[[:space:]]* ]] || fail "源码路径不能包含空格或换行。"
[[ "${PROJECT_DIR}" == /opt/* \
  && "${PROJECT_DIR}" != *[[:space:]]* \
  && "${PROJECT_DIR}" != *"'"* ]] || {
  fail "安装目录必须位于 /opt 下，且不能包含空白或单引号。"
}
[[ -n "${PUBLIC_HOST}" ]] || fail "缺少 --public-host；请填写用户访问的服务器 IP 或域名。"
[[ "${PUBLIC_HOST}" =~ ^[A-Za-z0-9._:-]+$ ]] || fail "无效访问主机：${PUBLIC_HOST}；只填写 IP 或域名，不要包含协议或路径。"
valid_port "${FRONTEND_PORT}" || fail "前端端口必须为 1–65535：${FRONTEND_PORT}"
valid_port "${BACKEND_PORT}" || fail "后端端口必须为 1–65535：${BACKEND_PORT}"
FRONTEND_PORT="$((10#${FRONTEND_PORT}))"
BACKEND_PORT="$((10#${BACKEND_PORT}))"
[[ "${FRONTEND_PORT}" != "${BACKEND_PORT}" ]] || fail "前后端端口不能相同，请分别指定。"

source_branch="$(git -C "${SOURCE_DIR}" branch --show-current)"
source_tag="$(git -C "${SOURCE_DIR}" describe --tags --exact-match HEAD 2>/dev/null || true)"
[[ "${source_branch}" == "main" || -n "${source_tag}" ]] || {
  fail "源码需要检出 main 或发布标签；请先定位到已评审的发布提交。"
}
source_changes="$(git -C "${SOURCE_DIR}" status --porcelain)"
[[ -z "${source_changes}" ]] || fail "源码目录有未提交改动，请妥善保存后使用干净的发布仓库。"
[[ ! -L "${CONFIG_DIR}" ]] || fail "配置目录不能是符号链接：${CONFIG_DIR}" E_CONFIG
if [[ ! -d "${CONFIG_DIR}" ]]; then
  install -d -m 0750 -o root -g root "${CONFIG_DIR}"
fi
[[ "$(stat -c '%u' "${CONFIG_DIR}")" -eq 0 \
  && -z "$(find "${CONFIG_DIR}" -maxdepth 0 -perm /022 -print)" ]] || fail "配置目录须由 root 持有且不可被其他账号写入。" E_CONFIG
command -v flock >/dev/null || fail "缺少 flock，请安装 util-linux 后重试。" E_DEPENDENCY
exec 9>>"${CONFIG_DIR}/ops.lock"
flock --wait 300 9 || fail "等待部署锁超时；请等待已有安装、升级或备份结束，不要删除锁文件。" E_LOCK
if [[ -d "${PROJECT_DIR}/.git" ]]; then
  [[ "${REPAIR_STOPPED_INSTALL}" == "true" ]] || {
    fail "安装目录已有部署；日常升级请使用 sudo solution-workspace update。"
  }
  for existing_unit in \
    solution-workspace-backend.service \
    solution-workspace-frontend.service \
    solution-workspace-backup.service \
    solution-workspace-backup.timer; do
    systemctl is-active --quiet "${existing_unit}" && {
      fail "修复安装前必须停止所有应用和备份任务；仍在运行：${existing_unit}"
    }
  done
fi

INSTALL_MUTATED=false
INSTALL_SERVICES_STARTED=false
workspace_on_failure() {
  if [[ "${INSTALL_SERVICES_STARTED}" == true ]]; then
    systemctl stop solution-workspace.target solution-workspace-backup.timer \
      solution-workspace-backup.service solution-workspace-backend.service \
      solution-workspace-frontend.service || true
    WORKSPACE_STATE="安装未完成，已尝试停止应用与备份服务；请检查 systemctl status。配置与数据库保留。"
  elif [[ "${INSTALL_MUTATED}" == true ]]; then
    WORKSPACE_STATE="安装未完成；已创建的运行时、代码、配置或数据被保留，尚未启动应用。"
  fi
}
workspace_cleanup() {
  local candidate
  for candidate in "${temporary_node_dir:-}" "${temporary_uv_dir:-}"; do
    [[ -z "${candidate}" ]] || rm -rf -- "${candidate}"
  done
  [[ -z "${temporary_env:-}" ]] || rm -f -- "${temporary_env}"
}
workspace_require_space /opt 2147483648
INSTALL_MUTATED=true
WORKSPACE_STATE="正在准备新服务器安装，已创建的文件会在失败时保留。"

if [[ -z "${DATABASE_URL}" ]]; then
  DATABASE_URL="sqlite:////var/lib/solution-workspace/trial.db"
fi
[[ "${DATABASE_URL}" == sqlite:////* \
  && "${DATABASE_URL}" != *[[:space:]]* \
  && "${DATABASE_URL}" != *"'"* ]] || {
  fail "数据库配置须为 sqlite://// 开头的绝对路径，不能包含空白或单引号。"
}
database_path="${DATABASE_URL#sqlite:///}"
database_path="$(realpath --canonicalize-missing -- "${database_path}")"
data_root="$(realpath --canonicalize-missing -- "${DATA_DIR}")"
[[ "${database_path}" == "${data_root}/"* && "${database_path}" == *.db ]] || {
  fail "数据库必须是 ${DATA_DIR} 内的 .db 文件。"
}
DATABASE_URL="sqlite:///${database_path}"

if [[ "${INSTALL_PACKAGES}" == "true" ]]; then
  workspace_stage "安装系统软件与运行时" "检查 Ubuntu 软件源、Node.js/uv 下载连接、DNS 与磁盘空间；离线代码包不包含这些安装依赖。" E_RUNTIME
  log "Installing Ubuntu prerequisites"
  export DEBIAN_FRONTEND=noninteractive
  workspace_run apt-get update
  workspace_run apt-get install -y --no-install-recommends \
    ca-certificates curl git openssl build-essential util-linux xz-utils

  node_version=""
  if command -v node >/dev/null 2>&1; then
    node_version="$(node --version | sed 's/^v//')"
  fi
  if [[ -z "${node_version}" ]] || ! version_at_least "${node_version}" "${NODE_VERSION}"; then
    log "Installing verified Node.js ${NODE_VERSION} binary"
    machine_arch="$(uname -m)"
    case "${machine_arch}" in
      x86_64) node_arch="x64" ;;
      aarch64|arm64) node_arch="arm64" ;;
      *) fail "暂不支持该 CPU 架构的 Node.js 自动安装：${machine_arch}" ;;
    esac
    node_archive="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"
    temporary_node_dir="$(mktemp -d)"
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
      "https://nodejs.org/dist/v${NODE_VERSION}/${node_archive}" \
      --output "${temporary_node_dir}/${node_archive}"
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
      "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" \
      --output "${temporary_node_dir}/SHASUMS256.txt"
    (
      cd "${temporary_node_dir}"
      grep "  ${node_archive}\$" SHASUMS256.txt | sha256sum --check --strict -
    )
    tar -xJf "${temporary_node_dir}/${node_archive}" -C /opt
    ln -sfn "/opt/node-v${NODE_VERSION}-linux-${node_arch}/bin/node" /usr/local/bin/node
    ln -sfn "/opt/node-v${NODE_VERSION}-linux-${node_arch}/bin/npm" /usr/local/bin/npm
    ln -sfn "/opt/node-v${NODE_VERSION}-linux-${node_arch}/bin/npx" /usr/local/bin/npx
    ln -sfn "/opt/node-v${NODE_VERSION}-linux-${node_arch}/bin/corepack" /usr/local/bin/corepack
  fi

  uv_version=""
  if command -v uv >/dev/null 2>&1; then
    uv_version="$(uv --version | awk '{print $2}')"
  fi
  if [[ -z "${uv_version}" ]] || ! version_at_least "${uv_version}" "0.11.0"; then
    log "Installing verified uv ${UV_VERSION} binaries"
    machine_arch="$(uname -m)"
    case "${machine_arch}" in
      x86_64)
        uv_target="x86_64-unknown-linux-gnu"
        uv_sha256="aab924fd522efd06f1c5f3b93a243864fc453132c94b2dc49f1371b528a4b967"
        ;;
      aarch64|arm64)
        uv_target="aarch64-unknown-linux-gnu"
        uv_sha256="4d4fa08d95b06642e5800df6a22bd71455f23f988269e18da2847971d8c0bf31"
        ;;
      *) fail "暂不支持该 CPU 架构的 uv 自动安装：${machine_arch}" ;;
    esac
    uv_archive="uv-${uv_target}.tar.gz"
    temporary_uv_dir="$(mktemp -d)"
    curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
      "https://releases.astral.sh/github/uv/releases/download/${UV_VERSION}/${uv_archive}" \
      --output "${temporary_uv_dir}/${uv_archive}"
    printf '%s  %s\n' "${uv_sha256}" "${temporary_uv_dir}/${uv_archive}" \
      | sha256sum --check --strict -
    tar -xzf "${temporary_uv_dir}/${uv_archive}" -C "${temporary_uv_dir}"
    install -m 0755 -o root -g root \
      "${temporary_uv_dir}/uv-${uv_target}/uv" /usr/local/bin/uv
    install -m 0755 -o root -g root \
      "${temporary_uv_dir}/uv-${uv_target}/uvx" /usr/local/bin/uvx
  fi
fi

for required_command in git uv node npm curl flock openssl runuser systemctl; do
  command -v "${required_command}" >/dev/null 2>&1 || fail "缺少必需命令 ${required_command}，请补齐依赖后重试。"
done
node_version="$(node --version | sed 's/^v//')"
version_at_least "${node_version}" "${NODE_VERSION}" || {
  fail "Node.js 版本过低，至少需要 ${NODE_VERSION}。"
}
uv_version="$(uv --version | awk '{print $2}')"
version_at_least "${uv_version}" "0.11.0" || fail "uv 版本过低，至少需要 0.11.0。"

workspace_stage "创建服务账号与部署配置" "已有账号需满足专用系统账号要求；迁机必须保留原 app.env 中的加密密钥。" E_CONFIG
log "Creating dedicated service accounts"
ensure_service_account "${BACKEND_USER}" "/var/lib/solution-workspace-home"
ensure_service_account "${FRONTEND_USER}" "${FRONTEND_HOME}"
BACKEND_GROUP="$(id -gn "${BACKEND_USER}")"
FRONTEND_GROUP="$(id -gn "${FRONTEND_USER}")"

log "Preparing configuration and runtime directories"
install -d -m 0750 -o "${BACKEND_USER}" -g "${BACKEND_GROUP}" "${DATA_DIR}"
install -d -m 0755 -o root -g root "${BACKUP_DIR}"
install -d -m 0750 -o "${BACKEND_USER}" -g "${BACKEND_GROUP}" \
  "${SCHEDULED_BACKUP_DIR}"
install -d -m 0755 -o root -g root \
  "${PYTHON_RUNTIME_DIR}" "${UV_CACHE_DIR}" "$(dirname -- "${PROJECT_DIR}")"
install -d -m 0750 -o "${FRONTEND_USER}" -g "${FRONTEND_GROUP}" \
  "${NPM_CACHE_DIR}"
if [[ ! -d "${NPM_CACHE_DIR}/_cacache" && -d /root/.npm/_cacache ]]; then
  cp -a -- /root/.npm/_cacache "${NPM_CACHE_DIR}/_cacache"
  chown -R "${FRONTEND_USER}:${FRONTEND_GROUP}" "${NPM_CACHE_DIR}/_cacache"
fi
install -d -m 0750 -o root -g "${BACKEND_GROUP}" "${CONFIG_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  llm_secret="$(openssl rand -hex 32)"
  temporary_env="$(mktemp)"
  cat >"${temporary_env}" <<EOF
MVP_ENVIRONMENT=production
MVP_DATABASE_URL=${DATABASE_URL}
MVP_SERVER_HOST=127.0.0.1
MVP_SERVER_PORT=${BACKEND_PORT}
MVP_SESSION_COOKIE_NAME=mvp_session
MVP_SESSION_TTL_HOURS=12
MVP_COOKIE_SECURE=false
MVP_ALLOWED_HOSTS_CSV=${PUBLIC_HOST},127.0.0.1,localhost
MVP_CORS_ORIGINS_CSV=
MVP_LOG_LEVEL=INFO
MVP_API_MAX_BODY_BYTES=262144
MVP_LOGIN_VERIFICATION_LIMIT_PER_MINUTE=120
MVP_LOGIN_SOURCE_LIMIT_PER_MINUTE=60
MVP_LOGIN_MAX_CONCURRENT_VERIFICATIONS=2
MVP_LOGIN_THROTTLE_MAX_KEYS=2048
MVP_LOGIN_FAILURE_AUDIT_LIMIT_PER_MINUTE=20
MVP_LOGIN_FAILURE_AUDIT_RETENTION_DAYS=90
MVP_LOGIN_FAILURE_AUDIT_MAX_ROWS=10000
MVP_LLM_MAX_CONCURRENT_GENERATIONS=2
MVP_LLM_MAX_USER_CONCURRENT_GENERATIONS=1
MVP_LLM_USER_REQUESTS_PER_HOUR=20
MVP_LLM_USER_TOKENS_PER_DAY=100000
MVP_LLM_GLOBAL_TOKENS_PER_DAY=1000000
MVP_LLM_MAX_TRACKED_USERS=10000
MVP_LLM_CHAT_COOLDOWN_SECONDS=2
MVP_LLM_WEEKLY_COOLDOWN_SECONDS=60
MVP_LLM_TEAM_SUMMARY_COOLDOWN_SECONDS=60
MVP_LLM_CONFIG_SECRET=${llm_secret}
MVP_LLM_TIMEOUT_SECONDS=60
MVP_LLM_TEST_TOKEN_TTL_SECONDS=600
MVP_MINIMAX_API_KEY=
MVP_MINIMAX_BASE_URL=https://api.minimaxi.com/v1
MVP_MINIMAX_MODEL=MiniMax-M2.7
MVP_MINIMAX_ACCESS_MODE=auto
MVP_MINIMAX_TIMEOUT_SECONDS=60
EOF
  install -m 0640 -o root -g "${BACKEND_GROUP}" "${temporary_env}" "${ENV_FILE}"
  rm -f -- "${temporary_env}"
else
  log "Keeping existing ${ENV_FILE}"
fi

workspace_stage "安装指定提交的代码" "检查源码仓库、目标路径与提交；不要用不对应的 main 替代发布标签。" E_RELEASE
log "Materializing a root-owned release checkout"
source_commit="$(git -C "${SOURCE_DIR}" rev-parse HEAD)"
origin_url="$(git -C "${SOURCE_DIR}" remote get-url origin 2>/dev/null || true)"
if [[ "${SOURCE_DIR}" != "${PROJECT_DIR}" ]]; then
  if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
    [[ ! -e "${PROJECT_DIR}" ]] || fail "安装目录已存在但不是 Git 仓库；请核对路径，安装器不会覆盖该目录。"
    workspace_run git clone --no-local --no-checkout "${SOURCE_DIR}" "${PROJECT_DIR}"
  else
    deployed_changes="$(git -C "${PROJECT_DIR}" status --porcelain --untracked-files=no)"
    [[ -z "${deployed_changes}" ]] || fail "部署目录有已跟踪文件被修改；请先保存并处理改动。"
  fi
  workspace_run git -C "${PROJECT_DIR}" fetch --no-tags -- "${SOURCE_DIR}" "${source_commit}"
  workspace_run git -C "${PROJECT_DIR}" checkout -B main "${source_commit}"
  if [[ -n "${origin_url}" ]]; then
    git -C "${PROJECT_DIR}" remote set-url origin "${origin_url}"
  fi
else
  [[ "${PROJECT_DIR}" == /opt/* ]] || fail "原地安装的源码目录必须位于 /opt 下。"
fi
[[ "$(git -C "${PROJECT_DIR}" rev-parse HEAD)" == "${source_commit}" ]] || {
  fail "安装后的提交与选定的源码提交不一致，已停止安装。"
}
chown -R root:root "${PROJECT_DIR}"
chmod -R u=rwX,go=rX "${PROJECT_DIR}"

workspace_stage "安装 Python 及锁定依赖" "检查 Python 下载、uv 软件源、缓存与磁盘空间；错误日志会保留。" E_PYTHON
export UV_PYTHON_INSTALL_DIR="${PYTHON_RUNTIME_DIR}"
export UV_CACHE_DIR
workspace_run uv python install 3.12
(
  cd "${PROJECT_DIR}"
  workspace_run uv sync --frozen --no-dev --python 3.12
)

workspace_stage "安装前端依赖并构建" "检查 npm 软件源、构建报错与磁盘空间；修复原因后使用 --repair-stopped-install 恢复未完成的安装。" E_FRONTEND_BUILD
[[ "$(git -C "${PROJECT_DIR}" cat-file -t "${source_commit}:frontend")" == "tree" ]] || {
  fail "源码提交缺少 frontend 目录，请核对发布包。"
}
frontend_symlinks="$(
  git -C "${PROJECT_DIR}" ls-tree -r "${source_commit}" frontend \
    | awk '$1 == "120000" { print }'
)"
[[ -z "${frontend_symlinks}" ]] || fail "前端源码包含符号链接，已停止构建；请检查发布内容。"
frontend_stage_dir="$(mktemp -d "${PROJECT_DIR}.frontend-install.XXXXXXXX")"
frontend_archive="${frontend_stage_dir}/frontend.tar"
if ! (
  git -C "${PROJECT_DIR}" archive --format=tar \
    --output="${frontend_archive}" "${source_commit}" frontend &&
  tar --no-same-owner --no-same-permissions \
    -xf "${frontend_archive}" -C "${frontend_stage_dir}" &&
  rm -f -- "${frontend_archive}" &&
  test -d "${frontend_stage_dir}/frontend" &&
  test ! -L "${frontend_stage_dir}/frontend" &&
  chown -R "${FRONTEND_USER}:${FRONTEND_GROUP}" "${frontend_stage_dir}" &&
  workspace_run runuser -u "${FRONTEND_USER}" -- env -i \
    HOME="${FRONTEND_HOME}" LANG=C.UTF-8 PATH="${PATH}" \
    npm_config_cache="${NPM_CACHE_DIR}" npm_config_update_notifier=false \
    npm --prefix "${frontend_stage_dir}/frontend" \
      ci --include=dev --prefer-offline --no-audit --no-fund &&
  workspace_run runuser -u "${FRONTEND_USER}" -- env -i \
    HOME="${FRONTEND_HOME}" LANG=C.UTF-8 PATH="${PATH}" \
    npm_config_cache="${NPM_CACHE_DIR}" npm_config_update_notifier=false \
    npm --prefix "${frontend_stage_dir}/frontend" run build &&
  test -d "${frontend_stage_dir}/frontend/node_modules" &&
  test ! -L "${frontend_stage_dir}/frontend/node_modules" &&
  test "$(realpath -- "${frontend_stage_dir}/frontend/node_modules")" = \
    "$(realpath -- "${frontend_stage_dir}/frontend")/node_modules" &&
  test -d "${frontend_stage_dir}/frontend/dist" &&
  test ! -L "${frontend_stage_dir}/frontend/dist" &&
  test "$(realpath -- "${frontend_stage_dir}/frontend/dist")" = \
    "$(realpath -- "${frontend_stage_dir}/frontend")/dist" &&
  test -f "${frontend_stage_dir}/frontend/node_modules/vinext/dist/cli.js" &&
  test ! -L "${frontend_stage_dir}/frontend/node_modules/vinext/dist/cli.js" &&
  test "$(realpath -- "${frontend_stage_dir}/frontend/node_modules/vinext/dist/cli.js")" = \
    "$(realpath -- "${frontend_stage_dir}/frontend")/node_modules/vinext/dist/cli.js" &&
  test -f "${frontend_stage_dir}/frontend/dist/server/index.js" &&
  test ! -L "${frontend_stage_dir}/frontend/dist/server/index.js" &&
  test "$(realpath -- "${frontend_stage_dir}/frontend/dist/server/index.js")" = \
    "$(realpath -- "${frontend_stage_dir}/frontend")/dist/server/index.js" &&
  chown -R root:root "${frontend_stage_dir}" &&
  chmod -R u=rwX,go=rX "${frontend_stage_dir}" &&
  chmod 0700 "${frontend_stage_dir}"
); then
  rm -rf -- "${frontend_stage_dir}"
  fail "前端依赖安装或构建失败，请查看 npm/构建日志。"
fi
rm -rf -- "${PROJECT_DIR}/frontend/node_modules" "${PROJECT_DIR}/frontend/dist"
mv -- "${frontend_stage_dir}/frontend/node_modules" "${PROJECT_DIR}/frontend/node_modules"
mv -- "${frontend_stage_dir}/frontend/dist" "${PROJECT_DIR}/frontend/dist"
rm -rf -- "${frontend_stage_dir}"
chown -R root:root "${PROJECT_DIR}"
chmod -R u=rwX,go=rX "${PROJECT_DIR}"

runuser -u "${BACKEND_USER}" -- test -r "${PROJECT_DIR}/server.py" || {
  fail "后端账号无法读取发布文件，请检查目录和文件权限。"
}
unreadable_backend_file="$(
  runuser -u "${BACKEND_USER}" -- \
    find "${PROJECT_DIR}/app" -type f ! -readable -print -quit
)"
[[ -z "${unreadable_backend_file}" ]] || {
  fail "后端账号无法读取 ${unreadable_backend_file}，请检查发布文件权限。"
}
runuser -u "${FRONTEND_USER}" -- test -r "${PROJECT_DIR}/frontend/package.json" || {
  fail "前端账号无法读取发布文件，请检查目录和文件权限。"
}
runuser -u "${FRONTEND_USER}" -- \
  test -r "${PROJECT_DIR}/frontend/node_modules/vinext/dist/cli.js" || {
  fail "前端账号无法读取 Vinext 运行时，请检查依赖安装和文件权限。"
}
runuser -u "${FRONTEND_USER}" -- \
  test -r "${PROJECT_DIR}/frontend/dist/server/index.js" || {
  fail "前端账号无法读取生产构建，请检查构建结果和文件权限。"
}

workspace_stage "安装 systemd 服务" "检查服务日志和配置，勿重新生成或覆盖迁入的加密密钥。" E_SERVICE
INSTALL_SERVICES_STARTED=true
if ! bash "${PROJECT_DIR}/deploy/systemd/install.sh" \
  "${PROJECT_DIR}" \
  "${BACKEND_USER}" \
  "${FRONTEND_USER}" \
  "$(command -v node)" \
  "${ENV_FILE}" \
  "${DATA_DIR}" \
  "${BACKUP_DIR}" \
  "${FRONTEND_PORT}" \
  "${BACKEND_PORT}"; then
  systemctl stop solution-workspace.target || true
  systemctl stop solution-workspace-backend.service solution-workspace-frontend.service || true
  systemctl stop solution-workspace-backup.timer solution-workspace-backup.service || true
  fail "systemd 安装或启动失败，已尝试停止所有应用服务；请核对当前状态。"
fi

workspace_stage "检查安装后的服务状态" "执行 sudo solution-workspace status 和 logs，确认前后端与自动备份均正常。" E_HEALTH
if ! /usr/local/sbin/solution-workspace health; then
  systemctl stop solution-workspace.target || true
  systemctl stop solution-workspace-backup.timer || true
  systemctl stop solution-workspace-backup.service || true
  fail "安装后健康检查失败，已尝试停服；请检查服务日志。"
fi
systemctl is-active --quiet solution-workspace-backup.timer
systemctl is-enabled --quiet solution-workspace-backup.timer

cat <<EOF

Deployment completed.
  Application: http://${PUBLIC_HOST}:${FRONTEND_PORT}/
  Release:     ${PROJECT_DIR} (${source_commit})
  Runtime env: ${ENV_FILE}
  Database:    ${DATABASE_URL}
  Operations:  sudo solution-workspace help

Create the first administrator interactively:
  sudo solution-workspace create-admin admin "系统管理员"

Read docs/UBUNTU_DEPLOYMENT.md before opening the firewall or switching databases.
EOF
