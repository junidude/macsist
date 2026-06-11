#!/usr/bin/env bash
# Deploy the app to a non-TCC-protected location + (re)install its LaunchAgent
# (always-on at login, auto-restart on crash).
#
# Why: launchd agents cannot read ~/Documents ("Operation not permitted"), same
# as the server (see server/deploy.sh). Bonus: TCC grants (Accessibility /
# Input Monitoring / Screen Recording) attach to the deployed venv's python and
# survive relaunches — unlike dev runs, where they attach to the terminal host.
#
# Run once, and again after editing any app/*.py.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="$HOME/Library/Application Support/HotkeyExplain/app"
PY=/opt/homebrew/Caskroom/miniforge/base/bin/python3
LABEL=com.hotkeyexplain.app
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/HotkeyExplain"

mkdir -p "$DEST_DIR" "$LOG_DIR"
cp "$SRC_DIR"/*.py "$SRC_DIR/requirements.txt" "$DEST_DIR/"

if [ ! -d "$DEST_DIR/.venv" ]; then
  "$PY" -m venv "$DEST_DIR/.venv"
  "$DEST_DIR/.venv/bin/pip" install --upgrade pip
fi
"$DEST_DIR/.venv/bin/pip" install -q -r "$DEST_DIR/requirements.txt"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DEST_DIR/.venv/bin/python</string>
    <string>$DEST_DIR/main.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>$LOG_DIR/app.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/app.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Deployed app to: $DEST_DIR"
echo "LaunchAgent (re)loaded: $LABEL"
echo "  status:  launchctl list | grep hotkeyexplain"
echo "  logs:    tail -f $LOG_DIR/app.log"
echo "  restart: launchctl kickstart -k gui/\$(id -u)/$LABEL"
