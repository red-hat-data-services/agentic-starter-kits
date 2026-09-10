#!/usr/bin/env bash
# Build the quality-gates-pipeline Slack summary: a gate-level status block
# (QG1/QG2/QG4/QG7) plus a per-agent QG4/QG7 matrix. Prints Slack mrkdwn to
# stdout.
#
# Never lets a malformed outcome artifact abort the whole summary: the gate
# summary always renders, and the agent table degrades to a placeholder
# rather than crashing the script (a crash here would otherwise silence the
# entire Slack alert — see the caller in quality-gates-pipeline.yml).

set -euo pipefail

command -v jq >/dev/null 2>&1 || {
  echo "jq is required to build the QG summary" >&2
  exit 1
}

QG1_RESULT="${QG1_RESULT:?QG1_RESULT is required}"
QG2_RESULT="${QG2_RESULT:?QG2_RESULT is required}"
QG4_RESULT="${QG4_RESULT:?QG4_RESULT is required}"
QG7_RESULT="${QG7_RESULT:?QG7_RESULT is required}"
QG4_OUTCOMES_DIR="${QG4_OUTCOMES_DIR:-qg4-outcomes}"
QG7_OUTCOMES_DIR="${QG7_OUTCOMES_DIR:-qg7-outcomes}"
# Slack section blocks cap text at 3000 characters; this is the budget for
# the *entire* summary_text (gate summary + agent table together), since
# both land in one section block. Row count alone can't bound this — agent
# name length varies — so the table is truncated by character budget, not a
# fixed row count.
TOTAL_CHAR_BUDGET="${TOTAL_CHAR_BUDGET:-2900}"

# Agents that pass QG4 but are intentionally excluded from QG7 behavioral
# evals. Set via the QG7_EXCLUDED_AGENTS_JSON workflow-level env var in
# quality-gates-pipeline.yml — the single source of truth shared with the
# collect-qg4 job. The literal default below only matters for standalone/test
# runs where that env var isn't set.
QG7_EXCLUDED_AGENTS_JSON="${QG7_EXCLUDED_AGENTS_JSON:-[\"langgraph/examples/guardrailed_agent\", \"langgraph/templates/agentic_rag\"]}"
if QG7_EXCLUDED="$(jq -ce 'if type == "array" then . else error("not an array") end' <<<"${QG7_EXCLUDED_AGENTS_JSON}" 2>/dev/null)"; then
  :
else
  echo "::warning::QG7_EXCLUDED_AGENTS_JSON is not a valid JSON array; treating QG7 exclusion list as empty" >&2
  QG7_EXCLUDED='[]'
fi

# Icon for a gate-level (QG1/QG2/QG4/QG7) needs.*.result value.
gate_status_icon() {
  case "$1" in
    success) echo "✅" ;;
    skipped) echo "⏭️" ;;
    cancelled | timed_out) echo "⏱️" ;;
    # failure, or anything unrecognized — treat as a hard failure.
    *) echo "❌" ;;
  esac
}

gate_line() {
  local label="$1" result="$2" note="${3:-}"
  local icon
  icon="$(gate_status_icon "${result}")"
  if [[ -n "${note}" ]]; then
    echo "${icon} ${label}: ${result} (${note})"
  else
    echo "${icon} ${label}: ${result}"
  fi
}

qg2_note=""
[[ "${QG2_RESULT}" == "skipped" ]] && qg2_note="blocked by QG1"
qg4_note=""
[[ "${QG4_RESULT}" == "skipped" ]] && qg4_note="blocked by QG1/QG2"
qg7_note=""
[[ "${QG7_RESULT}" == "skipped" ]] && qg7_note="no agents eligible"

gate_summary="$(
  {
    echo "*Gate Summary*"
    gate_line "QG1 — Cluster Readiness" "${QG1_RESULT}"
    gate_line "QG2 — Platform Readiness" "${QG2_RESULT}" "${qg2_note}"
    gate_line "QG4 — Deployment Health" "${QG4_RESULT}" "${qg4_note}"
    gate_line "QG7 — Behavioral Evals" "${QG7_RESULT}" "${qg7_note}"
  }
)"

# Icon for a per-agent qg4/qg7 cell value (see the "qg7:" derivation below
# for the full set of possible values — includes synthetic ones like
# "blocked_fail" alongside real job.status values).
agent_status_icon() {
  case "$1" in
    success) echo "✅" ;;
    failure) echo "❌" ;;
    cancelled | timed_out) echo "⏱️" ;;
    # blocked_fail, blocked_skip, excluded, not_run, skipped — none of these
    # mean QG7 ran and failed, so render as "didn't run" rather than a red X.
    *) echo "⏭️" ;;
  esac
}

agent_status_note() {
  case "$1" in
    blocked_fail) echo "blocked: failed QG4" ;;
    blocked_skip) echo "QG4 skipped" ;;
    excluded) echo "excluded from QG7" ;;
    not_run) echo "QG7 did not run" ;;
    cancelled) echo "cancelled" ;;
    timed_out) echo "timed out" ;;
    *) echo "" ;;
  esac
}

# Filters the given files down to valid JSON ones. Sets the globals
# FILTER_VALID_FILES (array) and FILTER_INVALID_COUNT — deliberately not
# `local -n` namerefs (bash 4.3+ only) since this needs to run under bash
# 3.2 (macOS's default /bin/bash). Must be called directly, not inside a
# `$(...)`/`<(...)` subshell, or these global assignments won't be visible
# to the caller. A single truncated/corrupt outcome artifact should not
# take down the whole summary.
filter_valid_json() {
  FILTER_VALID_FILES=()
  FILTER_INVALID_COUNT=0
  local f
  for f in "$@"; do
    if jq empty "${f}" >/dev/null 2>&1; then
      FILTER_VALID_FILES+=("${f}")
    else
      FILTER_INVALID_COUNT=$((FILTER_INVALID_COUNT + 1))
      echo "::warning::Skipping unparseable outcome file: ${f}" >&2
    fi
  done
}

# Builds the "*Agent Results*" code-fenced table from a pre-validated QG4
# file list and pre-computed QG7 status map. Isolated in a function so a
# caller can catch a failure here (e.g. an unexpected jq error) and fall
# back to a placeholder instead of letting the whole script — and the Slack
# alert with it — die. File validation happens in the caller (not here)
# because this function is invoked inside a `$(...)` subshell, so any
# variables it sets wouldn't be visible back in the caller's scope.
build_agent_table() {
  local qg7_json="$1" char_budget="$2"
  shift 2
  local -a qg4_files=("$@")

  local rows
  rows="$(
    jq -s --argjson excluded "${QG7_EXCLUDED}" --argjson qg7 "${qg7_json}" '
      map(
        . as $a
        | ($a.dir | ltrimstr("agents/")) as $qg7_id
        | ($qg7_id | IN($excluded[])) as $is_excluded
        | {
            name: $a.name,
            qg4: $a.status,
            qg7: (
              if $a.status == "skipped" then "blocked_skip"
              elif $a.status != "success" then "blocked_fail"
              elif $is_excluded then "excluded"
              elif ($qg7 | has($a.name)) then $qg7[$a.name]
              else "not_run"
              end
            )
          }
      )
      | sort_by(.name)
    ' "${qg4_files[@]}"
  )"

  local total_count
  total_count="$(jq 'length' <<<"${rows}")"

  local header
  header="$(printf '%-34s %-4s %-4s' "agent" "qg4" "qg7")"
  # Fixed overhead around the table: "*Agent Results*\n```\n" + header line +
  # "\n" + closing "```", plus a little slack for the header line itself.
  local chrome_len=$(( ${#header} + 32 ))

  local -a row_lines=()
  while IFS=$'\t' read -r name qg4_status qg7_status; do
    qg4_sym="$(agent_status_icon "${qg4_status}")"
    qg7_sym="$(agent_status_icon "${qg7_status}")"
    note="$(agent_status_note "${qg7_status}")"
    row_lines+=("$(printf '%-34s %-2s   %-2s   %s' "${name}" "${qg4_sym}" "${qg7_sym}" "${note}")")
  done < <(jq -r '.[] | [.name, .qg4, .qg7] | @tsv' <<<"${rows}")

  # Reserve room for the truncation trailer up front so it's never the thing
  # that pushes the block over budget.
  local trailer_reserve=70
  local shown=0
  local running_len=${chrome_len}
  local -a included=()
  local line line_len
  for line in "${row_lines[@]+"${row_lines[@]}"}"; do
    line_len=$(( ${#line} + 1 ))
    if (( running_len + line_len + trailer_reserve > char_budget )); then
      break
    fi
    included+=("${line}")
    running_len=$(( running_len + line_len ))
    shown=$(( shown + 1 ))
  done

  local table_body=""
  if [[ ${#included[@]} -gt 0 ]]; then
    table_body="$(printf '%s\n' "${included[@]}")"
  fi
  if (( shown < total_count )); then
    table_body="${table_body}
... and $((total_count - shown)) more agent(s), see workflow run for the full matrix"
  fi

  # shellcheck disable=SC2016 # backticks here are a literal Slack code-fence, not command substitution
  printf '*Agent Results*\n```\n%s\n%s\n```' "${header}" "${table_body}"
}

shopt -s nullglob
all_qg4_files=("${QG4_OUTCOMES_DIR}"/qg4-outcome-*/result.json)
all_qg7_files=("${QG7_OUTCOMES_DIR}"/qg7-outcome-*/result.json)

valid_qg4_files=()
invalid_qg4_count=0
if [[ ${#all_qg4_files[@]} -gt 0 ]]; then
  filter_valid_json "${all_qg4_files[@]}"
  valid_qg4_files=("${FILTER_VALID_FILES[@]+"${FILTER_VALID_FILES[@]}"}")
  invalid_qg4_count="${FILTER_INVALID_COUNT}"
fi

valid_qg7_files=()
invalid_qg7_count=0
if [[ ${#all_qg7_files[@]} -gt 0 ]]; then
  filter_valid_json "${all_qg7_files[@]}"
  valid_qg7_files=("${FILTER_VALID_FILES[@]+"${FILTER_VALID_FILES[@]}"}")
  invalid_qg7_count="${FILTER_INVALID_COUNT}"
fi

qg7_json='{}'
if [[ ${#valid_qg7_files[@]} -gt 0 ]]; then
  qg7_json="$(jq -s '[.[] | {(.name): .status}] | add // {}' "${valid_qg7_files[@]}" 2>/dev/null)" || qg7_json='{}'
fi

warnings=()
[[ "${invalid_qg4_count}" -gt 0 ]] && warnings+=("⚠️ ${invalid_qg4_count} QG4 outcome file(s) could not be parsed and were excluded")
[[ "${invalid_qg7_count}" -gt 0 ]] && warnings+=("⚠️ ${invalid_qg7_count} QG7 outcome file(s) could not be parsed and were excluded")
warnings_text=""
for warning in "${warnings[@]+"${warnings[@]}"}"; do
  warnings_text="${warnings_text}
${warning}"
done

agent_table=""
if [[ ${#all_qg4_files[@]} -gt 0 ]]; then
  if [[ ${#valid_qg4_files[@]} -gt 0 ]]; then
    # Budget the agent table against what's left after the gate summary and
    # any warning lines, since all of it lands in one Slack section block.
    remaining_budget=$(( TOTAL_CHAR_BUDGET - ${#gate_summary} - ${#warnings_text} - 4 ))
    [[ "${remaining_budget}" -lt 200 ]] && remaining_budget=200
    if ! agent_table="$(build_agent_table "${qg7_json}" "${remaining_budget}" "${valid_qg4_files[@]}")"; then
      agent_table=$'*Agent Results*\n_agent-level summary unavailable (unexpected error building the table) — see workflow run for details_'
    fi
  else
    agent_table=$'*Agent Results*\n_agent-level summary unavailable (no readable outcome data) — see workflow run for details_'
  fi
  agent_table="${agent_table}${warnings_text}"
fi

if [[ -n "${agent_table}" ]]; then
  printf '%s\n\n%s\n' "${gate_summary}" "${agent_table}"
else
  printf '%s\n' "${gate_summary}"
fi
