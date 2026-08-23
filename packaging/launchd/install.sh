#!/bin/bash
# Install a per-user launchd agent so the lamplight service runs at login and restarts if
# it exits. Paths are substituted from the current environment rather than hard-coded,
# because launchd requires absolute paths and will not expand ~ or read your PATH.
#
# Ramps still cannot progress while the machine is asleep: sunrise and fade_off are driven
# by this service, not by the device. Only the `timer` schedule kind runs on the device.
set -euo pipefail

LABEL="io.github.smartwhale8.lamplight"
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENT_DIR/$LABEL.plist"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${LAMPLIGHT_PYTHON:-$(command -v python3)}"
PORT="${LAMPLIGHT_PORT:-8765}"
LOG="$HOME/Library/Logs/lamplight.log"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script is for macOS. On Linux use packaging/systemd/install.sh." >&2
  exit 1
fi

if ! "$PYTHON" -c "import lamplight" 2>/dev/null; then
  echo "error: '$PYTHON' cannot import lamplight." >&2
  echo "Install it first (pip install -e \".[server]\"), or set LAMPLIGHT_PYTHON to the" >&2
  echo "interpreter of the environment where it is installed." >&2
  exit 1
fi

cat <<EOF
This will install a launchd agent:

  label       $LABEL
  plist       $PLIST
  interpreter $PYTHON
  working dir $REPO
  port        $PORT
  log         $LOG

The service will start now and at every login.
EOF

read -rp "Proceed? [y/N] " reply
[[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

mkdir -p "$AGENT_DIR" "$(dirname "$LOG")"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>-m</string>
        <string>lamplight.server</string>
        <string>--port</string>
        <string>$PORT</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO</string>

    <key>RunAtLoad</key>
    <true/>

    <!-- Restart on a crash, but not after a clean exit. -->
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <!-- Do not spin if startup fails repeatedly, for instance with no device configured. -->
    <key>ThrottleInterval</key>
    <integer>30</integer>

    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>

    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
EOF

# bootout first so re-running this script reloads rather than failing on a duplicate label.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo
echo "Installed and started."
echo "  status:  launchctl print gui/$(id -u)/$LABEL | head -20"
echo "  logs:    tail -f $LOG"
echo "  open:    http://localhost:$PORT"
echo "  remove:  $(dirname "${BASH_SOURCE[0]}")/uninstall.sh"
