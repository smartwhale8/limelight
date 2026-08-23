#!/bin/bash
# Install a systemd --user unit so the limelight service runs at login and restarts if it
# exits. A user unit is preferred over a system one because the configuration, including
# the device token, lives in the user's home directory at mode 0600.
#
# Ramps still cannot progress while the machine is suspended: sunrise and fade_off are
# driven by this service, not by the device. Only the `timer` schedule kind runs on the
# device itself.
set -euo pipefail

UNIT="limelight.service"
UNIT_DIR="$HOME/.config/systemd/user"
UNIT_PATH="$UNIT_DIR/$UNIT"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${LIMELIGHT_PYTHON:-$(command -v python3)}"
PORT="${LIMELIGHT_PORT:-8765}"

if ! command -v systemctl >/dev/null; then
  echo "systemctl not found. On macOS use packaging/launchd/install.sh." >&2
  exit 1
fi

if ! "$PYTHON" -c "import limelight" 2>/dev/null; then
  echo "error: '$PYTHON' cannot import limelight." >&2
  echo "Install it first (pip install -e \".[server]\"), or set LIMELIGHT_PYTHON to the" >&2
  echo "interpreter of the environment where it is installed." >&2
  exit 1
fi

cat <<EOF
This will install a systemd user unit:

  unit        $UNIT_PATH
  interpreter $PYTHON
  working dir $REPO
  port        $PORT

The service will start now and at every login.
EOF

read -rp "Proceed? [y/N] " reply
[[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

mkdir -p "$UNIT_DIR"

cat > "$UNIT_PATH" <<EOF
[Unit]
Description=limelight, local control for miIO smart lights
Documentation=https://github.com/smartwhale8/limelight
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$REPO
ExecStart=$PYTHON -m limelight.server --port $PORT
Restart=on-failure
RestartSec=30

# An API key can be supplied here rather than written into config.json:
# Environment=LIMELIGHT_API_KEY=...

# Modest hardening. The service needs only outbound UDP on the local network,
# a listening TCP socket, and its own configuration directory.
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%h/.config/limelight
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"

echo
echo "Installed and started."
echo "  status:  systemctl --user status $UNIT"
echo "  logs:    journalctl --user -u $UNIT -f"
echo "  open:    http://localhost:$PORT"
echo "  remove:  $(dirname "${BASH_SOURCE[0]}")/uninstall.sh"
echo
echo "A user unit stops at logout unless lingering is enabled. To keep schedules firing"
echo "when you are not logged in:"
echo "  sudo loginctl enable-linger \"\$USER\""
