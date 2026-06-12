#!/usr/bin/env bash
# Deploy the server scripts to a non-TCC-protected location so the launchd
# agent can run them (launchd agents cannot read ~/Documents).
#
# Run this once, and again after editing server.py or start_server.sh.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="$HOME/Library/Application Support/Macsist/server"
LABEL=com.macsist.llm-server
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/llm-server"
# Pre-rename (≤M7) agent
LEGACY_LABEL=com.hotkeyexplain.llm-server

mkdir -p "$DEST_DIR" "$LOG_DIR"
cp "$SRC_DIR/server.py"       "$DEST_DIR/server.py"
cp "$SRC_DIR/start_server.sh" "$DEST_DIR/start_server.sh"
chmod +x "$DEST_DIR/start_server.sh"

echo "Deployed to: $DEST_DIR"
echo "  server.py"
echo "  start_server.sh"
# models.env is owned by install.sh (M10) — never written here, only reported.
if [[ -f "$DEST_DIR/models.env" ]]; then
  echo "  models.env (preserved):"
  sed 's/^/    /' "$DEST_DIR/models.env"
else
  echo "  models.env 없음 — 기본 모델 사용 (start_server.sh defaults)"
fi

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$DEST_DIR/start_server.sh</string>
    <string>--supervise</string>
  </array>
  <key>WorkingDirectory</key><string>$DEST_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG_DIR/launchd.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/launchd.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/opt/homebrew/Caskroom/miniforge/base/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>HOME</key>
    <string>$HOME</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LEGACY_LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
# bootstrap right after bootout intermittently fails with I/O error 5 while
# launchd tears the old job down — retry briefly instead of dying (M10).
for attempt in 1 2 3 4 5; do
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null && break
  [ "$attempt" = 5 ] && { echo "bootstrap failed: $LABEL" >&2; exit 1; }
  sleep 1
done
echo "LaunchAgent (re)loaded: $LABEL. Tail logs:"
echo "  tail -f $LOG_DIR/vlm.log"
