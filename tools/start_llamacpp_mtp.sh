#!/bin/bash
# Start llama.cpp servers with MTP speculative decoding on zero12.
# Run on zero12 (193.168.2.2) — NOT on the laptop.
#
# Usage:
#   chmod +x start_llamacpp_mtp.sh
#   ./start_llamacpp_mtp.sh              # start all 3 servers
#   ./start_llamacpp_mtp.sh --stop       # kill all llama-server processes
#   ./start_llamacpp_mtp.sh --status     # check if servers are running
#
# Port layout:
#   8080 — Gemma 4 26B (MTP via assistant drafter GGUF)
#   8082 — Qwen3.6 27B (native MTP heads, no drafter needed)
#   8083 — Qwen3.6 35B MoE (native MTP heads, no drafter needed)
#
# Prerequisites:
#   - llama.cpp built with HIP/ROCm support (make GGML_HIPBLAS=1)
#   - GGUF model files in ~/models/
#   - AMD GPU with ROCm installed

set -euo pipefail

MODEL_DIR="${MODEL_DIR:-$HOME/models}"
LLAMA_SERVER="${LLAMA_SERVER:-llama-server}"
NGL="${NGL:-99}"  # GPU layers

# Model paths — adjust to match your GGUF files
GEMMA4_MODEL="${GEMMA4_MODEL:-$MODEL_DIR/gemma-4-26B-A4B-it-Q8_0.gguf}"
GEMMA4_DRAFTER="${GEMMA4_DRAFTER:-$MODEL_DIR/gemma-4-26B-A4B-it-assistant-F16.gguf}"
QWEN27_MODEL="${QWEN27_MODEL:-$MODEL_DIR/qwen3.6-27b-q8_k_xl.gguf}"
QWEN35_MODEL="${QWEN35_MODEL:-$MODEL_DIR/qwen3.6-35b-moe-q8_k_xl.gguf}"

declare -A SERVERS=(
    [8080]="Gemma4-26B-MTP"
    [8082]="Qwen3.6-27B-MTP"
    [8083]="Qwen3.6-35B-MoE-MTP"
)

status() {
    echo "=== llama.cpp MTP Server Status ==="
    for port in 8080 8082 8083; do
        if pgrep -f "llama-server.*--port $port" > /dev/null 2>&1; then
            pid=$(pgrep -f "llama-server.*--port $port")
            echo "  [ON]  port $port (${SERVERS[$port]}) — PID $pid"
        elif curl -s -m 2 "http://localhost:$port/v1/models" > /dev/null 2>&1; then
            echo "  [ON]  port $port (${SERVERS[$port]}) — responding but PID unknown"
        else
            echo "  [OFF] port $port (${SERVERS[$port]})"
        fi
    done
}

stop_servers() {
    echo "Stopping all llama-server processes..."
    for port in 8080 8082 8083; do
        if pgrep -f "llama-server.*--port $port" > /dev/null 2>&1; then
            pkill -f "llama-server.*--port $port" && echo "  Stopped port $port"
        fi
    done
    echo "Done."
}

start_servers() {
    # Gemma 4 26B MTP (port 8080) — uses assistant GGUF as MTP drafter
    if [ -f "$GEMMA4_MODEL" ] && [ -f "$GEMMA4_DRAFTER" ]; then
        echo "Starting Gemma 4 26B MTP on port 8080..."
        nohup "$LLAMA_SERVER" \
            -m "$GEMMA4_MODEL" \
            --mtp-head "$GEMMA4_DRAFTER" \
            --spec-type mtp \
            -ngl "$NGL" \
            --port 8080 \
            --host 0.0.0.0 \
            > /tmp/llamacpp-8080.log 2>&1 &
        echo "  PID: $!"
    else
        echo "SKIP port 8080: model or drafter GGUF not found"
        echo "  Model:   $GEMMA4_MODEL"
        echo "  Drafter: $GEMMA4_DRAFTER"
    fi

    # Qwen3.6 27B MTP (port 8082) — native MTP heads, no drafter needed
    if [ -f "$QWEN27_MODEL" ]; then
        echo "Starting Qwen3.6 27B MTP on port 8082..."
        nohup "$LLAMA_SERVER" \
            -m "$QWEN27_MODEL" \
            --spec-type mtp \
            -ngl "$NGL" \
            --port 8082 \
            --host 0.0.0.0 \
            > /tmp/llamacpp-8082.log 2>&1 &
        echo "  PID: $!"
    else
        echo "SKIP port 8082: model GGUF not found: $QWEN27_MODEL"
    fi

    # Qwen3.6 35B MoE MTP (port 8083) — native MTP heads, no drafter needed
    if [ -f "$QWEN35_MODEL" ]; then
        echo "Starting Qwen3.6 35B MoE MTP on port 8083..."
        nohup "$LLAMA_SERVER" \
            -m "$QWEN35_MODEL" \
            --spec-type mtp \
            -ngl "$NGL" \
            --port 8083 \
            --host 0.0.0.0 \
            > /tmp/llamacpp-8083.log 2>&1 &
        echo "  PID: $!"
    else
        echo "SKIP port 8083: model GGUF not found: $QWEN35_MODEL"
    fi

    echo ""
    echo "All servers started. Check status with: $0 --status"
    echo "Logs: /tmp/llamacpp-{8080,8082,8083}.log"
}

# Auto-start via systemd user service (run once to install)
install_systemd() {
    echo "Installing systemd user services for auto-start..."
    mkdir -p "$HOME/.config/systemd/user"

    for port in 8080 8082 8083; do
        local name="${SERVERS[$port]}"
        local service_file="$HOME/.config/systemd/user/llamacpp-${port}.service"
        cat > "$service_file" << SERVICEOF
[Unit]
Description=llama.cpp ${name} on port ${port}
After=network.target

[Service]
ExecStart=${LLAMA_SERVER} ARGS_PLACEHOLDER
Restart=on-failure
RestartSec=30
Environment=HOME=%h

[Install]
WantedBy=default.target
SERVICEOF
        echo "  Created $service_file (edit ARGS_PLACEHOLDER before enabling)"
    done
    echo ""
    echo "To enable: systemctl --user enable llama-cpp-{8080,8082,8083}.service"
    echo "To start:  systemctl --user start llama-cpp-{8080,8082,8083}.service"
}

case "${1:-}" in
    --stop)    stop_servers ;;
    --status)  status ;;
    --install) install_systemd ;;
    *)         start_servers ;;
esac
