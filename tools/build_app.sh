#!/bin/bash
# Build dist/WaveLens.app: a small native launcher that runs main.py with the
# project's .venv. Double-click to start; macOS asks for camera access in the app's name.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/dist/WaveLens.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

"$ROOT/.venv/bin/python" "$ROOT/tools/make_icon.py" "$APP/Contents/Resources/WaveLens.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>WaveLens</string>
    <key>CFBundleDisplayName</key><string>WaveLens</string>
    <key>CFBundleIdentifier</key><string>com.hackthenorth.wavelens</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>WaveLens</string>
    <key>CFBundleIconFile</key><string>WaveLens</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSArchitecturePriority</key><array><string>arm64</string></array>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSCameraUsageDescription</key>
    <string>WaveLens looks at the objects on your desk to turn them into a band.</string>
    <key>NSMicrophoneUsageDescription</key>
    <string>Not used.</string>
</dict>
</plist>
EOF

# Native launcher (see tools/launcher.c for why this cannot be a shell script).
# arm64 only, so Finder never starts it under Rosetta.
clang -arch arm64 -O2 -Wall -DROOT="\"$ROOT\"" -o "$APP/Contents/MacOS/WaveLens" "$ROOT/tools/launcher.c"
mkdir -p "$ROOT/cache"
# ad-hoc signature: gives the bundle a stable identity for the privacy database
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
touch "$APP"
echo "built $APP"
