#!/bin/bash
# Stop and remove the lamplight launchd agent. Leaves the configuration in
# ~/.config/lamplight untouched, so the device stays adopted.
set -euo pipefail

LABEL="io.github.smartwhale8.lamplight"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [[ -f "$PLIST" ]]; then
  rm -f "$PLIST"
  echo "Removed $PLIST"
else
  echo "No agent found at $PLIST"
fi

echo "Stopped and removed. Configuration in ~/.config/lamplight was left in place."
