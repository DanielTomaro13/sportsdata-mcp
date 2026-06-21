#!/bin/sh
# Assemble sportsdata-mcp.app around the PyInstaller onedir bundle (commerce Phase 3).
#
#   sh scripts/build-installer.sh      # produces dist/sportsdata-mcp/ (the onedir)
#   sh scripts/make-macos-app.sh       # wraps it as dist/sportsdata-mcp.app
#
# The bundled Mach-O binary becomes the bundle's MAIN executable at
#   sportsdata-mcp.app/Contents/MacOS/sportsdata-mcp
# (a Mach-O main executable is required for the hardened runtime + notarization — a shell
# launcher as CFBundleExecutable can notarize-pass yet refuse to launch). That path is
# exactly what `sportsdata-mcp setup` writes (sys.executable when frozen) into the config.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="sportsdata-mcp"
DIST="$REPO/dist"
ONEDIR="$DIST/$APP_NAME"               # from build-installer.sh
APP="$DIST/$APP_NAME.app"
PKG="$REPO/packaging/macos"
VERSION="$("$REPO/.venv/bin/python" -c 'import sportsdata_mcp; print(sportsdata_mcp.__version__)' 2>/dev/null \
           || python -c 'import sportsdata_mcp; print(sportsdata_mcp.__version__)')"

if [ ! -d "$ONEDIR" ]; then
  echo "error: $ONEDIR not found — run 'sh scripts/build-installer.sh' first" >&2
  exit 1
fi

echo "assembling $APP_NAME.app $VERSION"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Frameworks"

# Lay the onedir out the way PyInstaller's bootloader expects INSIDE a .app: the Mach-O
# executable alone in Contents/MacOS (so it's the bundle's main executable), and the whole
# `_internal` payload FLAT in Contents/Frameworks. When the bootloader detects it's running
# from `…app/Contents/MacOS/`, it resolves its Python runtime + support libs at
# `…/Contents/Frameworks/` (NOT `…/MacOS/_internal/`) — putting them under MacOS makes the
# app fail at launch with "Failed to load Python shared library …/Contents/Frameworks/Python".
cp "$ONEDIR/$APP_NAME" "$APP/Contents/MacOS/$APP_NAME"
cp -R "$ONEDIR/_internal/." "$APP/Contents/Frameworks/"

# Info.plist with the version substituted in (CFBundleExecutable = sportsdata-mcp).
sed "s/__VERSION__/$VERSION/g" "$PKG/Info.plist.template" > "$APP/Contents/Info.plist"

echo "done → $APP"
echo "  bundle binary: $APP/Contents/MacOS/$APP_NAME"
echo "next: sh scripts/sign-and-notarize.sh   (needs an Apple Developer ID)"
