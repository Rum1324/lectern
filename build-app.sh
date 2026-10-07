#!/bin/bash
# Builds dist/Lectern.app: a menu bar launcher (app/LecternApp.swift) bundling lectern.py,
# laser.swift and web/. Needs only the Xcode Command Line Tools (swiftc, sips, iconutil).
set -euo pipefail
cd "$(dirname "$0")"
APP=dist/Lectern.app
rm -rf dist build-tmp
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources" build-tmp

echo "compiling (arm64 + x86_64)..."
swiftc -O -target arm64-apple-macos11 app/LecternApp.swift -o build-tmp/Lectern-arm64
swiftc -O -target x86_64-apple-macos11 app/LecternApp.swift -o build-tmp/Lectern-x86_64
lipo -create build-tmp/Lectern-arm64 build-tmp/Lectern-x86_64 -output "$APP/Contents/MacOS/Lectern"

echo "bundling server..."
cp lectern.py laser.swift "$APP/Contents/Resources/"
cp -R web "$APP/Contents/Resources/web"
cp app/Info.plist "$APP/Contents/Info.plist"

echo "icon..."
ICONSET=build-tmp/Lectern.iconset
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s web/icon-512.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2))
  sips -z $d $d web/icon-512.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Lectern.icns"

# Ad-hoc signature with a fixed identifier, so macOS keeps the Accessibility grant across rebuilds.
codesign --force --sign - --identifier com.lectern.menubar "$APP"
rm -rf build-tmp
echo "built $APP"
