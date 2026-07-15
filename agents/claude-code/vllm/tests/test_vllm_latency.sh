#!/usr/bin/env bash
#
# vLLM Latency Benchmark
#
# Measures latency and throughput for vLLM endpoints across different
# request types: short/long prompts, streaming/non-streaming, tool use.
# Results are saved to a timestamped JSON file for later comparison.
#
# Usage:
#   bash test_vllm_latency.sh --url <VLLM_URL> --model <MODEL>
#   # or via env vars:
#   export VLLM_URL=https://my-vllm.example.com VLLM_MODEL=openai/gpt-oss-120b
#   bash test_vllm_latency.sh
#
# Requirements: bash, curl, jq, bc

set -uo pipefail

# --- Configuration -----------------------------------------------------------

VLLM_URL="${VLLM_URL:-}"
VLLM_MODEL="${VLLM_MODEL:-}"
VLLM_API_KEY="${VLLM_API_KEY:-}"
VLLM_TIMEOUT="${VLLM_TIMEOUT:-120}"
VLLM_RUNS="${VLLM_RUNS:-3}"
VLLM_INSECURE="${VLLM_INSECURE:-false}"
OUTPUT_DIR="${OUTPUT_DIR:-.}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --url)       VLLM_URL="$2";     shift 2 ;;
    --model)     VLLM_MODEL="$2";   shift 2 ;;
    --api-key)   VLLM_API_KEY="$2"; shift 2 ;;
    --timeout)   VLLM_TIMEOUT="$2"; shift 2 ;;
    --runs)      VLLM_RUNS="$2";    shift 2 ;;
    --output)    OUTPUT_DIR="$2";   shift 2 ;;
    --insecure)  VLLM_INSECURE="true"; shift ;;
    -h|--help)
      echo "Usage: $0 --url <VLLM_URL> --model <MODEL> [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --url       vLLM base URL (or VLLM_URL env var)"
      echo "  --model     Model name (or VLLM_MODEL env var)"
      echo "  --api-key   API key if auth enabled (or VLLM_API_KEY)"
      echo "  --timeout   Request timeout in seconds (default: 120)"
      echo "  --runs      Repetitions per test for averaging (default: 3)"
      echo "  --output    Directory for results JSON (default: current dir)"
      echo "  --insecure  Disable TLS certificate verification (or VLLM_INSECURE=true)"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$VLLM_URL" || -z "$VLLM_MODEL" ]]; then
  echo "Error: --url and --model are required (or set VLLM_URL and VLLM_MODEL)"
  exit 1
fi

if ! [[ "$VLLM_RUNS" =~ ^[1-9][0-9]*$ ]]; then
  echo "Error: --runs must be a positive integer"
  exit 1
fi

VLLM_URL="${VLLM_URL%/}"

# --- Helpers ------------------------------------------------------------------

BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

curl_opts=(-s --fail --max-time "$VLLM_TIMEOUT")
if [[ "$VLLM_INSECURE" == "true" ]]; then
  curl_opts+=(-k)
fi
if [[ -n "$VLLM_API_KEY" ]]; then
  curl_opts+=(-H "Authorization: Bearer $VLLM_API_KEY" -H "x-api-key: $VLLM_API_KEY")
fi

RESULTS_JSON="[]"

add_result() {
  local test_name="$1" api="$2" streaming="$3" prompt_tokens="$4" completion_tokens="$5"
  local ttfb="$6" total_time="$7" throughput="$8" unit="$9"
  RESULTS_JSON=$(echo "$RESULTS_JSON" | jq \
    --arg name "$test_name" \
    --arg api "$api" \
    --arg streaming "$streaming" \
    --argjson pt "$prompt_tokens" \
    --argjson ct "$completion_tokens" \
    --argjson ttfb "$ttfb" \
    --argjson total "$total_time" \
    --argjson tps "$throughput" \
    --arg unit "$unit" \
    '. + [{
      test: $name, api: $api, streaming: ($streaming == "true"),
      prompt_tokens: $pt, completion_tokens: $ct,
      ttfb_ms: $ttfb, total_ms: $total, throughput: $tps, throughput_unit: $unit
    }]')
}

header() { echo -e "\n${BOLD}[$1] $2${NC}"; }

# Run a single non-streaming request and extract timing + token counts
run_nonstream() {
  local api="$1" payload="$2"
  local endpoint
  if [[ "$api" == "anthropic" ]]; then
    endpoint="$VLLM_URL/v1/messages"
  else
    endpoint="$VLLM_URL/v1/chat/completions"
  fi

  local start_ns end_ns elapsed_ms
  start_ns=$(date +%s%N 2>/dev/null || python3 -c "import time; print(int(time.time()*1e9))")
  local resp
  if ! resp=$(curl "${curl_opts[@]}" -H "Content-Type: application/json" "$endpoint" -d "$payload" 2>/dev/null); then
    echo "FAIL 0 0 0"
    return
  fi
  end_ns=$(date +%s%N 2>/dev/null || python3 -c "import time; print(int(time.time()*1e9))")
  elapsed_ms=$(( (end_ns - start_ns) / 1000000 ))

  local prompt_tokens completion_tokens
  if [[ "$api" == "anthropic" ]]; then
    if ! echo "$resp" | jq -e '.usage.input_tokens != null and .usage.output_tokens != null' >/dev/null 2>&1; then
      echo "FAIL 0 0 0"
      return
    fi
    prompt_tokens=$(echo "$resp" | jq -r '.usage.input_tokens')
    completion_tokens=$(echo "$resp" | jq -r '.usage.output_tokens')
  else
    if ! echo "$resp" | jq -e '.usage.prompt_tokens != null and .usage.completion_tokens != null' >/dev/null 2>&1; then
      echo "FAIL 0 0 0"
      return
    fi
    prompt_tokens=$(echo "$resp" | jq -r '.usage.prompt_tokens')
    completion_tokens=$(echo "$resp" | jq -r '.usage.completion_tokens')
  fi

  local tps=0
  if [[ "$elapsed_ms" -gt 0 && "$completion_tokens" -gt 0 ]]; then
    tps=$(echo "scale=1; $completion_tokens * 1000 / $elapsed_ms" | bc)
  fi

  echo "$elapsed_ms $prompt_tokens $completion_tokens $tps"
}

# Run a single streaming request and measure TTFB + total time
run_stream() {
  local api="$1" payload="$2"
  local endpoint
  if [[ "$api" == "anthropic" ]]; then
    endpoint="$VLLM_URL/v1/messages"
  else
    endpoint="$VLLM_URL/v1/chat/completions"
  fi

  local tmpfile
  tmpfile=$(mktemp)

  local start_ns first_byte_ns end_ns
  start_ns=$(date +%s%N 2>/dev/null || python3 -c "import time; print(int(time.time()*1e9))")

  curl "${curl_opts[@]}" -H "Content-Type: application/json" "$endpoint" -d "$payload" 2>/dev/null | while IFS= read -r line; do
    if [[ ! -f "${tmpfile}.first" ]]; then
      date +%s%N > "${tmpfile}.first" 2>/dev/null || python3 -c "import time; print(int(time.time()*1e9))" > "${tmpfile}.first"
    fi
    echo "$line" >> "$tmpfile"
  done

  end_ns=$(date +%s%N 2>/dev/null || python3 -c "import time; print(int(time.time()*1e9))")

  local ttfb_ms total_ms
  if [[ -f "${tmpfile}.first" ]]; then
    first_byte_ns=$(cat "${tmpfile}.first")
    ttfb_ms=$(( (first_byte_ns - start_ns) / 1000000 ))
  else
    ttfb_ms=0
  fi
  total_ms=$(( (end_ns - start_ns) / 1000000 ))

  local chunk_count
  chunk_count=$(grep -c "^data: {" "$tmpfile" 2>/dev/null || echo "0")

  local stream_complete="false"
  if [[ "$api" == "anthropic" ]]; then
    grep -q '"type":"message_stop"' "$tmpfile" 2>/dev/null && stream_complete="true"
  else
    grep -q '^data: \[DONE\]' "$tmpfile" 2>/dev/null && stream_complete="true"
  fi

  if [[ "$chunk_count" -eq 0 || "$stream_complete" != "true" ]]; then
    rm -f "$tmpfile" "${tmpfile}.first"
    echo "FAIL 0 0 0"
    return
  fi

  local tps=0
  if [[ "$total_ms" -gt 0 && "$chunk_count" -gt 0 ]]; then
    tps=$(echo "scale=1; $chunk_count * 1000 / $total_ms" | bc)
  fi

  rm -f "$tmpfile" "${tmpfile}.first"
  echo "$ttfb_ms $total_ms $chunk_count $tps"
}

# Run a test N times and print averaged results
bench() {
  local test_name="$1" api="$2" streaming="$3" payload="$4" max_tokens="$5"

  local sum_time=0 sum_ttfb=0 sum_pt=0 sum_ct=0 sum_tps=0 success_count=0

  for ((i=1; i<=VLLM_RUNS; i++)); do
    if [[ "$streaming" == "false" ]]; then
      read -r elapsed pt ct tps <<< "$(run_nonstream "$api" "$payload")"
      if [[ "$elapsed" == "FAIL" ]]; then
        echo -e "  ${DIM}Run $i: FAILED — request error${NC}"
        continue
      fi
      sum_time=$((sum_time + elapsed))
      sum_pt=$((sum_pt + pt))
      sum_ct=$((sum_ct + ct))
      sum_tps=$(echo "$sum_tps + $tps" | bc)
      ((success_count++))
      echo -e "  ${DIM}Run $i: ${elapsed}ms | prompt=$pt completion=$ct | $tps tok/s${NC}"
    else
      read -r ttfb total chunks tps <<< "$(run_stream "$api" "$payload")"
      if [[ "$ttfb" == "FAIL" ]]; then
        echo -e "  ${DIM}Run $i: FAILED — request error${NC}"
        continue
      fi
      sum_ttfb=$((sum_ttfb + ttfb))
      sum_time=$((sum_time + total))
      sum_ct=$((sum_ct + chunks))
      sum_tps=$(echo "$sum_tps + $tps" | bc)
      ((success_count++))
      echo -e "  ${DIM}Run $i: TTFB=${ttfb}ms total=${total}ms | $chunks chunks | $tps chunk/s${NC}"
    fi
  done

  if [[ "$success_count" -eq 0 ]]; then
    echo -e "  ${BOLD}All $VLLM_RUNS runs failed — skipping${NC}"
    return
  fi

  local avg_time avg_ttfb avg_pt avg_ct avg_tps
  avg_time=$((sum_time / success_count))
  avg_ttfb=$((sum_ttfb / success_count))
  avg_pt=$((sum_pt / success_count))
  avg_ct=$((sum_ct / success_count))
  avg_tps=$(echo "scale=1; $sum_tps / $success_count" | bc)

  if [[ "$streaming" == "false" ]]; then
    echo -e "  ${BOLD}Avg: ${avg_time}ms | prompt=$avg_pt completion=$avg_ct | $avg_tps tok/s ($success_count/$VLLM_RUNS runs)${NC}"
    add_result "$test_name" "$api" "false" "$avg_pt" "$avg_ct" "0" "$avg_time" "$avg_tps" "tok/s"
  else
    echo -e "  ${BOLD}Avg: TTFB=${avg_ttfb}ms total=${avg_time}ms | $avg_ct chunks | $avg_tps chunk/s ($success_count/$VLLM_RUNS runs)${NC}"
    add_result "$test_name" "$api" "true" "0" "$avg_ct" "$avg_ttfb" "$avg_time" "$avg_tps" "chunk/s"
  fi
}

# --- Tests --------------------------------------------------------------------

echo "==========================================="
echo " vLLM Latency Benchmark"
echo "==========================================="
echo "URL:     $VLLM_URL"
echo "Model:   $VLLM_MODEL"
echo "Runs:    $VLLM_RUNS per test"
echo "Timeout: ${VLLM_TIMEOUT}s"

SHORT_PROMPT="What is 2+2? Reply with just the number."
LONG_PROMPT="Write a detailed essay about the history of computing, from Charles Babbage's Analytical Engine through Alan Turing's contributions, the invention of the transistor, the development of integrated circuits, the personal computer revolution, and the rise of the internet. Include key dates, people, and technological breakthroughs."

# 1. Short prompt, non-streaming (OpenAI)
header "1/10" "Short prompt — OpenAI non-streaming (max_tokens=50)"
bench "short_openai" "openai" "false" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"messages\":[{\"role\":\"user\",\"content\":\"$SHORT_PROMPT\"}]}" 50

# 2. Short prompt, non-streaming (Anthropic)
header "2/10" "Short prompt — Anthropic non-streaming (max_tokens=50)"
bench "short_anthropic" "anthropic" "false" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"messages\":[{\"role\":\"user\",\"content\":\"$SHORT_PROMPT\"}]}" 50

# 3. Short prompt, streaming (OpenAI)
header "3/10" "Short prompt — OpenAI streaming (max_tokens=50)"
bench "short_openai_stream" "openai" "true" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"$SHORT_PROMPT\"}]}" 50

# 4. Short prompt, streaming (Anthropic)
header "4/10" "Short prompt — Anthropic streaming (max_tokens=50)"
bench "short_anthropic_stream" "anthropic" "true" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"$SHORT_PROMPT\"}]}" 50

# 5. Long prompt, non-streaming (OpenAI)
header "5/10" "Long prompt — OpenAI non-streaming (max_tokens=200)"
bench "long_openai" "openai" "false" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":200,\"messages\":[{\"role\":\"user\",\"content\":\"$LONG_PROMPT\"}]}" 200

# 6. Long prompt, non-streaming (Anthropic)
header "6/10" "Long prompt — Anthropic non-streaming (max_tokens=200)"
bench "long_anthropic" "anthropic" "false" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":200,\"messages\":[{\"role\":\"user\",\"content\":\"$LONG_PROMPT\"}]}" 200

# 7. Long prompt, streaming (OpenAI)
header "7/10" "Long prompt — OpenAI streaming (max_tokens=200)"
bench "long_openai_stream" "openai" "true" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":200,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"$LONG_PROMPT\"}]}" 200

# 8. Long prompt, streaming (Anthropic)
header "8/10" "Long prompt — Anthropic streaming (max_tokens=200)"
bench "long_anthropic_stream" "anthropic" "true" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":200,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"$LONG_PROMPT\"}]}" 200

# 9. Multi-turn (Anthropic)
header "9/10" "Multi-turn (3 messages) — Anthropic non-streaming (max_tokens=100)"
bench "multiturn_anthropic" "anthropic" "false" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":100,\"messages\":[{\"role\":\"user\",\"content\":\"My name is Alice and I work at Acme Corp.\"},{\"role\":\"assistant\",\"content\":\"Hello Alice! Nice to meet you. How can I help you today?\"},{\"role\":\"user\",\"content\":\"What is my name and where do I work?\"}]}" 100

# 10. Tool use (Anthropic)
header "10/10" "Tool use — Anthropic non-streaming (max_tokens=200)"
bench "tooluse_anthropic" "anthropic" "false" \
  "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":200,\"messages\":[{\"role\":\"user\",\"content\":\"What is the weather in San Francisco?\"}],\"tools\":[{\"name\":\"get_weather\",\"description\":\"Get weather for a location\",\"input_schema\":{\"type\":\"object\",\"properties\":{\"location\":{\"type\":\"string\"}},\"required\":[\"location\"]}}]}" 200

# --- Summary ------------------------------------------------------------------

echo ""
echo "==========================================="
echo " Summary"
echo "==========================================="
echo ""
printf "  ${BOLD}%-30s %8s %8s %8s %10s${NC}\n" "Test" "TTFB" "Total" "Tokens" "Throughput"
printf "  %-30s %8s %8s %8s %10s\n" "------------------------------" "--------" "--------" "--------" "----------"

echo "$RESULTS_JSON" | jq -r '.[] | [.test, .ttfb_ms, .total_ms, .completion_tokens, .throughput, .throughput_unit] | @tsv' | \
while IFS=$'\t' read -r name ttfb total tokens tps unit; do
  if [[ "$ttfb" == "0" ]]; then
    ttfb_str="—"
  else
    ttfb_str="${ttfb}ms"
  fi
  printf "  %-30s %8s %7sms %8s %8s %s\n" "$name" "$ttfb_str" "$total" "$tokens" "$tps" "$unit"
done

# --- Save results -------------------------------------------------------------

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RESULTS_FILE="$OUTPUT_DIR/vllm-latency-${TIMESTAMP}.json"

jq -n \
  --arg url "$VLLM_URL" \
  --arg model "$VLLM_MODEL" \
  --arg ts "$TIMESTAMP" \
  --argjson runs "$VLLM_RUNS" \
  --argjson results "$RESULTS_JSON" \
  '{
    timestamp: $ts,
    url: $url,
    model: $model,
    runs_per_test: $runs,
    results: $results
  }' > "$RESULTS_FILE"

echo ""
echo "Results saved to: $RESULTS_FILE"
echo ""
