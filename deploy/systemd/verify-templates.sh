#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
temporary_dir="$(mktemp -d)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

project_dir="${temporary_dir}/project"
data_dir="${temporary_dir}/data"
backup_dir="${temporary_dir}/backups"
env_file="${temporary_dir}/app.env"
node_bin="$(command -v node)"
node_bin_dir="$(dirname -- "${node_bin}")"
backend_user="$(id -un)"
backend_group="$(id -gn)"

mkdir -p \
  "${project_dir}/.venv/bin" \
  "${project_dir}/frontend/node_modules/vinext/dist" \
  "${project_dir}/frontend/dist" \
  "${data_dir}" \
  "${backup_dir}"
touch "${env_file}"
touch "${temporary_dir}/ops.lock"
ln -s "$(command -v python3)" "${project_dir}/.venv/bin/python"
ln -s "$(command -v true)" "${project_dir}/.venv/bin/alembic"
touch "${project_dir}/server.py"
touch "${project_dir}/frontend/node_modules/vinext/dist/cli.js"

render() {
  local source_file="$1"
  local destination_file="$2"
  sed \
    -e "s|@@PROJECT_DIR@@|${project_dir}|g" \
    -e "s|@@BACKEND_USER@@|${backend_user}|g" \
    -e "s|@@BACKEND_GROUP@@|${backend_group}|g" \
    -e "s|@@FRONTEND_USER@@|${backend_user}|g" \
    -e "s|@@FRONTEND_GROUP@@|${backend_group}|g" \
    -e "s|@@NODE_BIN@@|${node_bin}|g" \
    -e "s|@@NODE_BIN_DIR@@|${node_bin_dir}|g" \
    -e "s|@@ENV_FILE@@|${env_file}|g" \
    -e "s|@@DATA_DIR@@|${data_dir}|g" \
    -e "s|@@BACKUP_DIR@@|${backup_dir}|g" \
    -e "s|@@LOCK_FILE@@|${temporary_dir}/ops.lock|g" \
    -e 's|@@FRONTEND_PORT@@|5174|g' \
    -e 's|@@BACKEND_PORT@@|8787|g' \
    "${source_file}" >"${destination_file}"
}

render \
  "${SCRIPT_DIR}/solution-workspace-backend.service.in" \
  "${temporary_dir}/solution-workspace-backend.service"
render \
  "${SCRIPT_DIR}/solution-workspace-frontend.service.in" \
  "${temporary_dir}/solution-workspace-frontend.service"
render \
  "${SCRIPT_DIR}/solution-workspace-backup.service.in" \
  "${temporary_dir}/solution-workspace-backup.service"
cp -- "${SCRIPT_DIR}/solution-workspace.target" "${temporary_dir}/solution-workspace.target"
cp -- "${SCRIPT_DIR}/solution-workspace-backup.timer" \
  "${temporary_dir}/solution-workspace-backup.timer"

if grep -R '@@[A-Z_]*@@' "${temporary_dir}"/*.service; then
  printf 'unexpanded systemd template token found\n' >&2
  exit 1
fi

systemd-analyze verify \
  "${temporary_dir}/solution-workspace-backend.service" \
  "${temporary_dir}/solution-workspace-frontend.service" \
  "${temporary_dir}/solution-workspace-backup.service" \
  "${temporary_dir}/solution-workspace-backup.timer" \
  "${temporary_dir}/solution-workspace.target"
