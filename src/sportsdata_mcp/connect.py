"""`sportsdata-mcp connect` — get a provider working without touching a terminal cookie.

THE PROBLEM THIS SOLVES
-----------------------
Most providers here need nothing. A handful need a credential, and the instructions for
those were, honestly, developer instructions: "open devtools, Application, Cookies,
copy `pl_profile` and `sessionid`, export them as an environment variable". That is a
reasonable ask of an engineer and an unreasonable one of everybody else — and every step
is a chance to paste the wrong value, or to paste it somewhere it should not go.

So where a credential already exists on this machine, we read it rather than asking:

    sportsdata-mcp connect          # what can be connected, and what is already done
    sportsdata-mcp connect fpl      # connect one provider

For a cookie provider the wizard reads the cookie straight out of the local browser,
verifies it with a real API call, and writes it to the user's private config. The user
clicks "Allow" on one macOS Keychain prompt and is done.

WHAT IT WILL AND WILL NOT TOUCH
-------------------------------
* It reads cookies for **one host**, named in the provider's spec — never the cookie jar.
  `connect fpl` can see `fantasy.premierleague.com` and nothing else.
* It **never prints a credential**. Output says "found", "verified", "saved", and shows
  a fingerprint, never a value.
* It writes to `~/.config/sportsdata-mcp/config.yaml` with mode 0600, creating the
  directory 0700. That file is outside every git repo by design.
* It **verifies before saving**. A cookie that does not actually work is not written, so
  "connected" means the provider answered, not that a string was copied.
* Manual paste is always available (`--manual`) and is the only path when the browser
  route is unavailable.

WHY BROWSER-READING IS THE SAFER OPTION HERE
--------------------------------------------
The alternative is a human copying a session credential through a clipboard, a terminal
and possibly a chat window. Reading it locally, scoped to one host, and never echoing it
is a shorter and less leaky path than the manual one it replaces.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# ─── what each connectable provider needs ───────────────────────────────


@dataclass(frozen=True)
class Connector:
    """One provider's recipe: which cookies, from which host, verified how."""

    provider: str
    label: str
    env_var: str
    #: Cookie names to collect, in the order they should be sent.
    cookie_names: tuple[str, ...]
    #: The ONLY host whose cookies this connector may read.
    cookie_host: str
    #: A GET that returns 2xx only when the credential works.
    verify_url: str
    manual_hint: str
    #: Extra guidance shown before a manual paste.
    login_url: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)


CONNECTORS: dict[str, Connector] = {
    "fpl": Connector(
        provider="fpl",
        label="Fantasy Premier League",
        env_var="FPL_SESSION_COOKIE",
        cookie_names=("pl_profile", "sessionid", "csrftoken"),
        cookie_host="fantasy.premierleague.com",
        # /me/ returns {"player": null} when signed out and a player object when not,
        # so a 200 alone proves nothing — the verifier checks the body.
        verify_url="https://fantasy.premierleague.com/api/me/",
        login_url="https://fantasy.premierleague.com/",
        manual_hint="devtools → Application → Cookies → fantasy.premierleague.com",
        notes=(
            (
                "`csrftoken` is collected because FPL's write endpoints require it as an "
                "X-CSRFToken header. Reads work without it."
            ),
        ),
    ),
    "espnfantasy": Connector(
        provider="espnfantasy",
        label="ESPN Fantasy (private leagues)",
        env_var="ESPN_FANTASY_COOKIE",
        cookie_names=("espn_s2", "SWID"),
        cookie_host="espn.com",
        verify_url="",  # needs a league id, so it cannot be verified generically
        login_url="https://www.espn.com/fantasy/",
        manual_hint="devtools → Application → Cookies → espn.com",
        notes=("Only needed for PRIVATE leagues; public ones work with no credential.",),
    ),
}


# ─── reading one host's cookies from the local browser ──────────────────


def _chrome_cookie_db() -> Path | None:
    for rel in (
        "Library/Application Support/Google/Chrome/Default/Cookies",
        "Library/Application Support/Chromium/Default/Cookies",
        "Library/Application Support/BraveSoftware/Brave-Browser/Default/Cookies",
    ):
        p = Path.home() / rel
        if p.exists():
            return p
    return None


def _chrome_key() -> bytes | None:
    """The AES key Chrome derives from a Keychain secret.

    Reading it triggers one macOS permission prompt — which is the whole user-facing
    cost of this feature, and is a prompt the user can decline.
    """
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    from cryptography.hazmat.primitives.hashes import SHA1
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=SHA1(), length=16, salt=b"saltysalt", iterations=1003)
    return kdf.derive(out.stdout.strip().encode())


def _decrypt(value: bytes, key: bytes) -> str:
    """Chrome on macOS: 'v10' prefix, AES-128-CBC, fixed IV of 16 spaces."""
    if not value.startswith(b"v10"):
        return value.decode(errors="ignore")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plain = dec.update(value[3:]) + dec.finalize()
    if plain and plain[-1] <= 16:  # strip PKCS#7 padding
        plain = plain[: -plain[-1]]
    # Newer Chrome prefixes a 32-byte SHA256 of the domain before the value.
    text = plain.decode(errors="ignore")
    return text[32:] if len(text) > 32 and not text[:32].isprintable() else text


def read_browser_cookies(host: str, names: tuple[str, ...]) -> dict[str, str]:
    """Cookies for ONE host. Never reads or returns anything for another domain."""
    db = _chrome_cookie_db()
    if db is None:
        return {}
    key = _chrome_key()
    if key is None:
        return {}
    # Chrome holds the DB locked while running; work on a copy.
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "cookies.sqlite"
        shutil.copy2(db, copy)
        con = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        try:
            placeholders = ",".join("?" * len(names))
            rows = con.execute(
                "SELECT name, encrypted_value FROM cookies "
                f"WHERE host_key LIKE ? AND name IN ({placeholders})",
                (f"%{host}", *names),
            ).fetchall()
        finally:
            con.close()
    return {n: v for n, blob in rows if (v := _decrypt(blob, key))}


# ─── verification, storage ──────────────────────────────────────────────


def verify(conn: Connector, cookie_header: str) -> tuple[bool, str]:
    """Prove the credential WORKS before storing it. 'Connected' should mean the
    provider answered, not that a string was copied into a file."""
    if not conn.verify_url:
        return True, "stored without verification (this provider has no generic check)"
    try:
        r = httpx.get(
            conn.verify_url,
            headers={"Cookie": cookie_header, "User-Agent": "sportsdata-mcp connect"},
            timeout=20,
        )
    except httpx.HTTPError as e:
        return False, f"could not reach {conn.label}: {type(e).__name__}"
    if r.status_code != 200:
        return False, f"{conn.label} rejected it (HTTP {r.status_code})"
    # FPL answers 200 with {"player": null} when signed out — a status check alone
    # would call an expired cookie "connected".
    try:
        body = r.json()
    except ValueError:
        return True, "accepted"
    if isinstance(body, dict) and body.get("player") is None and "player" in body:
        return False, "the cookie is present but signed out — log in again and retry"
    return True, "verified against a live call"


def config_path() -> Path:
    return Path.home() / ".config" / "sportsdata-mcp" / "config.yaml"


def save_secret(env_var: str, value: str) -> Path:
    """Write into the user's private config, 0600 in a 0700 directory.

    Chosen over an environment variable deliberately: an env var has to be re-exported
    per shell and tends to end up in a dotfile that gets committed. This path is outside
    every repo, and the loader already reads it.
    """
    import yaml

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = {}
    if path.exists():
        data = yaml.safe_load(path.read_text()) or {}
    data.setdefault("secrets", {})[env_var] = value
    tmp = path.with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)
    return path


def fingerprint(value: str) -> str:
    """Enough to tell two credentials apart in a log; not enough to use one."""
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()[:8]


def status() -> list[tuple[str, str, bool]]:
    """(provider, label, connected?) for everything connectable."""
    import yaml

    stored: dict = {}
    p = config_path()
    if p.exists():
        stored = (yaml.safe_load(p.read_text()) or {}).get("secrets", {}) or {}
    out = []
    for c in CONNECTORS.values():
        have = bool(os.environ.get(c.env_var) or stored.get(c.env_var))
        out.append((c.provider, c.label, have))
    return out


def build_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def as_json(obj) -> str:
    return json.dumps(obj, indent=2)


def b64(v: str) -> str:  # small helper kept for symmetry with future connectors
    return base64.b64encode(v.encode()).decode()
