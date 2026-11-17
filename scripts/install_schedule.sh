#!/bin/bash
# Install (or re-install) the daily 20:30 collection job into macOS launchd.
# Safe to run more than once.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.mandipulse.collect"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_ROOT/logs"
chmod +x "$PROJECT_ROOT/scripts/run_daily.sh"

# Fill in the real project path and copy the job definition into place.
sed "s#PROJECT_ROOT#$PROJECT_ROOT#g" "$PROJECT_ROOT/scripts/$LABEL.plist" > "$TARGET"

# Unload the old version if it's loaded, then load the new one.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"

echo "Installed $LABEL -> runs daily at 20:30. Logs: $PROJECT_ROOT/logs/collect_daily.log"
echo "Run it now to test:  launchctl kickstart gui/$(id -u)/$LABEL"
