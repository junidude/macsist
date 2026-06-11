#!/usr/bin/env bash
# Deploy the server scripts to a non-TCC-protected location so the launchd
# agent can run them (launchd agents cannot read ~/Documents).
#
# Run this once, and again after editing server.py or start_server.sh.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST_DIR="$HOME/Library/Application Support/HotkeyExplain/server"

mkdir -p "$DEST_DIR"
cp "$SRC_DIR/server.py"       "$DEST_DIR/server.py"
cp "$SRC_DIR/start_server.sh" "$DEST_DIR/start_server.sh"
chmod +x "$DEST_DIR/start_server.sh"

echo "Deployed to: $DEST_DIR"
echo "  server.py"
echo "  start_server.sh"

# (Re)install the LaunchAgent
PLIST="$HOME/Library/LaunchAgents/com.hotkeyexplain.llm-server.plist"
launchctl bootout "gui/$(id -u)/com.hotkeyexplain.llm-server" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
echo "LaunchAgent (re)loaded. Tail logs:"
echo "  tail -f ~/Library/Logs/llm-server/vlm.log"
