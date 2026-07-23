#!/bin/bash
# Build Speech.app and a distributable DMG on macOS.
# Usage: scripts/build_macos.sh [python]
# Optional signing/notarization (never print credential contents):
#   SPEECH_CODESIGN_IDENTITY   Developer ID Application identity (or empty for ad-hoc)
#   SPEECH_NOTARIZE=0|1        default 0; when 1, require identity + notarytool API key
#   SPEECH_NOTARY_KEY          path to .p8 private key file
#   SPEECH_NOTARY_KEY_ID       App Store Connect API key ID
#   SPEECH_NOTARY_ISSUER       App Store Connect Issuer ID
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

# Signing / notarization configuration (credential-free local builds when unset).
CODESIGN_IDENTITY="${SPEECH_CODESIGN_IDENTITY:-}"
NOTARIZE="${SPEECH_NOTARIZE:-0}"
NOTARY_KEY="${SPEECH_NOTARY_KEY:-}"
NOTARY_KEY_ID="${SPEECH_NOTARY_KEY_ID:-}"
NOTARY_ISSUER="${SPEECH_NOTARY_ISSUER:-}"

case "$NOTARIZE" in
    0|1) ;;
    *)
        echo "SPEECH_NOTARIZE must be 0 or 1, got: $NOTARIZE" >&2
        exit 1
        ;;
esac

if [ "$NOTARIZE" = "1" ]; then
    if [ -z "$CODESIGN_IDENTITY" ]; then
        echo "SPEECH_NOTARIZE=1 requires a non-empty SPEECH_CODESIGN_IDENTITY." >&2
        exit 1
    fi
    if [ -z "$NOTARY_KEY" ] || [ ! -r "$NOTARY_KEY" ]; then
        echo "SPEECH_NOTARIZE=1 requires SPEECH_NOTARY_KEY to be a readable key file path." >&2
        exit 1
    fi
    if [ -z "$NOTARY_KEY_ID" ]; then
        echo "SPEECH_NOTARIZE=1 requires SPEECH_NOTARY_KEY_ID." >&2
        exit 1
    fi
    if [ -z "$NOTARY_ISSUER" ]; then
        echo "SPEECH_NOTARIZE=1 requires SPEECH_NOTARY_ISSUER." >&2
        exit 1
    fi
fi

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

if [ -n "$CODESIGN_IDENTITY" ]; then
    echo "Building Speech.app version $VERSION for $MACOS_ARCH (codesign identity set)..."
else
    echo "Building Speech.app version $VERSION for $MACOS_ARCH (ad-hoc / unsigned local)..."
fi
export SPEECH_CODESIGN_IDENTITY="$CODESIGN_IDENTITY"
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

if [ -n "$CODESIGN_IDENTITY" ]; then
    echo "Verifying app codesign (strict/deep)..."
    codesign --verify --deep --strict --verbose=2 "$APP"
fi

mkdir -p dist/installer

echo "Creating DMG..."
STAGING="$(mktemp -d)"
# Always remove staging, including on failure after create.
cleanup_staging() {
    rm -rf "$STAGING"
}
if [ -n "$BUILD_VERSION_OVERRIDE" ]; then
    # Chain with existing build-version restore on EXIT.
    cleanup_all() {
        cleanup_staging
        cleanup_build_version
    }
    trap cleanup_all EXIT
else
    trap cleanup_staging EXIT
fi
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -volname "Speech" -srcfolder "$STAGING" -ov -format UDZO "$DMG" >/dev/null
cleanup_staging
# Staging gone; keep only build-version trap if needed.
if [ -n "$BUILD_VERSION_OVERRIDE" ]; then
    trap cleanup_build_version EXIT
else
    trap - EXIT
fi

if [ -n "$CODESIGN_IDENTITY" ]; then
    echo "Signing DMG..."
    codesign --force --sign "$CODESIGN_IDENTITY" "$DMG"
    echo "Verifying DMG codesign..."
    codesign --verify --strict --verbose=2 "$DMG"
fi

if [ "$NOTARIZE" = "1" ]; then
    echo "Submitting DMG for notarization..."
    xcrun notarytool submit "$DMG" \
        --key "$NOTARY_KEY" \
        --key-id "$NOTARY_KEY_ID" \
        --issuer "$NOTARY_ISSUER" \
        --wait
    echo "Stapling notarization ticket..."
    xcrun stapler staple "$DMG"
    echo "Validating staple..."
    xcrun stapler validate "$DMG"
fi

# Stable name and checksums only after signing / notarization (D06).
cp "$DMG" "$STABLE_DMG"

shasum -a 256 "$DMG" | awk '{print $1}' > "$DMG.sha256"
shasum -a 256 "$STABLE_DMG" | awk '{print $1}' > "$STABLE_DMG.sha256"

echo "Built:"
ls -la dist/installer/Speech*.dmg*
