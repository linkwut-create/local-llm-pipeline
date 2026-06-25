#!/bin/bash
# Model health monitor - check if a model is actually running and responding
export LOCAL_LLM_BASE_URL="http://193.168.2.2:4000/v1"
export LOCAL_LLM_API_KEY="sk-zero12-cluster"

model="${1:-}"
[ -z "$model" ] && { echo "Usage: $0 <model-name>"; exit 1; }

check() {
  local m=$1
  # 1. Is the service running?
  local svc=$(ssh zero12 "systemctl --user is-active ${m}-llama.service 2>/dev/null" 2>/dev/null)
  echo "  service: ${svc:-unknown}"
  
  # 2. Does LiteLLM list it?
  local listed=$(curl -s --max-time 5 -H "Authorization: Bearer sk-zero12-cluster" \
    "http://193.168.2.2:4000/v1/models" 2>/dev/null | grep -c "\"$m\"")
  echo "  in LiteLLM: $([ $listed -gt 0 ] && echo YES || echo NO)"
  
  # 3. Does it respond to inference?
  local resp=$(curl -s --max-time 30 -H "Authorization: Bearer sk-zero12-cluster" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"Say: ALIVE\"}],\"max_tokens\":50}" \
    "http://193.168.2.2:4000/v1/chat/completions" 2>/dev/null)
  if echo "$resp" | grep -q '"content":"'; then
    local content=$(echo "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin)['choices'][0]['message'].get('content','')[:40])" 2>/dev/null)
    echo "  inference: OK -> '$content'"
  elif echo "$resp" | grep -q '"error"'; then
    local err=$(echo "$resp" | python3 -c "import sys,json;print(json.load(sys.stdin)['error'].get('message','')[:60])" 2>/dev/null)
    echo "  inference: ERROR -> $err"
  else
    echo "  inference: NO RESPONSE"
  fi
}

echo "=== $(date) ==="
echo "Model: $model"
check "$model"
