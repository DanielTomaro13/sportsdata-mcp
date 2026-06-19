#!/bin/sh
# Assemble sportsdata-mcp.app around the PyInstaller onedir bundle (commerce Phase 3).
#
#   sh scripts/build-installer.sh      # produces dist/sportsdata-mcp/ (the onedir)
#   sh scripts/make-macos-app.sh       # wraps it as dist/sportsdata-mcp.app
#
# The bundled MCP binary ends up at
#   sportsdata-mcp.app/Contents/Resources/sportsdata-mcp/sportsdata-mcp
# which is exactly the path `sportsdata-mcp setup` writes into the AI-client config.
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
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 1. the bundled runtime + binary go under Resources/sportsdata-mcp/
cp -R "$ONEDIR" "$APP/Contents/Resources/$APP_NAME"

# 2. the launcher is the bundle's main executable
cp "$PKG/launcher.sh" "$APP/Contents/MacOS/$APP_NAME-launcher"
chmod +x "$APP/Contents/MacOS/$APP_NAME-launcher"

# 3. Info.plist with the version substituted in
sed "s/__VERSION__/$VERSION/g" "$PKG/Info.plist.template" > "$APP/Contents/Info.plist"

echo "done → $APP"
echo "next: sh scripts/sign-and-notarize.sh   (needs an Apple Developer ID)"
