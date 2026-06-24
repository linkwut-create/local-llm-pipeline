"""Model Launcher — on-demand llama.cpp model lifecycle.

Maps LiteLLM model names → systemd services. Starts models before use,
waits for readiness, stops them after use to free unified memory.

Resident models (8001, 8003) are never stopped.
"""

from __future__ import annotations
import subprocess, urllib.request, time, os, json
from pathlib import Path

# Which models are resident (always on, never stop)
_RESIDENT_MODELS = {"qwen3.6-deep", "qwen3.6-default", "qwen3-coder-30b"}

# LiteLLM model name → (systemd service name, port)
# Auto-discovered from systemd service files
_MODEL_REGISTRY: dict[str, tuple[str, int]] = {}

def _discover_services():
    """Scan systemd user services to build model→service→port map."""
    global _MODEL_REGISTRY
    if _MODEL_REGISTRY:
        return
    svc_dir = os.path.expanduser("~/.config/systemd/user")
    if not os.path.isdir(svc_dir):
        return
    import re
    for f in os.listdir(svc_dir):
        if not f.endswith('.service'):
            continue
        svc_path = os.path.join(svc_dir, f)
        try:
            with open(svc_path) as fh:
                content = fh.read()
        except Exception:
            continue
        port_m = re.search(r'--port (\d+)', content)
        if not port_m:
            continue
        port = int(port_m.group(1))
        service = f.replace('.service', '')
        # Use LiteLLM model_name format (same as in litellm_config.yaml)
        # Read from manifest to get the canonical LiteLLM name
        name = _resolve_litellm_name(service, port)
        _MODEL_REGISTRY[name] = (service, port)

def _resolve_litellm_name(service: str, port: int) -> str:
    """Resolve service→LiteLLM model name."""
    # Try reading LiteLLM config
    config_paths = [
        "/home/zero12/ai_cluster/litellm_config.yaml",
        os.path.expanduser("~/ai_cluster/litellm_config.yaml"),
    ]
    import re as _re
    for cp in config_paths:
        try:
            with open(cp) as fh:
                content = fh.read()
            # Find model_name for this port
            pattern = f'api_base: http://127.0.0.1:{port}/v1'
            if pattern in content:
                # Get the model_name from the next line
                m = _re.search(
                    f'{pattern}.*?\n.*?model_name: (\\S+)',
                    content, _re.DOTALL
                )
                if m:
                    return m.group(1)
        except Exception:
            pass
    return f"model-{port}"

def _service_name_for_model(model: str) -> tuple[str | None, int | None]:
    """Get (systemd_service_name, port) for a LiteLLM model name."""
    _discover_services()
    # Direct match
    if model in _MODEL_REGISTRY:
        return _MODEL_REGISTRY[model]
    # Try fuzzy match (model name may differ from service name)
    for name, (svc, port) in _MODEL_REGISTRY.items():
        if model in name or name in model:
            return (svc, port)
    return (None, None)

def ensure_running(model: str, max_wait: int = 180) -> bool:
    """Ensure a model's llama.cpp backend is running. Start if needed.
    
    Returns True if the model is ready to use.
    Resident models are assumed always running.
    """
    if model in _RESIDENT_MODELS:
        return True  # Always on, don't touch
    
    service, port = _service_name_for_model(model)
    if not service or not port:
        return False  # No service mapped, maybe an external/Ollama model
    
    _discover_services()
    
    # Check if already responding
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/v1/models", timeout=3)
        return True
    except Exception:
        pass
    
    # Start the service
    try:
        subprocess.run(
            ["systemctl", "--user", "start", service],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        return False
    
    # Wait for it to be ready
    deadline = time.monotonic() + max_wait
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/v1/models", timeout=5
            )
            return True
        except Exception:
            time.sleep(3)
    
    return False

def stop_if_on_demand(model: str):
    """Stop a model if it's not resident, freeing memory."""
    if model in _RESIDENT_MODELS:
        return  # Never stop resident models
    
    service, port = _service_name_for_model(model)
    if not service:
        return
    
    try:
        subprocess.run(
            ["systemctl", "--user", "stop", service],
            capture_output=True, text=True, timeout=15,
        )
    except Exception:
        pass

def stop_all_on_demand():
    """Stop all non-resident models."""
    _discover_services()
    for name, (service, port) in _MODEL_REGISTRY.items():
        if name in _RESIDENT_MODELS:
            continue
        try:
            # Check if running
            r = subprocess.run(
                ["systemctl", "--user", "is-active", service],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0:
                subprocess.run(
                    ["systemctl", "--user", "stop", service],
                    capture_output=True, text=True, timeout=15,
                )
        except Exception:
            pass

def list_running() -> list[str]:
    """Return list of currently running model names."""
    _discover_services()
    running = []
    for name, (service, port) in _MODEL_REGISTRY.items():
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/v1/models", timeout=2
            )
            running.append(f"{name} (:{port})")
        except Exception:
            pass
    return running

# On import, discover services
_discover_services()
