#!/bin/bash
# Stop, disable and remove the lamplight systemd user unit. Leaves the configuration in
# ~/.config/lamplight untouched, so the device stays adopted.
set -euo pipefail

UNIT="lamplight.service"
UNIT_PATH="$HOME/.config/systemd/user/$UNIT"

systemctl --user disable --now "$UNIT" 2>/dev/null || true

if [[ -f "$UNIT_PATH" ]]; then
  rm -f "$UNIT_PATH"
  systemctl --user daemon-reload
  echo "Removed $UNIT_PATH"
else
  echo "No unit found at $UNIT_PATH"
fi

echo "Stopped and removed. Configuration in ~/.config/lamplight was left in place."
