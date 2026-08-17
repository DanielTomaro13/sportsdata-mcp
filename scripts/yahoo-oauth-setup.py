#!/usr/bin/env python3
"""One-time Yahoo Fantasy OAuth setup — run locally, get a refresh token.

    python3 scripts/yahoo-oauth-setup.py

Yahoo is the only major fantasy platform with a sanctioned write API, but every endpoint
requires OAuth — even game metadata returns 401 unauthenticated. So nothing can be built
or verified against it until a token exists, and only the account holder can create one.

This script walks that once:

    1. you paste your app's client id and secret (secret is not echoed)
    2. it prints an authorise URL — open it, approve, and Yahoo redirects you
    3. you paste back the `code` from the redirected URL
    4. it exchanges that for a REFRESH TOKEN and prints the env vars to set

The refresh token is long-lived: once set, the engine mints access tokens silently and
the agent runs a whole season without you. That is what makes Yahoo an L3 platform.

NOTHING HERE LEAVES YOUR MACHINE except the two calls to Yahoo's own OAuth endpoints.
The secret and the token are printed to YOUR terminal — do not paste them into a chat.

FIRST, REGISTER AN APP
----------------------
https://developer.yahoo.com/apps/create/

  Application Type   Web Application  (NOT "Installed Application")
  Redirect URI       https://localhost:8080  — any https URL you control works; you
                     never have to run a server there, you just copy the code out of
                     the address bar
  API Permissions    tick **Fantasy Sports** → **Read/Write**
                     (Read-only will make every write fail later with a 401)
"""

from __future__ import annotations

import getpass
import json
import sys
import urllib.parse

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("pip install httpx")

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def main() -> int:
    print(__doc__)
    print("─" * 70)

    client_id = input("\nClient ID (Consumer Key): ").strip()
    client_secret = getpass.getpass("Client Secret (not echoed): ").strip()
    redirect_uri = input("Redirect URI as registered [https://localhost:8080]: ").strip() or "https://localhost:8080"

    if not client_id or not client_secret:
        sys.exit("both the client id and secret are required")

    # PREFLIGHT. Yahoo only lets an app request `fspt-w` if the registration carries the
    # Fantasy Sports permission, so asking for it here answers "is this app configured
    # correctly?" in one request — before putting anyone through a consent dance that
    # would succeed and then 401 on every fantasy call.
    if not _scope_allowed(client_id, redirect_uri, "fspt-w"):
        print(
            "\n❌ This app cannot request the Fantasy Sports scope — Yahoo rejects\n"
            "   `fspt-w` as invalid_scope, which means the permission is not on the\n"
            "   app registration. Consent would succeed and every fantasy call would\n"
            "   still 401, so stopping here.\n\n"
            "   At https://developer.yahoo.com/apps/ open the app and check:\n\n"
            "     Application Type   MUST be 'Web Application'. The Fantasy Sports\n"
            "                        permission is NOT offered for 'Installed Application',\n"
            "                        and that is the usual cause — the checkbox is simply\n"
            "                        absent rather than unticked.\n"
            "     OAuth Client Type  Confidential Client\n"
            "     API Permissions    Fantasy Sports → Read/Write\n\n"
            "   If Fantasy Sports does not appear in the permissions list at all, the\n"
            "   app type is wrong — create a new Web Application rather than editing.\n\n"
            "   Re-run this script to re-check; it takes one request and no consent.\n",
            file=sys.stderr,
        )
        return 2
    print("\n✓ preflight: the app can request Fantasy Sports read/write")

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "language": "en-us",
            # Ask explicitly, so a misconfigured app fails at consent rather than later.
            "scope": "fspt-w",
        }
    )
    print("\n" + "─" * 70)
    print("1. Open this URL and approve access:\n")
    print(f"   {AUTH_URL}?{params}\n")
    print("2. Yahoo will redirect you to a page that probably fails to load. That is fine —")
    print("   the part that matters is in the ADDRESS BAR:\n")
    print(f"   {redirect_uri}/?code=XXXXXXXX\n")
    print("3. Copy the value after `code=` and paste it below.")
    print("─" * 70)

    code = input("\nAuthorisation code: ").strip()
    if not code:
        sys.exit("no code supplied")

    with httpx.Client(timeout=30) as c:
        r = c.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code": code,
                "grant_type": "authorization_code",
            },
        )
    if r.status_code != 200:
        # The two usual causes are worth naming rather than dumping a raw error.
        print(f"\ntoken exchange failed (HTTP {r.status_code}): {r.text[:300]}", file=sys.stderr)
        print(
            "\nCommon causes:\n"
            "  * the code is single-use and expires in minutes — start again from step 1\n"
            "  * the redirect URI must match the app registration EXACTLY, "
            "including the scheme and any trailing slash",
            file=sys.stderr,
        )
        return 1

    tok = r.json()
    print("\n✅ Got a refresh token. Add these to your shell profile:\n")
    print(f"  export YAHOO_CLIENT_ID='{client_id}'")
    print("  export YAHOO_CLIENT_SECRET='<the secret you typed above>'")
    print(f"  export YAHOO_REFRESH_TOKEN='{tok['refresh_token']}'")
    print(f"\n(access token expires in {tok.get('expires_in', '?')}s; the refresh token is the durable one)")

    # Prove it works end to end, and show the response SHAPE — which is the thing worth
    # sharing, because Yahoo's JSON is unusual and the provider must be written for it.
    print("\n─── verifying, and capturing the response shape ───")
    with httpx.Client(timeout=30, headers={"Authorization": f"Bearer {tok['access_token']}"}) as c:
        r = c.get("https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games?format=json")
        print(f"users;use_login=1/games -> HTTP {r.status_code}")
        if r.status_code == 200:
            body = r.json()
            print("\nThis is SAFE TO SHARE — it is structure, not credentials:")
            print(json.dumps(_shape(body), indent=1)[:2000])
        elif "additional_authorization_required" in r.text:
            # The single most likely failure, and the raw message does not say why.
            # The token is VALID — it simply carries no Fantasy Sports scope, because
            # Yahoo grants scopes from the app registration at consent time.
            print(
                "\n❌ The token is valid, but the app has no Fantasy Sports permission.\n\n"
                "   Yahoo attaches scopes at CONSENT time from the app registration, so\n"
                "   adding the permission now does NOT upgrade the token you just minted.\n\n"
                "   Fix, in order:\n"
                "     1. https://developer.yahoo.com/apps/ → your app → API Permissions\n"
                "        tick **Fantasy Sports** and choose **Read/Write**, then save\n"
                "     2. revoke the old grant so the exposed token dies:\n"
                "        https://login.yahoo.com/account/security/app-passwords\n"
                "        (Account Info → Apps connected to your account → remove it)\n"
                "     3. run this script again — the new consent carries the scope\n",
                file=sys.stderr,
            )
            return 2
        else:
            print(r.text[:300], file=sys.stderr)
            return 1
    return 0


def _scope_allowed(client_id: str, redirect_uri: str, scope: str) -> bool:
    """Does Yahoo let this app request `scope`?

    The authorise endpoint 302s to an error URL carrying `error=invalid_scope` when the
    app registration does not include the permission. Only the CLIENT ID is used — a
    public identifier that ships in every OAuth redirect — so this reveals nothing.
    """
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as c:
            r = c.get(
                AUTH_URL,
                params={
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "response_type": "code",
                    "scope": scope,
                },
            )
        return "invalid_scope" not in r.headers.get("location", "")
    except httpx.HTTPError:
        return True  # a network blip must not block a correctly configured app


def _shape(value, depth: int = 0):
    """Describe structure, not content. Yahoo's JSON mixes arrays and numeric-keyed
    objects, so the SHAPE is the genuinely useful thing to look at."""
    if depth > 6:
        return "…"
    if isinstance(value, dict):
        return {k: _shape(v, depth + 1) for k, v in list(value.items())[:12]}
    if isinstance(value, list):
        return [_shape(value[0], depth + 1), f"…{len(value)} items"] if value else []
    if isinstance(value, str):
        return f"<str:{len(value)}>" if len(value) > 24 else value
    return value


if __name__ == "__main__":
    raise SystemExit(main())
