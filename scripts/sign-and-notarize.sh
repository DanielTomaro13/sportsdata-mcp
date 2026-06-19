#!/bin/sh
# Sign, notarize and staple dist/sportsdata-mcp.app → a Gatekeeper-clean DMG (Phase 3).
#
#   sh scripts/build-installer.sh && sh scripts/make-macos-app.sh
#   sh scripts/sign-and-notarize.sh
#
# Needs an Apple Developer ID ($99/yr). Set in the environment:
#   APPLE_SIGNING_IDENTITY   "Developer ID Application: Your Name (TEAMID)"
# and ONE notarytool credential set:
#   (a) APPLE_API_KEY_PATH + APPLE_API_KEY_ID + APPLE_API_ISSUER   (App Store Connect API key), or
#   (b) APPLE_ID + APPLE_APP_PASSWORD + APPLE_TEAM_ID              (app-specific password)
# Distribution is DIRECT DOWNLOAD, not the App Store: Developer ID signing + notarization.
set -eu

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_NAME="sportsdata-mcp"
DIST="$REPO/dist"
APP="$DIST/$APP_NAME.app"
ENT="$REPO/packaging/macos/entitlements.plist"
VERSION="$("$REPO/.venv/bin/python" -c 'import sportsdata_mcp; print(sportsdata_mcp.__version__)' 2>/dev/null \
           || python -c 'import sportsdata_mcp; print(sportsdata_mcp.__version__)' 2>/dev/null || echo "0.0.0")"
DMG="$DIST/$APP_NAME-$VERSION-macos.dmg"

if [ ! -d "$APP" ]; then
  echo "error: $APP not found — run build-installer.sh + make-macos-app.sh first" >&2
  exit 1
fi
if [ -z "${APPLE_SIGNING_IDENTITY:-}" ]; then
  echo "APPLE_SIGNING_IDENTITY is not set — get an Apple Developer ID, then:" >&2
  echo "  export APPLE_SIGNING_IDENTITY='Developer ID Application: Your Name (TEAMID)'" >&2
  echo "  + the notarytool credentials (see the header of this script / RELEASE.md)" >&2
  exit 1
fi

# 1. Codesign inside-out (--deep) with the hardened runtime + entitlements so the bundled
#    CPython and its .dylibs pass notarization.
echo "codesigning $APP …"
codesign --force --deep --options runtime --timestamp \
  --entitlements "$ENT" --sign "$APPLE_SIGNING_IDENTITY" "$APP"
codesign --verify --strict --verbose=2 "$APP"

# 2. Package the DMG and sign it too.
echo "building $DMG …"
rm -f "$DMG"
hdiutil create -volname "$APP_NAME" -srcfolder "$APP" -ov -format UDZO "$DMG"
codesign --force --timestamp --sign "$APPLE_SIGNING_IDENTITY" "$DMG"

# 3. Notarize (waits for Apple's verdict) with whichever credential set is present.
echo "submitting to notarytool (a few minutes) …"
if [ -n "${APPLE_API_KEY_PATH:-}" ]; then
  xcrun notarytool submit "$DMG" --key "$APPLE_API_KEY_PATH" \
    --key-id "${APPLE_API_KEY_ID:?set APPLE_API_KEY_ID}" \
    --issuer "${APPLE_API_ISSUER:?set APPLE_API_ISSUER}" --wait
else
  xcrun notarytool submit "$DMG" \
    --apple-id "${APPLE_ID:?set APPLE_ID (or the APPLE_API_* trio)}" \
    --password "${APPLE_APP_PASSWORD:?set APPLE_APP_PASSWORD (an app-specific password)}" \
    --team-id "${APPLE_TEAM_ID:?set APPLE_TEAM_ID}" --wait
fi

# 4. Staple the ticket so it verifies offline, then confirm.
echo "stapling …"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
spctl --assess --type open --context context:primary-signature -v "$DMG" || true

echo "done → $DMG (signed · notarized · stapled)"
