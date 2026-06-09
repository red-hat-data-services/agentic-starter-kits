#!/usr/bin/env bash
#
# vLLM Endpoint Validation
#
# Tests vLLM's OpenAI and Anthropic API endpoints for compatibility
# with Claude Code and general LLM workloads.
#
# Usage:
#   bash test_vllm_endpoints.sh --url <VLLM_URL> --model <MODEL>
#   # or via env vars:
#   export VLLM_URL=https://my-vllm.example.com VLLM_MODEL=openai/gpt-oss-120b
#   bash test_vllm_endpoints.sh
#
# Requirements: bash, curl, jq

set -uo pipefail

# --- Configuration -----------------------------------------------------------

VLLM_URL="${VLLM_URL:-}"
VLLM_MODEL="${VLLM_MODEL:-}"
VLLM_API_KEY="${VLLM_API_KEY:-}"
VLLM_TIMEOUT="${VLLM_TIMEOUT:-60}"
VLLM_INSECURE="${VLLM_INSECURE:-false}"

while [[ $# -gt 0 ]]; do
  case $1 in
    --url)       VLLM_URL="$2";     shift 2 ;;
    --model)     VLLM_MODEL="$2";   shift 2 ;;
    --api-key)   VLLM_API_KEY="$2"; shift 2 ;;
    --timeout)   VLLM_TIMEOUT="$2"; shift 2 ;;
    --insecure)  VLLM_INSECURE="true"; shift ;;
    -h|--help)
      echo "Usage: $0 --url <VLLM_URL> --model <MODEL> [--api-key <KEY>] [--timeout <SECS>] [--insecure]"
      echo ""
      echo "Environment variables: VLLM_URL, VLLM_MODEL, VLLM_API_KEY, VLLM_TIMEOUT, VLLM_INSECURE"
      exit 0 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if [[ -z "$VLLM_URL" || -z "$VLLM_MODEL" ]]; then
  echo "Error: --url and --model are required (or set VLLM_URL and VLLM_MODEL)"
  exit 1
fi

VLLM_URL="${VLLM_URL%/}"

# --- Helpers ------------------------------------------------------------------

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
FAIL=0
SKIP=0

curl_opts=(-s --max-time "$VLLM_TIMEOUT")
if [[ "$VLLM_INSECURE" == "true" ]]; then
  curl_opts+=(-k)
fi
if [[ -n "$VLLM_API_KEY" ]]; then
  curl_opts+=(-H "Authorization: Bearer $VLLM_API_KEY" -H "x-api-key: $VLLM_API_KEY")
fi

pass() { echo -e "  ${GREEN}PASS${NC} $1"; ((PASS++)); }
fail() { echo -e "  ${RED}FAIL${NC} $1"; ((FAIL++)); }
skip() { echo -e "  ${YELLOW}SKIP${NC} $1"; ((SKIP++)); }
header() { echo -e "\n${BOLD}[$1] $2${NC}"; }

# --- Tests --------------------------------------------------------------------

echo "==========================================="
echo " vLLM Endpoint Validation"
echo "==========================================="
echo "URL:     $VLLM_URL"
echo "Model:   $VLLM_MODEL"
echo "Timeout: ${VLLM_TIMEOUT}s"
echo ""

# 1. Health check
header "1/8" "Health Check"
health=$(curl "${curl_opts[@]}" -o /dev/null -w "%{http_code}" "$VLLM_URL/health" 2>/dev/null)
if [[ "$health" == "200" ]]; then
  pass "GET /health returned 200"
else
  fail "GET /health returned $health (expected 200)"
fi

# 2. List models
header "2/8" "List Models"
models_resp=$(curl "${curl_opts[@]}" "$VLLM_URL/v1/models" 2>/dev/null)
if echo "$models_resp" | jq -e ".data[] | select(.id == \"$VLLM_MODEL\")" > /dev/null 2>&1; then
  max_len=$(echo "$models_resp" | jq -r ".data[] | select(.id == \"$VLLM_MODEL\") | .max_model_len")
  pass "Model '$VLLM_MODEL' found (max_model_len: $max_len)"
else
  fail "Model '$VLLM_MODEL' not found in /v1/models response"
fi

# 3. OpenAI chat completion (non-streaming)
header "3/8" "OpenAI Chat Completion (non-streaming)"
oai_resp=$(curl "${curl_opts[@]}" -H "Content-Type: application/json" \
  "$VLLM_URL/v1/chat/completions" \
  -d "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"messages\":[{\"role\":\"user\",\"content\":\"What is 2+2? Reply with just the number.\"}]}" 2>/dev/null)

if echo "$oai_resp" | jq -e '.choices[0].message.content' > /dev/null 2>&1; then
  content=$(echo "$oai_resp" | jq -r '.choices[0].message.content')
  usage=$(echo "$oai_resp" | jq -r '.usage | "prompt=\(.prompt_tokens) completion=\(.completion_tokens)"')
  pass "Got response: \"$content\" ($usage)"
else
  fail "Invalid response: $(echo "$oai_resp" | head -c 200)"
fi

# 4. OpenAI chat completion (streaming)
header "4/8" "OpenAI Chat Completion (streaming)"
oai_stream=$(curl "${curl_opts[@]}" -H "Content-Type: application/json" \
  "$VLLM_URL/v1/chat/completions" \
  -d "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Say hello.\"}]}" 2>/dev/null)

if echo "$oai_stream" | grep -q "data: \[DONE\]"; then
  chunk_count=$(echo "$oai_stream" | grep -c "^data: {" || true)
  pass "Streaming complete ($chunk_count chunks, [DONE] received)"
else
  fail "Streaming incomplete — missing [DONE] sentinel"
fi

# 5. Anthropic messages (non-streaming)
header "5/8" "Anthropic Messages API (non-streaming)"
ant_resp=$(curl "${curl_opts[@]}" -H "Content-Type: application/json" \
  "$VLLM_URL/v1/messages" \
  -d "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"messages\":[{\"role\":\"user\",\"content\":\"What is 2+2? Reply with just the number.\"}]}" 2>/dev/null)

if echo "$ant_resp" | jq -e '.type == "message" and .content[0].type == "text"' > /dev/null 2>&1; then
  content=$(echo "$ant_resp" | jq -r '.content[0].text')
  stop=$(echo "$ant_resp" | jq -r '.stop_reason')
  pass "Got response: \"$content\" (stop_reason: $stop)"
else
  fail "Invalid Anthropic response: $(echo "$ant_resp" | head -c 200)"
fi

# 6. Anthropic messages (streaming)
header "6/8" "Anthropic Messages API (streaming)"
ant_stream=$(curl "${curl_opts[@]}" -H "Content-Type: application/json" \
  "$VLLM_URL/v1/messages" \
  -d "{\"model\":\"$VLLM_MODEL\",\"max_tokens\":50,\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"Say hello.\"}]}" 2>/dev/null)

expected_events=("message_start" "content_block_start" "content_block_delta" "content_block_stop" "message_delta" "message_stop")
missing_events=()
for event in "${expected_events[@]}"; do
  if ! echo "$ant_stream" | grep -q "\"type\":\"$event\""; then
    missing_events+=("$event")
  fi
done

if [[ ${#missing_events[@]} -eq 0 ]]; then
  pass "All SSE event types present: ${expected_events[*]}"
else
  fail "Missing SSE events: ${missing_events[*]}"
fi

# 7. Multi-turn conversation
header "7/8" "Multi-turn Conversation"
multi_resp=$(curl "${curl_opts[@]}" -H "Content-Type: application/json" \
  "$VLLM_URL/v1/messages" \
  -d "{
    \"model\":\"$VLLM_MODEL\",
    \"max_tokens\":100,
    \"messages\":[
      {\"role\":\"user\",\"content\":\"My name is Alice.\"},
      {\"role\":\"assistant\",\"content\":\"Hello Alice! Nice to meet you.\"},
      {\"role\":\"user\",\"content\":\"What is my name?\"}
    ]
  }" 2>/dev/null)

if echo "$multi_resp" | jq -r '.content[0].text' 2>/dev/null | grep -qi "alice"; then
  content=$(echo "$multi_resp" | jq -r '.content[0].text')
  pass "Context preserved: \"$content\""
else
  content=$(echo "$multi_resp" | jq -r '.content[0].text // empty' 2>/dev/null)
  if [[ -n "$content" ]]; then
    fail "Context lost — response did not mention 'Alice': \"$content\""
  else
    fail "Invalid response: $(echo "$multi_resp" | head -c 200)"
  fi
fi

# 8. Tool use
header "8/8" "Tool Use"
tool_resp=$(curl "${curl_opts[@]}" -H "Content-Type: application/json" \
  "$VLLM_URL/v1/messages" \
  -d "{
    \"model\":\"$VLLM_MODEL\",
    \"max_tokens\":200,
    \"messages\":[
      {\"role\":\"user\",\"content\":\"What is the weather in San Francisco? Use the get_weather tool.\"}
    ],
    \"tools\":[{
      \"name\":\"get_weather\",
      \"description\":\"Get the current weather for a location\",
      \"input_schema\":{
        \"type\":\"object\",
        \"properties\":{
          \"location\":{\"type\":\"string\",\"description\":\"City name\"}
        },
        \"required\":[\"location\"]
      }
    }]
  }" 2>/dev/null)

if echo "$tool_resp" | jq -e '.content[] | select(.type == "tool_use")' > /dev/null 2>&1; then
  tool_name=$(echo "$tool_resp" | jq -r '.content[] | select(.type == "tool_use") | .name')
  tool_input=$(echo "$tool_resp" | jq -c '.content[] | select(.type == "tool_use") | .input')
  pass "Tool call: $tool_name($tool_input)"
elif echo "$tool_resp" | jq -e '.content[0].text' > /dev/null 2>&1; then
  content=$(echo "$tool_resp" | jq -r '.content[0].text' | head -c 100)
  fail "Model responded with text instead of tool_use: \"$content\""
else
  fail "Invalid response: $(echo "$tool_resp" | head -c 200)"
fi

# --- Summary ------------------------------------------------------------------

echo ""
echo "==========================================="
echo " Summary"
echo "==========================================="
echo -e "  ${GREEN}PASS${NC}: $PASS"
echo -e "  ${RED}FAIL${NC}: $FAIL"
[[ $SKIP -gt 0 ]] && echo -e "  ${YELLOW}SKIP${NC}: $SKIP"
echo ""

if [[ $FAIL -eq 0 ]]; then
  echo -e "${GREEN}All tests passed.${NC}"
  exit 0
else
  echo -e "${RED}$FAIL test(s) failed.${NC}"
  exit 1
fi
