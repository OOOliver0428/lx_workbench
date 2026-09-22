#!/usr/bin/env bash
# Shared by the installers and the installed operations command. Never enable xtrace:
# deployment environment files contain secrets.
WORKSPACE_MAIN_PID="${BASHPID}"
WORKSPACE_STAGE="检查命令和运行环境"
WORKSPACE_STATE="尚未执行服务、代码或数据库变更。"
WORKSPACE_ADVICE="检查上述原因；查看命令的 --help 或部署手册后重试。"
WORKSPACE_ERROR=""
WORKSPACE_CODE="E_COMMAND"
WORKSPACE_LOG=""

workspace_redact() {
  sed -E \
    -e 's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1[REDACTED]@#g' \
    -e 's/(Bearer[[:space:]]+)[A-Za-z0-9._~+\/-]+/\1[REDACTED]/Ig' \
    -e 's/((token|password|secret|api[_-]?key)[=:][[:space:]]*)[^[:space:]]+/\1[REDACTED]/Ig'
}

workspace_init_log() {
  local category="$1" directory=/var/log/solution-workspace
  [[ ! -L "${directory}" ]] || fail "日志目录不能是符号链接：${directory}" E_LOG
  install -d -m 0700 -o root -g root "${directory}"
  WORKSPACE_LOG="$(mktemp "${directory}/${category}-$(date -u +%Y%m%dT%H%M%S)-XXXXXX.log")"
  chmod 0600 "${WORKSPACE_LOG}"
  printf '操作日志：%s\n' "${WORKSPACE_LOG}"
}

workspace_stage() {
  WORKSPACE_STAGE="$1"
  WORKSPACE_ADVICE="$2"
  WORKSPACE_CODE="${3:-E_COMMAND}"
  log "${WORKSPACE_STAGE}"
}

workspace_require_space() {
  local directory="$1" required="$2" available
  available="$(df -PB1 -- "${directory}" | awk 'NR == 2 {print $4}')"
  [[ "${available}" =~ ^[0-9]+$ ]] || fail "无法读取磁盘空间：${directory}" E_DISK
  ((available >= required)) || fail "磁盘空间不足：${directory} 所在分区剩余 $((available / 1048576)) MiB，至少需要 $((required / 1048576)) MiB。请清理无关文件或扩容，勿删除回滚快照。" E_DISK
}

workspace_run() {
  if [[ -n "${WORKSPACE_LOG}" ]]; then
    "$@" 2>&1 | workspace_redact | tee -a "${WORKSPACE_LOG}"
  else
    "$@" 2>&1 | workspace_redact
  fi
}

fail() {
  WORKSPACE_ERROR="$1"
  WORKSPACE_CODE="${2:-${WORKSPACE_CODE}}"
  # Command substitutions have their own EXIT trap and cannot update the parent's
  # diagnostic state. Emit their concrete cause, but never run recovery there.
  if [[ "${BASHPID}" != "${WORKSPACE_MAIN_PID}" ]]; then
    printf '原因：%s\n' "${WORKSPACE_ERROR}" >&2
  fi
  exit 1
}

log() {
  printf '\n==> %s\n' "$*"
  if [[ -n "${WORKSPACE_LOG}" ]]; then
    printf '\n==> %s\n' "$*" >>"${WORKSPACE_LOG}"
  fi
}

workspace_error_details() {
  workspace_redact | {
    if [[ -n "${WORKSPACE_LOG}" ]]; then tee -a "${WORKSPACE_LOG}" >&2; else cat >&2; fi
  }
}

workspace_exit() {
  local status="$1"
  [[ "${BASHPID}" == "${WORKSPACE_MAIN_PID}" ]] || return 0
  trap - EXIT INT TERM
  set +e
  if ((status != 0)); then
    if declare -F workspace_on_failure >/dev/null; then
      workspace_on_failure
    fi
    {
      printf '\n操作未完成 [%s]\n阶段：%s\n原因：%s\n当前状态：%s\n下一步：%s\n' \
        "${WORKSPACE_CODE}" "${WORKSPACE_STAGE}" \
        "${WORKSPACE_ERROR:-本阶段命令执行失败（退出码 ${status}），请查看上方具体报错。}" \
        "${WORKSPACE_STATE}" "${WORKSPACE_ADVICE}"
      [[ -z "${WORKSPACE_LOG}" ]] || printf '详细日志：%s\n' "${WORKSPACE_LOG}"
    } | workspace_error_details
  fi
  if declare -F workspace_cleanup >/dev/null; then
    workspace_cleanup
  fi
  exit "${status}"
}

trap 'workspace_exit $?' EXIT
trap 'WORKSPACE_ERROR="操作被中断（Ctrl+C）；请先确认下面的服务状态。"; WORKSPACE_CODE=E_INTERRUPTED; exit 130' INT
trap 'WORKSPACE_ERROR="操作收到终止信号。"; WORKSPACE_CODE=E_INTERRUPTED; exit 143' TERM
