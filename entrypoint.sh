#!/bin/bash
set -euo pipefail

if [ -f /root/.hermes/.env ]; then
    set -a
    # shellcheck disable=SC1091
    source /root/.hermes/.env
    set +a
fi

git config --global --add safe.directory /workspace/NipaPlay-Reload >/dev/null 2>&1 || true

cleanup() {
    if [ -n "${BRIDGE_PID:-}" ]; then
        kill "$BRIDGE_PID" 2>/dev/null || true
    fi
    if [ -n "${HERMES_PID:-}" ]; then
        kill "$HERMES_PID" 2>/dev/null || true
    fi
}
trap cleanup INT TERM

echo "=== Starting Hermes Gateway ==="
hermes gateway run --replace &
HERMES_PID=$!

# Wait for Hermes API to be ready
echo "=== Waiting for Hermes API ==="
for i in $(seq 1 30); do
    if curl -s http://127.0.0.1:${HERMES_API_PORT:-8642}/health > /dev/null 2>&1; then
        echo "Hermes API ready"
        break
    fi
    if ! kill -0 "$HERMES_PID" 2>/dev/null; then
        echo "Hermes gateway exited before API became ready"
        wait "$HERMES_PID"
        exit 1
    fi
    sleep 1
done

if ! curl -s http://127.0.0.1:${HERMES_API_PORT:-8642}/health > /dev/null 2>&1; then
    echo "Hermes API did not become ready"
    exit 1
fi

echo "=== Starting AgentBridge ==="
agentbridge &
BRIDGE_PID=$!

# Wait for either process to exit
wait -n $HERMES_PID $BRIDGE_PID
