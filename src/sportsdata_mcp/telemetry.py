"""Usage and quality signals — local always, remote only if you say so.

WHAT THIS IS FOR
----------------
Two different questions get conflated under "analytics":

  1. "Is anyone using this?"   — answered by `scripts/metrics.py`, from PyPI and GitHub,
                                 without touching a single user's machine.
  2. "Does it actually WORK for them?" — needs a signal from where the tools run. That
                                 is this file.

Question 2 is the one that changes the code. A tool that 404s for everyone, a provider
whose upstream started returning empty arrays, a spec whose required parameter is wrong —
none of that shows up in a download count. It shows up here, as an error rate.

THE DEAL
--------
* **Local recording is always on.** It costs nothing, never leaves the machine, and gives
  the user something they own: `sportsdata-mcp stats` shows their own error rates and
  slowest providers. If you never opt in, this file is a private diagnostic tool for you.
* **Sending anything requires TWO explicit acts**: setting `SPORTSDATA_TELEMETRY=1` and
  configuring an endpoint. Neither has a default that transmits. There is no "anonymous
  by default", no first-run prompt that defaults to yes, and no way for a config file
  shipped by someone else to silently turn it on without the env var.
* **`sportsdata-mcp telemetry --show-payload` prints exactly what would be sent**, so the
  claims below are checkable rather than promises.

WHAT IS NEVER COLLECTED — and why each one matters
--------------------------------------------------
* **Tool arguments.** This is the important one. Arguments here are not innocuous: an
  ESPN Fantasy league id identifies a specific league and its members, a Sleeper username
  IS a username, and a search string is whatever the person typed. Recording tool names
  without arguments is the line between "which tools get used" and "what are they asking
  about".
* **Response bodies.** Ever. Not even sizes beyond a coarse "was it empty".
* **API keys, tokens, env var VALUES.** Only the NAMES of providers configured, and only
  as a count.
* **Paths, hostnames, usernames, IP addresses.** The payload has no field for any of
  them. The install id is a random UUID with nothing derived from the machine.

WHAT IS COLLECTED WHEN YOU OPT IN
---------------------------------
Per tool call: the tool name, its provider, whether it succeeded, the error CODE if not
(`AUTH_REQUIRED`, `UPSTREAM_TIMEOUT`, …), a latency bucket, and whether the result was
empty. Per session: server version, Python minor version, OS name, how many providers are
enabled, and a random install id so repeat sessions can be told from new installs.

That is enough to answer "is tool X broken for everyone or just me" and nothing else.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger("sportsdata_mcp.telemetry")

# Coarse enough that a latency cannot fingerprint a network, fine enough to see a
# provider get slow.
_LATENCY_BUCKETS = ((0.25, "<250ms"), (1.0, "<1s"), (3.0, "<3s"), (10.0, "<10s"))

# Per-tool counters are bounded by the tool count (762), but feedback is free text a
# caller can send any number of times. An HTTP deployment running for weeks with a model
# that likes calling `sportsdata_feedback` would grow without limit and eventually POST a
# multi-megabyte payload; 5,000 notes measured at 2.96 MB. Keep the most recent.
_MAX_FEEDBACK = 200


def _bucket(seconds: float) -> str:
    for threshold, label in _LATENCY_BUCKETS:
        if seconds < threshold:
            return label
    return ">=10s"


def _state_dir() -> Path:
    return Path(os.environ.get("SPORTSDATA_STATE_DIR") or (Path.home() / ".sportsdata-mcp"))


@dataclass
class ToolStats:
    calls: int = 0
    errors: int = 0
    empty: int = 0
    latency: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    codes: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "errors": self.errors,
            "empty": self.empty,
            "latency": dict(self.latency),
            "codes": dict(self.codes),
        }


class Telemetry:
    """Records locally; transmits only under explicit opt-in.

    Thread-safe because FastMCP may serve concurrent calls, and a torn counter would make
    the one number this exists to produce untrustworthy.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tools: dict[str, ToolStats] = defaultdict(ToolStats)
        self._feedback: list[dict] = []
        self._started = time.time()
        self._session_id = uuid.uuid4().hex[:12]

    # ─── recording ──────────────────────────────────────────────────────

    def record(
        self,
        tool: str,
        *,
        ok: bool,
        seconds: float,
        code: str | None = None,
        empty: bool = False,
    ) -> None:
        """Record one tool call. NOTE the signature: there is nowhere to pass arguments
        or a result. That is deliberate — a function that cannot receive them cannot leak
        them, no matter how the call site changes later."""
        with self._lock:
            s = self._tools[tool]
            s.calls += 1
            s.latency[_bucket(seconds)] += 1
            if not ok:
                s.errors += 1
                s.codes[code or "UNKNOWN"] += 1
            if empty:
                s.empty += 1

    def record_feedback(self, tool: str | None, helpful: bool, note: str | None) -> None:
        """Explicit "was this useful" from whoever is driving the tools.

        `note` is free text a user or model chose to send, and it is the ONE field here
        that could contain anything. It is never sent unless telemetry is enabled, it is
        truncated, and the docs say plainly that it is transmitted verbatim.
        """
        with self._lock:
            self._feedback.append(
                {
                    "tool": tool,
                    "helpful": helpful,
                    "note": (note or "")[:500] or None,
                    "at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
                }
            )
            if len(self._feedback) > _MAX_FEEDBACK:
                del self._feedback[:-_MAX_FEEDBACK]

    # ─── reading ────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            tools = {k: v.as_dict() for k, v in self._tools.items()}
            feedback = list(self._feedback)
        calls = sum(t["calls"] for t in tools.values())
        errors = sum(t["errors"] for t in tools.values())
        return {
            "session_id": self._session_id,
            "uptime_seconds": round(time.time() - self._started),
            "calls": calls,
            "errors": errors,
            "error_rate": round(errors / calls, 3) if calls else 0.0,
            "tools": tools,
            "feedback": feedback,
        }

    def payload(self, *, enabled_providers: int = 0) -> dict:
        """Exactly what a flush would transmit. `sportsdata-mcp telemetry --show-payload`
        prints this, so the privacy claims are verifiable rather than asserted."""
        from . import __version__

        snap = self.snapshot()
        return {
            "schema": 1,
            "install_id": install_id(),
            "session_id": snap["session_id"],
            "sent_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "server_version": __version__,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "os": platform.system(),
            "providers_enabled": enabled_providers,
            "uptime_seconds": snap["uptime_seconds"],
            "calls": snap["calls"],
            "errors": snap["errors"],
            "tools": snap["tools"],
            "feedback": snap["feedback"],
        }


# ─── opt-in state ───────────────────────────────────────────────────────


def is_enabled() -> bool:
    """True only if the env var says so. Deliberately NOT readable from the config file:
    a config file can be committed to a repo, shared in a gist, or shipped inside a
    Docker image, and none of those are the user in front of the machine consenting."""
    return os.environ.get("SPORTSDATA_TELEMETRY", "").strip().lower() in {"1", "true", "yes", "on"}


def endpoint() -> str | None:
    """Where a flush would POST. There is NO default — an unset endpoint means local-only
    even with telemetry enabled, so a typo in the env var cannot cause a silent send to
    somewhere unexpected."""
    return os.environ.get("SPORTSDATA_TELEMETRY_ENDPOINT") or None


def install_id() -> str:
    """A random UUID, generated once and stored locally.

    Nothing is derived from the machine — not the hostname, not the MAC, not a hash of
    anything. Its only job is telling "one install, forty sessions" apart from "forty
    installs". Delete the file to become a new install; there is no way to link the two.
    """
    path = _state_dir() / "install-id"
    try:
        if path.exists():
            got = path.read_text().strip()
            if got:
                return got
        new = uuid.uuid4().hex
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new + "\n")
        return new
    except OSError:
        # A read-only home is not a reason to fail a tool call.
        return "ephemeral-" + uuid.uuid4().hex[:8]


async def flush(tel: Telemetry, *, enabled_providers: int = 0) -> bool:
    """POST the payload if — and only if — both opt-in conditions hold.

    Returns True if something was sent. Never raises: a telemetry failure must not
    surface as a tool failure, because the person did us a favour by enabling it.
    """
    if not is_enabled():
        return False
    url = endpoint()
    if not url:
        log.debug("telemetry enabled but no endpoint configured — staying local")
        return False
    payload = tel.payload(enabled_providers=enabled_providers)
    if not payload["calls"] and not payload["feedback"]:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
        log.debug("telemetry flushed: %s", r.status_code)
        return 200 <= r.status_code < 300
    except Exception as e:  # noqa: BLE001 - never let telemetry break a session
        log.debug("telemetry flush failed (ignored): %s", e)
        return False


# ─── process-wide instance ──────────────────────────────────────────────

_TELEMETRY = Telemetry()


def get() -> Telemetry:
    return _TELEMETRY


def save_local(tel: Telemetry) -> Path | None:
    """Persist the session's counters so `sportsdata-mcp stats` can show more than the
    current process. Local only — this file is never uploaded, whatever the settings."""
    path = _state_dir() / "stats.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        history = []
        if path.exists():
            history = json.loads(path.read_text()).get("sessions", [])
        snap = tel.snapshot()
        if not snap["calls"]:
            return None
        history.append({"ended_at": datetime.now(tz=UTC).isoformat(timespec="seconds"), **snap})
        path.write_text(json.dumps({"sessions": history[-50:]}, indent=2))
        return path
    except (OSError, json.JSONDecodeError):
        return None


def load_local() -> list[dict]:
    path = _state_dir() / "stats.json"
    try:
        return json.loads(path.read_text()).get("sessions", [])
    except (OSError, json.JSONDecodeError):
        return []
