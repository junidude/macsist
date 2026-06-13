#!/usr/bin/env bash
# Build a distributable Macsist.dmg for the website / GitHub Releases.
#
# The bundle is SELF-SIGNED (no Apple notarization), so on a downloader's Mac
# Gatekeeper blocks the first open. The DMG ships a "READ ME FIRST" note and the
# website should repeat it. To open once:
#   right-click Macsist.app -> Open -> Open      (or, if macOS still refuses:)
#   xattr -dr com.apple.quarantine /Applications/Macsist.app
#
# Prereq: brew install python@3.13 (framework build — same as app/deploy.sh).
# Output: release/Macsist.dmg  (+ .sha256). The filename is intentionally
# version-less so the website's "latest" link never changes.

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$ROOT/app"
DIST="$APP_DIR/dist/Macsist.app"
VERSION="$(sed -n 's/^VERSION = "\(.*\)".*/\1/p' "$APP_DIR/setup.py")"
OUT_DIR="$ROOT/release"
DMG="$OUT_DIR/Macsist.dmg"
VOL="Macsist $VERSION"

echo "▸ Building + signing the bundle (no launchd install)…"
BUILD_ONLY=1 "$APP_DIR/deploy.sh"
[ -d "$DIST" ] || { echo "build failed: $DIST not found" >&2; exit 1; }

echo "▸ Staging the disk image…"
mkdir -p "$OUT_DIR"
STAGE="$(mktemp -d)"
ditto "$DIST" "$STAGE/Macsist.app"          # ditto preserves the code signature
ln -s /Applications "$STAGE/Applications"   # drag-to-install target
cat > "$STAGE/READ ME FIRST.txt" <<'TXT'
Macsist — how to open it the first time

This build is self-signed (not notarized by Apple), so macOS Gatekeeper
blocks it the very first time. Open it ONCE like this:

  1) Drag Macsist into the Applications folder (icon on the right).
  2) In Applications, right-click Macsist -> Open -> Open.
     If macOS still refuses ("damaged" / "can't be opened"), run this in
     Terminal once, then open it again:

       xattr -dr com.apple.quarantine /Applications/Macsist.app

  3) On first launch Macsist asks how to connect:
       - an external OpenAI-compatible API (paste a key — works instantly), or
       - a local model (guided server install).
     Grant Accessibility (and Screen Recording for region capture) when
     prompted, then restart the app.

Full guide: https://github.com/junidude/macsist
TXT

echo "▸ Creating $DMG…"
rm -f "$DMG"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo "▸ Checksum:"
( cd "$OUT_DIR" && shasum -a 256 "Macsist.dmg" | tee "Macsist.dmg.sha256" )

cat <<DONE

✅ Built: $DMG  ($(du -h "$DMG" | awk '{print $1}'))

Publish it:
  1) Make the repo public (one time):
       gh repo edit junidude/macsist --visibility public
  2) Create a GitHub Release and attach the DMG:
       gh release create v$VERSION "$DMG" "$DMG.sha256" \\
         --title "Macsist $VERSION" --notes-file - <<'NOTES'
       Download Macsist.dmg below. First open: right-click -> Open (self-signed).
       NOTES
  3) Stable download link for your website (never changes across versions):
       https://github.com/junidude/macsist/releases/latest/download/Macsist.dmg
DONE
