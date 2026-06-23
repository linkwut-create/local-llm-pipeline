"""Verify LiteLLM tunnel from Windows → llama.cpp."""
import urllib.request, json, time

print("Testing LiteLLM via SSH tunnel (127.0.0.1:4400)...")

# Test models list
try:
    req = urllib.request.Request("http://127.0.0.1:4400/v1/models",
        headers={"Authorization": "Bearer sk-zero12-cluster"})
    data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    models = [m.get("id","?") for m in data.get("data",[])]
    print(f"Models accessible: {len(models)}")
    for m in models[:8]: print(f"  - {m}")
except Exception as e:
    print(f"ERROR /models: {e}")

# Test inference
print("\nInference test (qwen3-coder-30b)...")
try:
    t0 = time.time()
    payload = json.dumps({"model":"qwen3-coder-30b","messages":[{"role":"user","content":"Say hi"}],"max_tokens":30,"temperature":0})
    req = urllib.request.Request("http://127.0.0.1:4400/v1/chat/completions",
        data=payload.encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer sk-zero12-cluster"})
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    content = resp["choices"][0]["message"]["content"]
    elapsed = round(time.time() - t0, 1)
    print(f"Response ({elapsed}s): {content}")
    print("\nLiteLLM → llama.cpp pipeline: WORKING")
except Exception as e:
    print(f"ERROR inference: {e}")
