#!/usr/bin/env bash
# Build x86_64 AppImage and Debian packages on Linux.
# Usage: scripts/build_linux.sh [python]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${1:-}"
if [ -z "$PYTHON" ]; then
    if [ -x ".venv/bin/python" ]; then
        PYTHON=".venv/bin/python"
    else
        PYTHON="python3"
    fi
fi
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Python interpreter is unavailable: $PYTHON" >&2
    exit 1
fi

if [ "$(uname -m)" != "x86_64" ]; then
    echo "Linux packages currently support x86_64 only." >&2
    exit 1
fi

for command_name in curl dpkg-deb file find getconf ldconfig sha256sum xclip; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "Required build command is unavailable: $command_name" >&2
        exit 1
    fi
done

BUILD_VERSION_OVERRIDE="${SPEECH_VERSION:-}"
VERSION="${BUILD_VERSION_OVERRIDE:-$($PYTHON -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')}"
if [ -z "$VERSION" ]; then
    echo "Could not determine project version." >&2
    exit 1
fi
export SPEECH_VERSION="$VERSION"

GLIBC_VERSION="$(getconf GNU_LIBC_VERSION | awk '{print $2}')"
if [ -z "$GLIBC_VERSION" ]; then
    echo "Could not determine the glibc version." >&2
    exit 1
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

echo "Building Speech version $VERSION for x86_64 Linux..."
"$PYTHON" -m PyInstaller --noconfirm --clean packaging/Speech.spec

APP_BINARY="$ROOT/dist/Speech/Speech"
if [ ! -x "$APP_BINARY" ]; then
    echo "Packaged Speech executable was not created." >&2
    exit 1
fi

PORTAUDIO="$(
    ldconfig -p \
        | awk '$1 == "libportaudio.so.2" && /x86-64/ {path=$NF} END {print path}'
)"
if [ -z "$PORTAUDIO" ]; then
    echo "A 64-bit libportaudio.so.2 was not found." >&2
    exit 1
fi
if ! file -L "$PORTAUDIO" | grep -q "ELF 64-bit"; then
    echo "PortAudio is not a 64-bit ELF library: $PORTAUDIO" >&2
    exit 1
fi
cp -L "$PORTAUDIO" "$ROOT/dist/Speech/_internal/"

BUILD_ROOT="$ROOT/build/linux"
APPDIR="$BUILD_ROOT/AppDir"
DEB_ROOT="$BUILD_ROOT/deb"
INSTALLER_DIR="$ROOT/dist/installer"
rm -rf "$APPDIR" "$DEB_ROOT"
mkdir -p "$APPDIR/usr/lib/speech" "$APPDIR/usr/bin"
mkdir -p "$INSTALLER_DIR"

cp -a "$ROOT/dist/Speech/." "$APPDIR/usr/lib/speech/"
install -m755 "$ROOT/packaging/linux/speech" "$APPDIR/usr/bin/speech"
install -m755 "$(command -v xclip)" "$APPDIR/usr/bin/xclip"
install -Dm644 "$ROOT/packaging/linux/speech.desktop" \
    "$APPDIR/usr/share/applications/speech.desktop"
install -Dm644 "$ROOT/packaging/linux/speech.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/speech.png"

LINUXDEPLOY_TAG="1-alpha-20251107-1"
LINUXDEPLOY_SHA256="c20cd71e3a4e3b80c3483cef793cda3f4e990aca14014d23c544ca3ce1270b4d"
LINUXDEPLOY="$BUILD_ROOT/linuxdeploy-x86_64.AppImage"
LINUXDEPLOY_URL="https://github.com/linuxdeploy/linuxdeploy/releases/download/$LINUXDEPLOY_TAG/linuxdeploy-x86_64.AppImage"
APPIMAGE_RUNTIME_TAG="20251108"
APPIMAGE_RUNTIME_SHA256="2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d"
APPIMAGE_RUNTIME="$BUILD_ROOT/runtime-x86_64"
APPIMAGE_RUNTIME_URL="https://github.com/AppImage/type2-runtime/releases/download/$APPIMAGE_RUNTIME_TAG/runtime-x86_64"

verify_file() {
    local target="$1"
    local sha256="$2"
    printf '%s  %s\n' "$sha256" "$target" | sha256sum --check --status
}

download_verified() {
    local url="$1"
    local target="$2"
    local sha256="$3"
    local label="$4"
    if [ ! -f "$target" ] || ! verify_file "$target" "$sha256"; then
        rm -f "$target"
        curl --fail --location --silent --show-error --output "$target" "$url"
    fi
    if ! verify_file "$target" "$sha256"; then
        echo "$label checksum verification failed." >&2
        exit 1
    fi
}

download_verified \
    "$LINUXDEPLOY_URL" \
    "$LINUXDEPLOY" \
    "$LINUXDEPLOY_SHA256" \
    "linuxdeploy"
download_verified \
    "$APPIMAGE_RUNTIME_URL" \
    "$APPIMAGE_RUNTIME" \
    "$APPIMAGE_RUNTIME_SHA256" \
    "AppImage runtime"
chmod +x "$LINUXDEPLOY"

PYINSTALLER_INTERNAL="$APPDIR/usr/lib/speech/_internal"
BUNDLED_LIBRARY_DIRS="$(find "$PYINSTALLER_INTERNAL" -type d -name "*.libs" -printf ':%p')"
export LD_LIBRARY_PATH="$PYINSTALLER_INTERNAL$BUNDLED_LIBRARY_DIRS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

VERSIONED_APPIMAGE="$INSTALLER_DIR/Speech-$VERSION.AppImage"
STABLE_APPIMAGE="$INSTALLER_DIR/Speech.AppImage"
rm -f "$VERSIONED_APPIMAGE" "$STABLE_APPIMAGE"
export APPIMAGE_EXTRACT_AND_RUN=1
export LDAI_OUTPUT="$VERSIONED_APPIMAGE"
export LDAI_RUNTIME_FILE="$APPIMAGE_RUNTIME"
export LINUXDEPLOY_OUTPUT_VERSION="$VERSION"
"$LINUXDEPLOY" --appdir "$APPDIR" \
    --executable "$APPDIR/usr/lib/speech/Speech" \
    --executable "$APPDIR/usr/bin/xclip" \
    --desktop-file "$APPDIR/usr/share/applications/speech.desktop" \
    --icon-file "$APPDIR/usr/share/icons/hicolor/256x256/apps/speech.png" \
    --output appimage
if [ ! -s "$VERSIONED_APPIMAGE" ]; then
    echo "AppImage was not created." >&2
    exit 1
fi
cp "$VERSIONED_APPIMAGE" "$STABLE_APPIMAGE"

mkdir -p "$DEB_ROOT/DEBIAN" "$DEB_ROOT/usr/lib/speech" "$DEB_ROOT/usr/bin"
cp -a "$ROOT/dist/Speech/." "$DEB_ROOT/usr/lib/speech/"
install -m755 "$ROOT/packaging/linux/speech" "$DEB_ROOT/usr/bin/speech"
install -Dm644 "$ROOT/packaging/linux/speech.desktop" \
    "$DEB_ROOT/usr/share/applications/speech.desktop"
install -Dm644 "$ROOT/packaging/linux/speech.png" \
    "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps/speech.png"
cat > "$DEB_ROOT/DEBIAN/control" << CONTROL
Package: speech
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: libc6 (>= $GLIBC_VERSION), libportaudio2, xclip,
 libgtk-3-0, libayatana-appindicator3-1,
 gir1.2-ayatanaappindicator3-0.1
Maintainer: Andres Lee <8980080+andresleecom@users.noreply.github.com>
Description: Local speech dictation using Faster Whisper
 Offline speech-to-text with global hotkeys and text insertion.
CONTROL

VERSIONED_DEB="$INSTALLER_DIR/Speech-$VERSION.deb"
STABLE_DEB="$INSTALLER_DIR/Speech.deb"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$VERSIONED_DEB"
cp "$VERSIONED_DEB" "$STABLE_DEB"

write_checksum() {
    local target="$1"
    local digest
    digest="$(sha256sum "$target" | awk '{print $1}')"
    printf '%s  %s\n' "$digest" "$(basename "$target")" > "$target.sha256"
}

write_checksum "$VERSIONED_APPIMAGE"
write_checksum "$STABLE_APPIMAGE"
write_checksum "$VERSIONED_DEB"
write_checksum "$STABLE_DEB"

echo "Built:"
ls -la "$INSTALLER_DIR"/Speech*.AppImage* "$INSTALLER_DIR"/Speech*.deb*
