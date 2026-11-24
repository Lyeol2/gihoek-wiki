#!/bin/bash
# 기획위키.app 만들기 (더블클릭하거나 터미널에서 실행)
# 폴더를 다른 곳으로 옮겼다면 이 파일을 다시 실행하면 된다.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"
APP="$ROOT/기획위키.app"
BUILD="$ROOT/macapp/build"

# 로그인 셸 기준 PATH (claude / codex CLI 위치 포함)
USER_PATH="$("${SHELL:-/bin/zsh}" -lic 'printf %s "$PATH"' 2>/dev/null || true)"
[ -z "$USER_PATH" ] && USER_PATH="$PATH"
USER_PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$USER_PATH"
PY="$(PATH="$USER_PATH" command -v python3)"
echo "python3: $PY"

mkdir -p "$BUILD"
echo "앱 컴파일 중…"
swiftc -O -swift-version 5 "$ROOT/macapp/main.swift" -o "$BUILD/GameDocWiki"

echo "아이콘 만드는 중…"
swift "$ROOT/macapp/make_icon.swift" "$BUILD/icon.png" >/dev/null
ICONSET="$BUILD/AppIcon.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for sz in 16 32 128 256 512; do
  sips -z $sz $sz "$BUILD/icon.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
  sips -z $((sz*2)) $((sz*2)) "$BUILD/icon.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$BUILD/AppIcon.icns"

echo "앱 묶는 중…"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BUILD/GameDocWiki" "$APP/Contents/MacOS/GameDocWiki"
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

ROOT="$ROOT" PY="$PY" USER_PATH="$USER_PATH" "$PY" - "$APP/Contents/Resources/app-config.json" <<'EOF'
import json, os, sys
cfg = os.path.join(os.environ["ROOT"], "config.json")
port = json.load(open(cfg)).get("port", 4173) if os.path.exists(cfg) else 4173
json.dump({"root": os.environ["ROOT"], "python": os.environ["PY"], "path": os.environ["USER_PATH"], "port": port},
          open(sys.argv[1], "w"), ensure_ascii=False, indent=2)
EOF

cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>기획 위키</string>
  <key>CFBundleDisplayName</key><string>기획 위키</string>
  <key>CFBundleIdentifier</key><string>local.gamedocwiki</string>
  <key>CFBundleExecutable</key><string>GameDocWiki</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.1</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key><true/>
    <key>NSAllowsArbitraryLoads</key><true/>
  </dict>
</dict>
</plist>
EOF

codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
touch "$APP"
echo ""
echo "완료: $APP"
echo "더블클릭해서 실행하세요. 독(Dock)에 끌어다 두면 편해요."
