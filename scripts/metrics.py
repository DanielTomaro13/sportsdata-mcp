#!/usr/bin/env python3
"""Adoption metrics for sportsdata-mcp, collected WITHOUT touching a single user.

    python scripts/metrics.py           # human-readable report
    python scripts/metrics.py --json    # machine-readable, for a dashboard or a cron

Everything here comes from public sources about the PACKAGE — PyPI's download logs and
GitHub's own traffic API — so nobody's client phones home, nothing is installed on their
machine, and no configuration of theirs is read. That is the point: the honest first
question is "what can I learn without asking anybody for anything", and the answer turns
out to be most of what you actually want to know.

WHAT THESE NUMBERS ARE NOT
--------------------------
PyPI download counts are NOT users. Every CI run, Docker build, mirror and dependency
resolver counts. A single user with a daily GitHub Action can be a hundred downloads a
month. The report below leans on the figures that survive that:

  * `without_mirrors` downloads      — PyPI's own de-mirrored series
  * unique cloners and unique viewers — GitHub counts these per actor per day
  * installer breakdown               — `pip` vs `uv`; a wall of `bandersnatch` or
                                        `requests` means bots, not people

Treat unique cloners as the closest thing to a floor on real humans, and downloads as a
loose upper bound. The truth is between them, nearer the floor.

WHY NOT JUST ADD TELEMETRY
--------------------------
Because these numbers answer "is anyone using this, and is it growing" already, and that
is the question worth asking first. Opt-in telemetry (`sportsdata_mcp.telemetry`) answers
a different one — "does it actually WORK for them" — and only for people who agree to
send it. The two are complementary; this file is the one that owes nobody an explanation.

GitHub traffic needs auth: the `gh` CLI must be installed and logged in, and traffic data
is only visible to repo admins. Without it the report still runs and says so.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

PACKAGE = "sportsdata-mcp"
REPO = "DanielTomaro13/sportsdata-mcp"
UA = "sportsdata-mcp-metrics (+https://github.com/DanielTomaro13/sportsdata-mcp)"


# ─── fetchers ───────────────────────────────────────────────────────────


def _get_json(url: str, attempts: int = 3) -> dict | None:
    """GET with a short retry — pypistats rate-limits an unauthenticated caller easily,
    and this script makes four calls to it back to back."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < attempts - 1:
                time.sleep(2 * (attempt + 1))
                continue
            print(f"  ! {url.split('/')[-1]}: {e}", file=sys.stderr)
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            print(f"  ! {url.split('/')[-1]}: {e}", file=sys.stderr)
            return None
    return None


def _gh(path: str) -> dict | list | None:
    """GitHub API via the `gh` CLI, so we inherit the user's existing auth."""
    try:
        out = subprocess.run(
            ["gh", "api", path],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


# ─── shaping ────────────────────────────────────────────────────────────


def _series_by_day(rows: list[dict], category_filter: str | None = None) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for row in rows:
        if category_filter and row.get("category") != category_filter:
            continue
        out[row["date"]] += row["downloads"]
    return dict(out)


def _today() -> date:
    """PyPI's series is dated in UTC, so window arithmetic must be too — a local-midnight
    "today" shifts every bucket by a day for anyone east of Greenwich."""
    return datetime.now(tz=UTC).date()


def _sum_window(series: dict[str, int], days: int, end: date | None = None) -> int:
    end = end or _today()
    start = end - timedelta(days=days)
    return sum(v for k, v in series.items() if start < date.fromisoformat(k) <= end)


def _top_categories(rows: list[dict], n: int = 5) -> list[tuple[str, int]]:
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        # pypistats reports "null" (the string) when the installer sent no UA detail —
        # which is exactly the bot/mirror traffic worth naming rather than hiding.
        cat = row.get("category")
        totals["unreported" if cat in (None, "null") else cat] += row["downloads"]
    return sorted(totals.items(), key=lambda kv: -kv[1])[:n]


def collect() -> dict:
    data: dict = {"collected_at": datetime.now().astimezone().isoformat(), "package": PACKAGE, "repo": REPO}

    recent = _get_json(f"https://pypistats.org/api/packages/{PACKAGE}/recent")
    if recent:
        data["downloads_recent"] = recent["data"]

    overall = _get_json(f"https://pypistats.org/api/packages/{PACKAGE}/overall?mirrors=false")
    if overall:
        series = _series_by_day(overall["data"])
        data["downloads_without_mirrors"] = {
            "last_7d": _sum_window(series, 7),
            "last_30d": _sum_window(series, 30),
            "prev_30d": _sum_window(series, 30, end=_today() - timedelta(days=30)),
            "series": dict(sorted(series.items())),
        }

    for name, path in (("systems", "system"), ("python_versions", "python_minor")):
        got = _get_json(f"https://pypistats.org/api/packages/{PACKAGE}/{path}")
        if got:
            data[name] = _top_categories(got["data"])

    pypi = _get_json(f"https://pypi.org/pypi/{PACKAGE}/json")
    if pypi:
        data["pypi"] = {"latest": pypi["info"]["version"], "releases": len(pypi["releases"])}

    repo = _gh(f"repos/{REPO}")
    if isinstance(repo, dict):
        data["github"] = {
            "stars": repo.get("stargazers_count"),
            "forks": repo.get("forks_count"),
            "watchers": repo.get("subscribers_count"),
            "open_issues": repo.get("open_issues_count"),
        }
        for name, path in (("clones", "clones"), ("views", "views")):
            got = _gh(f"repos/{REPO}/traffic/{path}")
            if isinstance(got, dict):
                data["github"][name] = {"count": got.get("count"), "uniques": got.get("uniques")}
        refs = _gh(f"repos/{REPO}/traffic/popular/referrers")
        if isinstance(refs, list):
            data["github"]["referrers"] = [
                {"source": r["referrer"], "views": r["count"], "uniques": r["uniques"]} for r in refs[:8]
            ]
    else:
        data["github"] = {"error": "gh CLI unavailable, not authenticated, or not a repo admin"}

    return data


# ─── reporting ──────────────────────────────────────────────────────────


def _trend(now: int, before: int) -> str:
    if not before:
        return "no prior window"
    pct = (now - before) / before * 100
    return f"{pct:+.0f}% vs the previous 30 days"


def report(d: dict) -> str:
    out: list[str] = []
    add = out.append

    add(f"sportsdata-mcp adoption — {d['collected_at'][:16].replace('T', ' ')}")
    add("=" * 62)

    add("\nREACH  (upper bound — CI, mirrors and bots all count as downloads)")
    if r := d.get("downloads_recent"):
        add(f"  PyPI downloads      {r['last_day']:>6} today  {r['last_week']:>6} this week  {r['last_month']:>6} this month")
    if w := d.get("downloads_without_mirrors"):
        add(f"  …without mirrors    {w['last_7d']:>6} 7d     {w['last_30d']:>6} 30d      ({_trend(w['last_30d'], w['prev_30d'])})")
    if p := d.get("pypi"):
        add(f"  Published           v{p['latest']}, {p['releases']} releases")

    add("\nPEOPLE  (closer to a floor — GitHub counts these per actor per day)")
    g = d.get("github", {})
    if err := g.get("error"):
        add(f"  unavailable: {err}")
    else:
        if c := g.get("clones"):
            add(f"  Unique cloners      {c['uniques']:>6} in 14d   ({c['count']} clones)")
        if v := g.get("views"):
            add(f"  Unique visitors     {v['uniques']:>6} in 14d   ({v['count']} views)")
        add(f"  Stars / forks       {g.get('stars', '?'):>6} / {g.get('forks', '?')}")
        if g.get("open_issues") is not None:
            add(f"  Open issues         {g['open_issues']:>6}   ← the only unsolicited signal about quality")

    if refs := g.get("referrers"):
        add("\nWHERE THEY COME FROM")
        for r in refs:
            add(f"  {r['source']:<34} {r['uniques']:>4} unique  ({r['views']} views)")

    if sys_rows := d.get("systems"):
        add("\nWHAT THEY RUN ON  (a wall of 'null' usually means bots, not people)")
        add("  " + "   ".join(f"{k}: {v}" for k, v in sys_rows))
    if py_rows := d.get("python_versions"):
        add("  " + "   ".join(f"{k if k == 'unreported' else 'py' + k}: {v}" for k, v in py_rows))

    add("\nHOW TO READ THIS")
    add("  Downloads are a LOOSE UPPER BOUND: one user with a daily CI job is ~30/month.")
    add("  Unique cloners are the nearest thing to a floor on real humans.")
    add("  The truth is between them, nearer the floor.")
    add("  Nothing here comes from a user's machine — see docs/TELEMETRY.md for the")
    add("  opt-in signal that does, and what it deliberately does not collect.")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="emit raw JSON instead of a report")
    args = ap.parse_args()

    data = collect()
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(report(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
