#!/bin/bash
# Build Speech.app and a distributable DMG on macOS.
# Usage: scripts/build_macos.sh [python]
set -euo pipefail

PYTHON="${1:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

VERSION="$("$PYTHON" -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
if [ -z "$VERSION" ]; then
    echo "Could not determine project version." >&2
    exit 1
fi

echo "Building Speech.app version $VERSION..."
"$PYTHON" -m PyInstaller --noconfirm --clean packaging/Speech.spec

APP="dist/Speech.app"
if [ ! -d "$APP" ]; then
    echo "Speech.app was not created." >&2
    exit 1
fi

mkdir -p dist/installer
DMG="dist/installer/Speech-$VERSION.dmg"
STABLE_DMG="dist/installer/Speech.dmg"

echo "Creating DMG..."
STAGING="$(mktemp -d)"
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "Speech" -srcfolder "$STAGING" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGING"
cp "$DMG" "$STABLE_DMG"

shasum -a 256 "$DMG" | awk '{print $1}' > "$DMG.sha256"
shasum -a 256 "$STABLE_DMG" | awk '{print $1}' > "$STABLE_DMG.sha256"

echo "Built:"
ls -la dist/installer/Speech*.dmg*
