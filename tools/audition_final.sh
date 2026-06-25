#!/bin/bash
set -o pipefail
export LOCAL_LLM_BASE_URL="http://193.168.2.2:4000/v1" LOCAL_LLM_API_KEY="sk-zero12-cluster"

MODELS=(deepseek-r1-32b-distill deepseek-r1-70b gemma4-12b gemma4-12b-unsloth gemma4-26b gemma4-26b-a4b-q8 gemma4-26b-unsloth gemma4-31b gemma4-31b-opus-latest gemma4-31b-unsloth gemma4-e4b-unsloth glm4.7-flash gpt-oss-20b gpt-oss-120b legalone-8b minicpm-4.5 mistral-small-119b-q6 mistral-small-4-119b-q5_k_xl-merged mistral3.5-128b mistral4-24b mistral4-119b nemotron-30b nemotron-30b-q8 nemotron-super qwen3-coder-30b qwen3-coder-next qwen3.5-0.8b qwen3.5-2b qwen3.5-9b qwen3.5-27b qwen3.5-27b-reasoning qwen3.5-35b qwen3.5-122b qwen3.6-27b qwen3.6-35b translategemma-12b translategemma-27b)

PASS=0; FAIL=0
prev=""
for i in "${!MODELS[@]}"; do
  m="${MODELS[$i]}"; n=$((i+1))
  
  # ALWAYS stop previous model, free its port
  if [ -n "$prev" ]; then
    ssh zero12 "systemctl --user stop ${prev}-llama.service 2>/dev/null; fuser -k \$((8000+i))/tcp 2>/dev/null" 2>/dev/null
    sleep 10
  fi
  prev="$m"
  
  echo "=== [$n/37] $m ==="
  ssh zero12 "systemctl --user start ${m}-llama.service" 2>/dev/null
  
  for w in $(seq 1 60); do
    sleep 10
    r=$(curl -s --max-time 10 -H "Authorization: Bearer sk-zero12-cluster" -H "Content-Type: application/json" \
      -d "{\"model\":\"$m\",\"messages\":[{\"role\":\"user\",\"content\":\"OK\"}],\"max_tokens\":5}" \
      "http://193.168.2.2:4000/v1/chat/completions" 2>/dev/null)
    if echo "$r" | grep -q '"content"'; then echo "  Ready ${w}x10s"; break; fi
  done
  
  py -3 tools/model_audition.py --model "$m" --timeout 120 2>&1 | tail -3
  rc=$?
  [ $rc -ne 0 ] && { echo "  Retry 180s..."; py -3 tools/model_audition.py --model "$m" --timeout 180 2>&1 | tail -3; rc=$?; }
  [ $rc -eq 0 ] && ((PASS++)) && echo "  PASS" || { ((FAIL++)); echo "  FAIL"; }
  echo "  [$PASS pass, $FAIL fail]"
done

# Stop last model
ssh zero12 "systemctl --user stop ${MODELS[-1]}-llama.service 2>/dev/null" 2>/dev/null
echo "=== Done: $PASS PASS / $FAIL FAIL ==="
