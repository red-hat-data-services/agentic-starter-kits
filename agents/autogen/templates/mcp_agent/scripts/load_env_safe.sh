#!/usr/bin/env bash
# Safe .env loader: parses KEY=VALUE lines only; does not execute the file as shell.
# - Skips blank lines and # comments
# - Optional leading "export "
# - Keys: [A-Za-z_][A-Za-z0-9_]*
# - Rejects lines containing command substitution $(...) or backticks
# - Values: everything after first '='; optional surrounding " or ' stripped
#
# Usage (from repo root mcp_agent):
#   SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck source=scripts/load_env_safe.sh
#   source "$SCRIPT_DIR/scripts/load_env_safe.sh"
#   load_env_safe "$SCRIPT_DIR/.env"

load_env_safe() {
  local env_file="${1:?env file path required}"
  if [[ ! -f "$env_file" ]]; then
    echo "load_env_safe: file not found: $env_file" >&2
    return 1
  fi

  local line key value
  local lineno=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    ((++lineno))
    line="${line%$'\r'}"

    # Trim leading whitespace
    line="${line#"${line%%[![:space:]]*}"}"
    [[ -z "$line" || "$line" == \#* ]] && continue

    if [[ "$line" == export[[:space:]]* ]]; then
      line="${line#export}"
      line="${line#"${line%%[![:space:]]*}"}"
      [[ -z "$line" || "$line" == \#* ]] && continue
    fi

    if [[ "$line" != *=* ]]; then
      echo "load_env_safe: $env_file:$lineno: line has no '=', skipping" >&2
      continue
    fi

    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    key="${key#"${key%%[![:space:]]*}"}"

    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      echo "load_env_safe: $env_file:$lineno: invalid key name, skipping" >&2
      continue
    fi

    # Reject command substitution / backticks (defense in depth; we do not eval .env)
    if [[ "$line" == *'$('* ]] || [[ "$line" == *'`'* ]]; then
      echo "load_env_safe: $env_file:$lineno: command substitution or backticks not allowed, skipping" >&2
      continue
    fi

    # Strip optional surrounding quotes; otherwise trim trailing whitespace on value
    if [[ ${#value} -ge 2 && "${value:0:1}" == '"' && "${value: -1}" == '"' ]]; then
      value="${value:1}"
      value="${value%\"}"
    elif [[ ${#value} -ge 2 && "${value:0:1}" == "'" && "${value: -1}" == "'" ]]; then
      value="${value:1}"
      value="${value%\'}"
    else
      value="${value%"${value##*[![:space:]]}"}"
    fi

    # Safe export: value is shell-quoted, never executed as code
    eval "$(printf "export %s=%q" "$key" "$value")"
  done <"$env_file"
}
