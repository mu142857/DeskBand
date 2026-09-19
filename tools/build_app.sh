#!/bin/bash
# Build dist/DeskBand.app: a thin launcher that runs main.py with the project's
# .venv. Double-click to start; macOS asks for camera access in the app's name.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/DeskBand.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

"$ROOT/.venv/bin/python" "$ROOT/tools/make_icon.py" "$APP/Contents/Resources/DeskBand.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>DeskBand</string>
    <key>CFBundleDisplayName</key><string>DeskBand</string>
    <key>CFBundleIdentifier</key><string>com.hackthenorth.deskband</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>DeskBand</string>
    <key>CFBundleIconFile</key><string>DeskBand</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSArchitecturePriority</key><array><string>arm64</string></array>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSCameraUsageDescription</key>
    <string>DeskBand looks at the objects on your desk to turn them into a band.</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Not used.</string>
</dict>
</plist>
EOF

cat > "$APP/Contents/MacOS/DeskBand" <<EOF
#!/bin/bash
# Launcher: run DeskBand from its project folder with the bundled venv.
cd "$ROOT"
export SSL_CERT_FILE="$ROOT/.venv/lib/python3.11/site-packages/certifi/cacert.pem"
# A script-only bundle can be started under Rosetta by Finder; the venv's
# packages are arm64-only, so force the native architecture.
# No exec: this script must stay alive as the parent so macOS attributes the
# camera request to DeskBand.app (whose Info.plist explains why) and not to Python.
/usr/bin/arch -arm64 "$ROOT/.venv/bin/python" "$ROOT/main.py" >> "$ROOT/cache/deskband.log" 2>&1
EOF
chmod +x "$APP/Contents/MacOS/DeskBand"
mkdir -p "$ROOT/cache"
# ad-hoc signature: gives the bundle a stable identity for the privacy database
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
touch "$APP"
echo "built $APP"
