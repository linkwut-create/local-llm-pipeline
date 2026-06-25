#!/bin/bash
# Serial model audition — stop resident, test each model one at a time
export LOCAL_LLM_BASE_URL="http://193.168.2.2:4000/v1"
export LOCAL_LLM_API_KEY="sk-zero12-cluster"
Z12="ssh zero12"

MODELS=(
  deepseek-r1-32b-distill deepseek-r1-70b
  gemma4-12b gemma4-12b-unsloth gemma4-26b gemma4-26b-a4b-q8 gemma4-26b-unsloth
  gemma4-31b gemma4-31b-opus-latest gemma4-31b-unsloth gemma4-e4b-unsloth
  glm4.7-flash gpt-oss-20b gpt-oss-120b
  legalone-8b minicpm-4.5
  mistral-small-119b-q6 mistral-small-4-119b-q5_k_xl-merged mistral3.5-128b mistral4-24b mistral4-119b
  nemotron-30b nemotron-30b-q8 nemotron-super
  qwen3-coder-30b qwen3-coder-next
  qwen3.5-0.8b qwen3.5-2b qwen3.5-9b qwen3.5-27b qwen3.5-27b-reasoning qwen3.5-35b qwen3.5-122b
  qwen3.6-27b qwen3.6-35b
  translategemma-12b translategemma-27b
)

TOTAL=${#MODELS[@]}; PASS=0; FAIL=0
LOG="evals/model_audition/results/batch_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG")"

echo "=== Model Audition ===" | tee "$LOG"

# Stop resident to free port 8001
echo "Stopping resident..." | tee -a "$LOG"
$Z12 "systemctl --user stop qwen36-llama.service 2>/dev/null" 2>/dev/null
sleep 3

for i in "${!MODELS[@]}"; do
  model="${MODELS[$i]}"
  n=$((i + 1))
  echo "[$n/$TOTAL] $model" | tee -a "$LOG"
  
  # Stop previous service first
  if [ $i -gt 0 ]; then
    prev="${MODELS[$((i-1))]}"
    $Z12 "systemctl --user stop ${prev}-llama.service 2>/dev/null; fuser -k $((8000+i))/tcp 2>/dev/null" 2>/dev/null
    sleep 2
  fi
  
  $Z12 "systemctl --user start ${model}-llama.service 2>/dev/null" 2>/dev/null
  
  # Wait until model responds (no timeout on loading)
  ready=0
  for w in $(seq 1 60); do
    sleep 10
    resp=$(curl -s --max-time 10 -H "Authorization: Bearer sk-zero12-cluster" \
      -H "Content-Type: application/json" \
      -d "{\"model\":\"$model\",\"messages\":[{\"role\":\"user\",\"content\":\"OK\"}],\"max_tokens\":5}" \
      "http://193.168.2.2:4000/v1/chat/completions" 2>/dev/null)
    if echo "$resp" | grep -q '"content"'; then
      echo "  Loaded ${w}x10s" | tee -a "$LOG"; ready=1; break
    fi
  done
  
  if [ $ready -eq 0 ]; then
    echo "  LOAD FAILED" | tee -a "$LOG"; ((FAIL++)); continue
  fi
  
  py -3 tools/model_audition.py --model "$model" --timeout 80 --json-only 2>&1 | tee -a "$LOG"
  rc=${PIPESTATUS[0]}
  if [ $rc -eq 0 ]; then ((PASS++)); echo "  PASS"; else ((FAIL++)); echo "  FAIL"; fi
done

# Restart resident
echo "Restarting resident..." | tee -a "$LOG"
$Z12 "systemctl --user start qwen36-llama.service 2>/dev/null" 2>/dev/null

echo "=== Done: Pass $PASS / Fail $FAIL / $TOTAL ===" | tee -a "$LOG"
