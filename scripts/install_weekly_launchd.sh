#!/bin/bash
set -euo pipefail

PROJECT_DIR="/Users/kseniagolovcenko/Projects/bidmatrix-monitor"
LABEL="com.bidmatrix.monitor.weekly"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$HOME/Library/LaunchAgents"
mkdir -p "$LOG_DIR"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>WorkingDirectory</key>
  <string>$PROJECT_DIR</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PROJECT_DIR/.venv/bin/bidmatrix-monitor</string>
    <string>--weekly</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>5</integer>
    <key>Hour</key>
    <integer>17</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/weekly-monitor.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/weekly-monitor-error.log</string>
  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Installed weekly BidMatrix summary schedule."
echo "It will run every Friday at 17:00 local Mac time."
echo "Plist: $PLIST"
echo "Logs: $LOG_DIR"
