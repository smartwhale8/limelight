#!/bin/bash
# Stop, disable and remove the limelight systemd user unit. Leaves the configuration in
# ~/.config/limelight untouched, so the device stays adopted.
set -euo pipefail

UNIT="limelight.service"
UNIT_PATH="$HOME/.config/systemd/user/$UNIT"

systemctl --user disable --now "$UNIT" 2>/dev/null || true

if [[ -f "$UNIT_PATH" ]]; then
  rm -f "$UNIT_PATH"
  systemctl --user daemon-reload
  echo "Removed $UNIT_PATH"
else
  echo "No unit found at $UNIT_PATH"
fi

echo "Stopped and removed. Configuration in ~/.config/limelight was left in place."
