"""Shared LiteLLM/OpenAI-compatible API utilities."""
import json, os, subprocess, time, urllib.request, urllib.error

def _resolve_base_url():
    url = os.environ.get("LOCAL_LLM_BASE_URL") or os.environ.get("OLLAMA_HOST") or "http://193.168.2.2:4000"
    if not url.startswith("http"): url = "http://" + url
    url = url.rstrip("/")
    if "/v1" not in url: url += "/v1"
    return url

def _build_headers():
    h = {"Content-Type": "application/json"}
    key = os.environ.get("LOCAL_LLM_API_KEY", "")
    if key: h["Authorization"] = "Bearer " + key
    return h

def call_chat_completion(model, messages, max_tokens=400, temperature=0.1, timeout=300):
    start = time.time()
    try:
        url = _resolve_base_url() + "/chat/completions"
        body = json.dumps({"model":model,"messages":messages,"max_tokens":max_tokens,"temperature":temperature,"stream":False}).encode()
        req = urllib.request.Request(url, data=body, headers=_build_headers(), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            r = json.loads(resp.read().decode())
            elapsed = time.time() - start
            content = ""
            if r.get("choices"):
                msg = r["choices"][0].get("message",{})
                content = msg.get("content") or msg.get("reasoning_content") or ""
            return {"ok":True,"response":content,"elapsed_seconds":round(elapsed,1),"error":None,"usage":r.get("usage",{})}
    except Exception as e:
        return {"ok":False,"response":"","elapsed_seconds":round(time.time()-start,1),"error":str(e)[:200],"usage":{}}

def get_openai_models():
    try:
        url = _resolve_base_url().rstrip("/v1") + "/v1/models"
        req = urllib.request.Request(url, headers=_build_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return [m.get("id","") for m in data.get("data",[]) if m.get("id")]
    except Exception:
        return []

def get_ollama_models():
    try:
        r = subprocess.run(["ollama","list"], capture_output=True, text=True, timeout=30)
        lines = r.stdout.strip().split(chr(10))
        return [l.split()[0] for l in lines[1:] if l.strip()]
    except Exception:
        return []

def get_available_models():
    m = get_openai_models()
    return m if m else get_ollama_models()

def warmup_model(model, timeout=600):
    r = call_chat_completion(model, [{"role":"user","content":"Say OK."}], max_tokens=5, timeout=timeout)
    return r["ok"] and bool(r["response"].strip())

def unload_model(model):
    pass  # llama.cpp manages VRAM automatically
