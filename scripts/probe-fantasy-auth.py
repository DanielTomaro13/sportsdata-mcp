#!/usr/bin/env python3
"""Probe the AUTHENTICATED fantasy endpoints, on your machine, and print only shapes.

    python3 scripts/probe-fantasy-auth.py fpl
    python3 scripts/probe-fantasy-auth.py espn --league 123456
    python3 scripts/probe-fantasy-auth.py supercoach

WHY THIS EXISTS
---------------
Building write support for a fantasy platform needs to know what its authenticated
endpoints return. That does NOT require anyone else to hold your password. This script
runs locally: the password is typed at a `getpass` prompt (never echoed, never written to
disk, never placed in argv where `ps` would show it), used once against the platform's
own login endpoint, and discarded when the process exits.

WHAT IT PRINTS
--------------
Structure only — key names, types, list lengths, and a redacted sample. Every value that
could be a credential or a personal detail is replaced before printing. The output is
designed to be safe to paste into a chat or an issue; read it before you do, and if
anything below looks wrong, don't.

WHAT IT NEVER DOES
------------------
No writes. Nothing here transfers a player, sets a lineup or changes an account. It is a
read-only reconnaissance tool, and any write support built from what it learns should be
a deliberate, separate, reviewable step.
"""

from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover - dependency guidance
    sys.exit("pip install httpx")

# Anything matching these key names is replaced before printing, wherever it appears.
_SECRET_KEYS = re.compile(
    r"(pass|token|cookie|session|secret|auth|csrf|swid|espn_s2|email|phone|address|"
    r"first_name|last_name|player_first_name|player_last_name|entry_email)",
    re.IGNORECASE,
)


def _redact(value: Any, depth: int = 0) -> Any:
    """Describe a value's SHAPE, replacing anything sensitive or identifying."""
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:40]:
            out[k] = "<redacted>" if _SECRET_KEYS.search(str(k)) else _redact(v, depth + 1)
        if len(value) > 40:
            out["…"] = f"+{len(value) - 40} more keys"
        return out
    if isinstance(value, list):
        if not value:
            return []
        # One representative item plus a count says everything a shape probe needs.
        return [_redact(value[0], depth + 1), f"…{len(value)} items total"]
    if isinstance(value, str):
        return f"<str len={len(value)}>" if len(value) > 40 else value
    return value


def _show(label: str, status: int, body: Any) -> None:
    print(f"\n─── {label}  [HTTP {status}] ───")
    print(json.dumps(_redact(body), indent=1)[:2500])


def probe_fpl() -> None:
    """FPL is the one platform with a plain login POST rather than an SSO dance."""
    email = input("FPL email: ").strip()
    password = getpass.getpass("FPL password (not echoed): ")
    manager_id = input("Your FPL manager id (the number in your team URL): ").strip()

    with httpx.Client(follow_redirects=True, timeout=30) as c:
        c.headers["User-Agent"] = "Mozilla/5.0"
        r = c.post(
            "https://users.premierleague.com/accounts/login/",
            data={
                "login": email,
                "password": password,
                "app": "plfpl-web",
                "redirect_uri": "https://fantasy.premierleague.com/",
            },
        )
        del password  # no longer needed; drop the reference immediately
        if "pl_profile" not in c.cookies and r.status_code >= 400:
            sys.exit(f"login failed (HTTP {r.status_code}) — check the email/password and try again")
        print(f"login ok; cookies set: {sorted(c.cookies.keys())}")

        for label, url in [
            ("me", "https://fantasy.premierleague.com/api/me/"),
            ("my-team", f"https://fantasy.premierleague.com/api/my-team/{manager_id}/"),
        ]:
            resp = c.get(url)
            _show(label, resp.status_code, resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:400])

    print(
        "\nTo use fpl_my_team, put the session cookie in your environment YOURSELF:\n"
        "  export FPL_SESSION_COOKIE='pl_profile=…; sessionid=…'\n"
        "(read it from your browser's devtools — do not paste it into a chat)"
    )


def probe_espn(league: str) -> None:
    """ESPN sits behind Disney OneID, so a scripted password login is not realistic.
    Cookies from a logged-in browser are the practical route."""
    print(
        "ESPN uses Disney OneID — no simple login POST.\n"
        "In a logged-in browser: devtools → Application → Cookies → espn.com,\n"
        "and copy the values of `espn_s2` and `SWID`.\n"
    )
    espn_s2 = getpass.getpass("espn_s2 (not echoed): ").strip()
    swid = getpass.getpass("SWID (not echoed): ").strip()
    year = input("Season year [2026]: ").strip() or "2026"

    with httpx.Client(timeout=30, cookies={"espn_s2": espn_s2, "SWID": swid}) as c:
        c.headers["User-Agent"] = "sportsdata-mcp probe"
        base = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leagues/{league}"
        for label, url in [
            ("league mTeam", f"{base}?view=mTeam"),
            ("roster", f"{base}?view=mRoster"),
            ("transactions", f"{base}?view=mTransactions2"),
            ("settings", f"{base}?view=mSettings"),
        ]:
            resp = c.get(url)
            _show(label, resp.status_code, resp.json() if resp.status_code == 200 else resp.text[:300])


def probe_supercoach() -> None:
    print(
        "SuperCoach sits behind News Corp SSO, which is a multi-step browser flow.\n"
        "The practical route is the same as ESPN: log in, then copy the session cookie\n"
        "from devtools and paste it below. Nothing is echoed.\n"
    )
    cookie = getpass.getpass("SuperCoach Cookie header (not echoed): ").strip()
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        c.headers.update({"Cookie": cookie, "User-Agent": "sportsdata-mcp probe"})
        for label, url in [
            ("classic teams", "https://supercoach.dailytelegraph.com.au/afl/api/classic/teams"),
            ("user", "https://supercoach.dailytelegraph.com.au/afl/api/classic/user"),
        ]:
            resp = c.get(url)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]
            _show(label, resp.status_code, body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("platform", choices=["fpl", "espn", "supercoach"])
    ap.add_argument("--league", help="ESPN league id (required for espn)")
    args = ap.parse_args()

    print(
        "This script prints SHAPES only — names, types and counts, with credentials and\n"
        "personal fields redacted. Read the output before pasting it anywhere.\n"
    )
    if args.platform == "fpl":
        probe_fpl()
    elif args.platform == "espn":
        if not args.league:
            return ap.error("--league is required for espn")
        probe_espn(args.league)
    else:
        probe_supercoach()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
