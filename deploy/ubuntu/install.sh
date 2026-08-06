#!/usr/bin/env bash
set -Eeuo pipefail
umask 0022
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly DEFAULT_SOURCE_DIR="$(realpath -- "${SCRIPT_DIR}/../..")"
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
  --source-dir PATH        Source mvp checkout (default: repository root)
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

fail() {
  printf 'error: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '\n==> %s\n' "$*"
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

[[ "${EUID}" -eq 0 ]] || fail "run this installer with sudo"
[[ -r /etc/os-release ]] || fail "cannot identify the operating system"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" ]] || fail "this installer supports Ubuntu only"
for bootstrap_command in realpath git systemctl; do
  command -v "${bootstrap_command}" >/dev/null 2>&1 || {
    fail "${bootstrap_command} is required before installation can start"
  }
done

SOURCE_DIR="$(realpath -- "${SOURCE_DIR}")"
PROJECT_DIR="$(realpath --canonicalize-missing -- "${PROJECT_DIR}")"
[[ -d "${SOURCE_DIR}/.git" ]] || fail "source directory is not a Git checkout"
[[ -f "${SOURCE_DIR}/uv.lock" ]] || fail "uv.lock was not found in ${SOURCE_DIR}"
[[ -f "${SOURCE_DIR}/frontend/package-lock.json" ]] || fail "frontend lockfile was not found"
[[ "${SOURCE_DIR}" != *[[:space:]]* ]] || fail "source path must not contain whitespace"
[[ "${PROJECT_DIR}" == /opt/* \
  && "${PROJECT_DIR}" != *[[:space:]]* \
  && "${PROJECT_DIR}" != *"'"* ]] || {
  fail "install directory must be a whitespace-free path below /opt"
}
[[ -n "${PUBLIC_HOST}" ]] || fail "--public-host is required"
[[ "${PUBLIC_HOST}" =~ ^[A-Za-z0-9._:-]+$ ]] || fail "invalid public host: ${PUBLIC_HOST}"
valid_port "${FRONTEND_PORT}" || fail "invalid frontend port: ${FRONTEND_PORT}"
valid_port "${BACKEND_PORT}" || fail "invalid backend port: ${BACKEND_PORT}"
[[ "${FRONTEND_PORT}" != "${BACKEND_PORT}" ]] || fail "frontend and backend ports must differ"

source_branch="$(git -C "${SOURCE_DIR}" branch --show-current)"
[[ "${source_branch}" == "mvp" ]] || fail "source checkout must be on the mvp branch"
source_changes="$(git -C "${SOURCE_DIR}" status --porcelain)"
[[ -z "${source_changes}" ]] || fail "source checkout has uncommitted changes"
if [[ -d "${PROJECT_DIR}/.git" ]]; then
  [[ "${REPAIR_STOPPED_INSTALL}" == "true" ]] || {
    fail "an install checkout already exists; use 'sudo solution-workspace update'"
  }
  for existing_unit in \
    solution-workspace-backend.service \
    solution-workspace-frontend.service \
    solution-workspace-backup.service \
    solution-workspace-backup.timer; do
    systemctl is-active --quiet "${existing_unit}" && {
      fail "repair requires all application and backup units to be stopped: ${existing_unit}"
    }
  done
  if [[ -f "${CONFIG_DIR}/ops.lock" ]]; then
    command -v flock >/dev/null 2>&1 || fail "flock is required to repair an installation"
    exec 9>>"${CONFIG_DIR}/ops.lock"
    flock --wait 300 9 || fail "another deployment or backup operation is still running"
  fi
fi

if [[ -z "${DATABASE_URL}" ]]; then
  DATABASE_URL="sqlite:////var/lib/solution-workspace/trial.db"
fi
[[ "${DATABASE_URL}" == sqlite:////* \
  && "${DATABASE_URL}" != *[[:space:]]* \
  && "${DATABASE_URL}" != *"'"* ]] || {
  fail "database URL must be an absolute SQLite URL without whitespace"
}
database_path="${DATABASE_URL#sqlite:///}"
database_path="$(realpath --canonicalize-missing -- "${database_path}")"
data_root="$(realpath --canonicalize-missing -- "${DATA_DIR}")"
[[ "${database_path}" == "${data_root}/"* && "${database_path}" == *.db ]] || {
  fail "database must be a .db file inside ${DATA_DIR}"
}
DATABASE_URL="sqlite:///${database_path}"

if [[ "${INSTALL_PACKAGES}" == "true" ]]; then
  log "Installing Ubuntu prerequisites"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends \
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
      *) fail "unsupported CPU architecture for Node.js: ${machine_arch}" ;;
    esac
    node_archive="node-v${NODE_VERSION}-linux-${node_arch}.tar.xz"
    temporary_node_dir="$(mktemp -d)"
    trap 'rm -rf -- "${temporary_node_dir:-}" "${temporary_uv_dir:-}"' EXIT
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
      *) fail "unsupported CPU architecture for uv: ${machine_arch}" ;;
    esac
    uv_archive="uv-${uv_target}.tar.gz"
    temporary_uv_dir="$(mktemp -d)"
    trap 'rm -rf -- "${temporary_node_dir:-}" "${temporary_uv_dir:-}"' EXIT
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
  command -v "${required_command}" >/dev/null 2>&1 || fail "${required_command} is required"
done
node_version="$(node --version | sed 's/^v//')"
version_at_least "${node_version}" "${NODE_VERSION}" || {
  fail "Node.js >= ${NODE_VERSION} is required"
}
uv_version="$(uv --version | awk '{print $2}')"
version_at_least "${uv_version}" "0.11.0" || fail "uv >= 0.11.0 is required"

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

log "Materializing a root-owned release checkout"
source_commit="$(git -C "${SOURCE_DIR}" rev-parse HEAD)"
origin_url="$(git -C "${SOURCE_DIR}" remote get-url origin 2>/dev/null || true)"
if [[ "${SOURCE_DIR}" != "${PROJECT_DIR}" ]]; then
  if [[ ! -d "${PROJECT_DIR}/.git" ]]; then
    [[ ! -e "${PROJECT_DIR}" ]] || fail "install directory exists but is not a Git checkout"
    git clone --no-local --branch mvp "${SOURCE_DIR}" "${PROJECT_DIR}"
  else
    deployed_changes="$(git -C "${PROJECT_DIR}" status --porcelain --untracked-files=no)"
    [[ -z "${deployed_changes}" ]] || fail "managed install checkout has tracked changes"
    git -C "${PROJECT_DIR}" fetch --force "${SOURCE_DIR}" refs/heads/mvp:refs/remotes/source/mvp
    git -C "${PROJECT_DIR}" checkout --force -B mvp refs/remotes/source/mvp
  fi
  if [[ -n "${origin_url}" ]]; then
    git -C "${PROJECT_DIR}" remote set-url origin "${origin_url}"
  fi
else
  [[ "${PROJECT_DIR}" == /opt/* ]] || fail "an in-place deployment must already be below /opt"
fi
[[ "$(git -C "${PROJECT_DIR}" rev-parse HEAD)" == "${source_commit}" ]] || {
  fail "deployed checkout does not match source commit"
}
chown -R root:root "${PROJECT_DIR}"
chmod -R u=rwX,go=rX "${PROJECT_DIR}"

log "Installing the locked Python runtime and dependencies"
export UV_PYTHON_INSTALL_DIR="${PYTHON_RUNTIME_DIR}"
export UV_CACHE_DIR
uv python install 3.12
(
  cd "${PROJECT_DIR}"
  uv sync --frozen --no-dev --python 3.12
)

log "Installing and building the locked frontend"
[[ "$(git -C "${PROJECT_DIR}" cat-file -t "${source_commit}:frontend")" == "tree" ]] || {
  fail "source commit does not contain a frontend tree"
}
frontend_symlinks="$(
  git -C "${PROJECT_DIR}" ls-tree -r "${source_commit}" frontend \
    | awk '$1 == "120000" { print }'
)"
[[ -z "${frontend_symlinks}" ]] || fail "frontend must not contain tracked symbolic links"
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
  runuser -u "${FRONTEND_USER}" -- env -i \
    HOME="${FRONTEND_HOME}" LANG=C.UTF-8 PATH="${PATH}" \
    npm_config_cache="${NPM_CACHE_DIR}" npm_config_update_notifier=false \
    npm --prefix "${frontend_stage_dir}/frontend" \
      ci --include=dev --prefer-offline --no-audit --no-fund &&
  runuser -u "${FRONTEND_USER}" -- env -i \
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
  fail "frontend dependency installation or build failed"
fi
rm -rf -- "${PROJECT_DIR}/frontend/node_modules" "${PROJECT_DIR}/frontend/dist"
mv -- "${frontend_stage_dir}/frontend/node_modules" "${PROJECT_DIR}/frontend/node_modules"
mv -- "${frontend_stage_dir}/frontend/dist" "${PROJECT_DIR}/frontend/dist"
rm -rf -- "${frontend_stage_dir}"
chown -R root:root "${PROJECT_DIR}"
chmod -R u=rwX,go=rX "${PROJECT_DIR}"

runuser -u "${BACKEND_USER}" -- test -r "${PROJECT_DIR}/server.py" || {
  fail "backend service account cannot read the installed release"
}
unreadable_backend_file="$(
  runuser -u "${BACKEND_USER}" -- \
    find "${PROJECT_DIR}/app" -type f ! -readable -print -quit
)"
[[ -z "${unreadable_backend_file}" ]] || {
  fail "backend service account cannot read ${unreadable_backend_file}"
}
runuser -u "${FRONTEND_USER}" -- test -r "${PROJECT_DIR}/frontend/package.json" || {
  fail "frontend service account cannot read the installed release"
}
runuser -u "${FRONTEND_USER}" -- \
  test -r "${PROJECT_DIR}/frontend/node_modules/vinext/dist/cli.js" || {
  fail "frontend service account cannot read the Vinext runtime"
}
runuser -u "${FRONTEND_USER}" -- \
  test -r "${PROJECT_DIR}/frontend/dist/server/index.js" || {
  fail "frontend service account cannot read the production build"
}

log "Installing systemd services and the operations command"
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
  fail "systemd installation or startup failed; all application units were stopped"
fi

log "Running post-deployment health checks"
if ! /usr/local/sbin/solution-workspace health; then
  systemctl stop solution-workspace.target || true
  systemctl stop solution-workspace-backup.timer || true
  systemctl stop solution-workspace-backup.service || true
  fail "post-deployment health checks failed; services were stopped"
fi

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
