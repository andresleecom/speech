#!/usr/bin/env bash
set -euo pipefail
VERSION="${1:-0.1.12}"; APP="speech"; ARCH="amd64"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"

python3 -m venv .venv-build
source .venv-build/bin/activate
pip install --upgrade pip
pip install -e .
pip install pyinstaller

pyinstaller packaging/Speech-linux.spec --noconfirm

PA="$(ldconfig -p | awk '/libportaudio\.so\.2/{print $NF; exit}')"
if [ -n "${PA:-}" ]; then
  cp -L "$PA" "dist/$APP/_internal/" 2>/dev/null || cp -L "$PA" "dist/$APP/"
else
  echo "WARN: libportaudio.so.2 not found; install portaudio19-dev" >&2
fi

rm -rf AppDir && mkdir -p AppDir/usr/bin
cp -r "dist/$APP/." AppDir/usr/bin/
install -Dm644 "packaging/linux/$APP.desktop" "AppDir/usr/share/applications/$APP.desktop"
install -Dm644 "packaging/linux/$APP.png" "AppDir/usr/share/icons/hicolor/256x256/apps/$APP.png"

if [ ! -x ./linuxdeploy.AppImage ]; then
  curl -fsSL -o linuxdeploy.AppImage \
    https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
  chmod +x linuxdeploy.AppImage
fi
export APPIMAGE_EXTRACT_AND_RUN=1
./linuxdeploy.AppImage --appdir AppDir \
  --executable "AppDir/usr/bin/$APP" \
  --desktop-file "AppDir/usr/share/applications/$APP.desktop" \
  --icon-file "AppDir/usr/share/icons/hicolor/256x256/apps/$APP.png" \
  --output appimage

DEB="${APP}_${VERSION}_${ARCH}"; rm -rf "$DEB"
mkdir -p "$DEB/DEBIAN" "$DEB/usr/lib/$APP" "$DEB/usr/bin" \
  "$DEB/usr/share/applications" "$DEB/usr/share/icons/hicolor/256x256/apps"
cp -r "dist/$APP/." "$DEB/usr/lib/$APP/"
ln -sf "/usr/lib/$APP/$APP" "$DEB/usr/bin/$APP"
cp "packaging/linux/$APP.desktop" "$DEB/usr/share/applications/$APP.desktop"
cp "packaging/linux/$APP.png" "$DEB/usr/share/icons/hicolor/256x256/apps/$APP.png"
cat > "$DEB/DEBIAN/control" << CTL
Package: $APP
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: libportaudio2, ffmpeg
Maintainer: Andres Lee <maintainer@example.com>
Description: Local speech dictation using Faster Whisper
 Offline speech-to-text with global hotkeys and text insertion.
CTL
dpkg-deb --build --root-owner-group "$DEB"
echo "----"; ls -1 ./*.AppImage "$DEB.deb" 2>/dev/null || true
