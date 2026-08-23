#!/bin/bash
# Start the lamplight service and print the URLs it is reachable on.
#
# Binds 0.0.0.0 by default so a phone on the same network can reach it. Set
# LAMPLIGHT_PYTHON to use a specific interpreter, or LAMPLIGHT_PORT to change the port.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${LAMPLIGHT_PYTHON:-python3}"
PORT="${LAMPLIGHT_PORT:-8765}"

# Best effort at the LAN address, for the phone-reachable URL. Falls back to loopback.
lan_address() {
  if command -v ipconfig >/dev/null 2>&1; then
    for iface in en0 en1 en2; do
      addr="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
      [[ -n "$addr" ]] && { echo "$addr"; return; }
    done
  fi
  if command -v hostname >/dev/null 2>&1; then
    addr="$(hostname -I 2>/dev/null | awk '{print $1}')"
    [[ -n "$addr" ]] && { echo "$addr"; return; }
  fi
  echo "127.0.0.1"
}

IP="$(lan_address)"

echo "lamplight, port $PORT"
echo "  this machine:  http://localhost:$PORT"
echo "  same network:  http://$IP:$PORT"
echo "  API docs:      http://localhost:$PORT/docs"
if [[ -z "${LAMPLIGHT_API_KEY:-}" ]]; then
  echo "  note: no API key set, so anything on this network can control the device"
fi
echo

exec "$PYTHON" -m lamplight.server --port "$PORT"
