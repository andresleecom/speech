#!/bin/bash
# Build Speech.app and a distributable DMG on macOS.
# Usage: scripts/build_macos.sh [python]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${1:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

BUILD_VERSION_OVERRIDE="${SPEECH_VERSION:-}"
VERSION="${BUILD_VERSION_OVERRIDE:-$($PYTHON -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')}"
if [ -z "$VERSION" ]; then
    echo "Could not determine project version." >&2
    exit 1
fi
export SPEECH_VERSION="$VERSION"

if [ -n "$BUILD_VERSION_OVERRIDE" ]; then
    BUILD_VERSION_FILE="$ROOT/src/winwhisper/_build_version.py"
    ORIGINAL_BUILD_VERSION="$(mktemp)"
    cp "$BUILD_VERSION_FILE" "$ORIGINAL_BUILD_VERSION"
    cleanup_build_version() {
        cp "$ORIGINAL_BUILD_VERSION" "$BUILD_VERSION_FILE"
        rm -f "$ORIGINAL_BUILD_VERSION"
    }
    trap cleanup_build_version EXIT
    "$PYTHON" "$ROOT/scripts/write_build_version.py" "$VERSION"
fi

MACOS_ARCH="${SPEECH_MACOS_ARCH:-}"
if [ -z "$MACOS_ARCH" ]; then
    MACOS_ARCH="$(uname -m)"
fi

case "$MACOS_ARCH" in
    arm64)
        EXPECTED_ARCH="arm64"
        DMG="dist/installer/Speech-$VERSION.dmg"
        STABLE_DMG="dist/installer/Speech.dmg"
        ;;
    intel|x86_64)
        EXPECTED_ARCH="x86_64"
        DMG="dist/installer/Speech-$VERSION-intel.dmg"
        STABLE_DMG="dist/installer/Speech-intel.dmg"
        ;;
    *)
        echo "Unsupported macOS architecture: $MACOS_ARCH" >&2
        exit 1
        ;;
esac

echo "Building Speech.app version $VERSION for $MACOS_ARCH..."
"$PYTHON" -m PyInstaller --noconfirm --clean packaging/Speech.spec

APP="dist/Speech.app"
APP_BINARY="$APP/Contents/MacOS/Speech"
if [ ! -x "$APP_BINARY" ]; then
    echo "Speech.app was not created." >&2
    exit 1
fi

ACTUAL_ARCHS="$(lipo -archs "$APP_BINARY")"
if [[ " $ACTUAL_ARCHS " != *" $EXPECTED_ARCH "* ]]; then
    echo "Expected $EXPECTED_ARCH binary, found: $ACTUAL_ARCHS" >&2
    exit 1
fi

mkdir -p dist/installer

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
