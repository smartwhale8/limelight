#!/bin/bash
# Stop and remove the limelight launchd agent. Leaves the configuration in
# ~/.config/limelight untouched, so the device stays adopted.
set -euo pipefail

LABEL="io.github.smartwhale8.limelight"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [[ -f "$PLIST" ]]; then
  rm -f "$PLIST"
  echo "Removed $PLIST"
else
  echo "No agent found at $PLIST"
fi

echo "Stopped and removed. Configuration in ~/.config/limelight was left in place."
