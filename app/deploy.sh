#!/usr/bin/env bash
# Deploy the app as a signed Macsist.app bundle + (re)install its LaunchAgent
# (always-on at login, auto-restart on crash).
#
# M12: py2app standalone build — the bundle is what makes Dock/Cmd-Tab/TCC
# show "Macsist" instead of "Python". Signed with the fixed self-signed
# identity "Macsist Signing" so the TCC designated requirement
# (identifier "com.macsist.app" + certificate leaf) is byte-identical across
# rebuilds → Accessibility/Screen Recording grants survive every redeploy.
# NEVER ad-hoc sign (-s -): that pins the per-build CDHash and resets TCC.
#
# Build python must be a FRAMEWORK build (brew python@3.13) — the miniforge
# base python is static (libpython3.13.a), py2app's stub can't dlopen it.
#
# Why ~/Library/Application Support: launchd agents cannot read ~/Documents
# ("Operation not permitted"), same as the server (see server/deploy.sh).
#
# Run once, and again after editing any app/*.py.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUPPORT_DIR="$HOME/Library/Application Support/Macsist"
APP_BUNDLE="$SUPPORT_DIR/Macsist.app"
BUILD_VENV="$SUPPORT_DIR/build-venv"
BREW_PY=/opt/homebrew/opt/python@3.13/bin/python3.13
IDENTITY="Macsist Signing"
LABEL=com.macsist.app
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/Macsist"
# Pre-rename (≤M7) agent — retire it so two apps don't fight over the hotkeys.
LEGACY_LABEL=com.hotkeyexplain.app

[ -x "$BREW_PY" ] || {
  echo "python@3.13 (framework 빌드)이 필요합니다: brew install python@3.13" >&2
  exit 1
}

# ── Signing identity (one-time) ─────────────────────────────────────────────
ensure_signing_identity() {
  security find-identity -v -p codesigning | grep -q "\"$IDENTITY\"" && return 0
  echo "서명 인증서 '$IDENTITY' 생성 (최초 1회)…"
  local tmp; tmp="$(mktemp -d)"
  cat > "$tmp/csr.cnf" <<'CNF'
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = Macsist Signing
[v3]
keyUsage = critical,digitalSignature
extendedKeyUsage = critical,codeSigning
basicConstraints = critical,CA:FALSE
CNF
  openssl req -x509 -newkey rsa:2048 -days 3650 -nodes \
      -keyout "$tmp/key.pem" -out "$tmp/cert.pem" -config "$tmp/csr.cnf" \
      2>/dev/null
  # PEM imports, NOT pkcs12: OpenSSL 3.x p12 defaults (AES/PBKDF2) fail
  # SecKeychainItemImport MAC verification. Key + cert in the same keychain
  # form the identity; -T lets codesign use the key without a prompt.
  security import "$tmp/key.pem" \
      -k "$HOME/Library/Keychains/login.keychain-db" -T /usr/bin/codesign
  security import "$tmp/cert.pem" \
      -k "$HOME/Library/Keychains/login.keychain-db"
  # User-domain trust is enough for codesign and needs no sudo (verified on
  # macOS 26.2); -p codeSign scopes the trust to code signing only.
  security add-trusted-cert -r trustRoot -p codeSign \
      -k "$HOME/Library/Keychains/login.keychain-db" "$tmp/cert.pem"
  rm -rf "$tmp"
  security find-identity -v -p codesigning | grep -q "\"$IDENTITY\"" || {
    echo "서명 인증서 생성 실패 — security find-identity 출력을 확인하세요." >&2
    exit 1
  }
  echo "  ⓘ 서명/신뢰 등록 중 Keychain 암호 창이 뜨면 '항상 허용'을 누르세요."
}

# ── Sign inside-out (framework → loose Mach-Os → bundle seal) ───────────────
sign_bundle() {
  local bundle="$1"
  xattr -cr "$bundle"  # Finder metadata = codesign "detritus" failure
  # ("replacing existing signature" stderr chatter is expected — py2app
  # ad-hoc-signs its output; failures still surface via the verify below.)
  codesign --force --sign "$IDENTITY" \
      "$bundle/Contents/Frameworks/Python.framework/Versions/3.13" 2>/dev/null
  # .so/.dylib under Resources aren't reached by --deep; re-sign so nothing
  # keeps a per-build linker ad-hoc signature (must happen BEFORE the outer
  # signature seals Resources by hash).
  find "$bundle/Contents/Resources" \( -name '*.so' -o -name '*.dylib' \) \
      -exec codesign --force --sign "$IDENTITY" {} + 2>/dev/null
  codesign --force --deep --sign "$IDENTITY" "$bundle" 2>/dev/null
  codesign --verify --deep --strict "$bundle"
}

ensure_signing_identity

# ── Build venv (framework python; auto-heal after brew upgrades) ────────────
if ! "$BUILD_VENV/bin/python" -c '' 2>/dev/null; then
  rm -rf "$BUILD_VENV"
  "$BREW_PY" -m venv "$BUILD_VENV"
  "$BUILD_VENV/bin/pip" install -q --upgrade pip setuptools wheel
fi
"$BUILD_VENV/bin/pip" install -q "py2app==0.28.10" -r "$SRC_DIR/requirements.txt"

# ── py2app build (in the repo — only launchd needs the deployed copy) ───────
rm -rf "$SRC_DIR/build" "$SRC_DIR/dist"
(cd "$SRC_DIR" && "$BUILD_VENV/bin/python" setup.py py2app 2>&1 \
    | tail -2)

sign_bundle "$SRC_DIR/dist/Macsist.app"

# BUILD_ONLY (release.sh): produce the signed bundle, skip the launchd install.
if [ -n "${BUILD_ONLY:-}" ]; then
  echo "Built (BUILD_ONLY): $SRC_DIR/dist/Macsist.app"
  exit 0
fi

# ── Install: bootout → swap bundle → plist → bootstrap ──────────────────────
mkdir -p "$SUPPORT_DIR" "$LOG_DIR"
launchctl bootout "gui/$(id -u)/$LEGACY_LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

rm -rf "$APP_BUNDLE"
ditto "$SRC_DIR/dist/Macsist.app" "$APP_BUNDLE"  # cp -R drops signing metadata
codesign --verify --deep --strict "$APP_BUNDLE"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_BUNDLE/Contents/MacOS/Macsist</string>
  </array>
  <key>WorkingDirectory</key><string>$SUPPORT_DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>LimitLoadToSessionType</key><string>Aqua</string>
  <key>StandardOutPath</key><string>$LOG_DIR/app.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/app.log</string>
</dict>
</plist>
EOF

# bootstrap right after bootout intermittently fails with I/O error 5 while
# launchd tears the old job down — retry briefly instead of dying (M10).
for attempt in 1 2 3 4 5; do
  launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null && break
  [ "$attempt" = 5 ] && { echo "bootstrap failed: $LABEL" >&2; exit 1; }
  sleep 1
done

# Legacy venv deployment (≤M11) — remove only once the bundle agent is live.
# config.json/history.jsonl live at $SUPPORT_DIR root, not under app/.
if [ -d "$SUPPORT_DIR/app" ]; then
  rm -rf "$SUPPORT_DIR/app"
  echo "구 venv 배포 제거: $SUPPORT_DIR/app"
fi

echo "Deployed app bundle: $APP_BUNDLE"
echo "LaunchAgent (re)loaded: $LABEL"
echo "  status:  launchctl list | grep macsist"
echo "  logs:    tail -f $LOG_DIR/app.log"
echo "  restart: launchctl kickstart -k gui/\$(id -u)/$LABEL"
