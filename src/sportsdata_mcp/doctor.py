"""`sportsdata-mcp doctor` — per-provider reachability + auth + REST contract check.

For every enabled group, doctor mints any required auth token and probes one
representative endpoint, reporting OK / FAIL / SKIP. Because REST providers have
no hash-style drift detector, this is the intended periodic check: a previously
working endpoint that now 404s (path drift) surfaces here as a FAIL and a nonzero
exit code.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx

from . import dates
from .auth.none import NullAuthProvider
from .config import Config
from .errors import PersistedQueryNotFoundError, ToolError
from .http_client import HTTPClient
from .registry import _build_body, _build_headers, _build_query, _interpolate_path
from .spec import AuthNone, Dispatcher, Endpoint, Spec
from .spec_loader import expand_wildcard_groups

Echo = Callable[[str], None]

_GREEN = "\033[32m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


@dataclass
class _Result:
    ok: int = 0
    failed: int = 0
    skipped: int = 0


def _full_url(provider, base: str, url: str) -> str:
    return provider.base_urls[base].rstrip("/") + url


def _payload_shape(body: object) -> str:
    if isinstance(body, dict):
        return f"dict, {len(body)} keys"
    if isinstance(body, list):
        return f"list, {len(body)} items"
    return type(body).__name__


def _default_args(ep: Endpoint) -> dict:
    """The param defaults the engine would apply at call time (FastMCP fills these
    from the tool signature). Doctor must seed them too, or a probe omits a
    defaulted-but-API-required param (e.g. TAB's `jurisdiction`) and 400s."""
    return {p.name: p.default for p in ep.params if p.default is not None}


def _pick_endpoint_probe(endpoints: list[Endpoint]) -> tuple[Endpoint | None, dict | None]:
    """Choose a representative endpoint + args. Prefer an example, then a no-required-param call.
    In both cases seed the param defaults so the probe matches a real call."""
    in_group = endpoints
    for ep in in_group:
        if ep.examples:
            # Render {{today}} so a probe asks for a window the provider still serves.
            # Sportsbet 400s on a racing date five weeks old, which is how a healthy
            # provider spent a night reported as drift.
            return ep, dates.render_params({**_default_args(ep), **ep.examples[0].params})
    for ep in in_group:
        if not any(p.required for p in ep.params):
            return ep, _default_args(ep)
    # All remaining endpoints need params we can't synthesise safely.
    return (in_group[0], None) if in_group else (None, None)


def _zero_variable_op(spec: Spec):
    """A verified GraphQL op with no required variables — safe to probe blind."""
    for op in spec.graphql.operations if spec.graphql else []:
        if op.verified and not op.variables.strip():
            return op
    return None


def _key_is_missing(http: HTTPClient, provider, auth_key: str) -> bool:
    """Does this provider need a user-supplied key that is not configured here?

    Both halves matter. `requires_user_key` alone is not enough — a developer WITH a key
    should still see a real failure. And an unconfigured optional-auth provider that works
    anonymously (ESPN Fantasy) must not be excused, because for it a 401 IS drift.
    """
    if not provider.requires_user_key:
        return False
    try:
        return isinstance(http._auth_provider(auth_key), NullAuthProvider)
    except Exception:  # noqa: BLE001 - a mint failure means unconfigured for our purposes
        return True


async def _probe_endpoint(http: HTTPClient, provider, ep: Endpoint, args: dict, echo: Echo) -> str:
    url = _interpolate_path(ep, args)
    echo(f"[{provider.id}/{ep.group}] {ep.method} {_full_url(provider, ep.base, url)}")
    try:
        r = await http.request(
            method=ep.method,
            base=ep.base,
            url=url,
            params=_build_query(ep, args),
            headers=_build_headers(ep, args),
            json_body=_build_body(ep, args),
            auth_key=ep.auth,
        )
    except httpx.HTTPError as e:
        echo(f"  {_RED}→ FAIL: transport error: {e}{_RESET}")
        return "fail"
    except ToolError as e:
        # e.g. AuthMissingError when a required secret isn't set — report, don't crash.
        if provider.requires_user_key:
            echo(f"  {_DIM}→ SKIP: no key configured for this provider{_RESET}")
            return "skip"
        echo(f"  {_RED}→ FAIL: {e.message}{_RESET}")
        return "fail"
    size = len(r.content)
    no_key = _key_is_missing(http, provider, ep.auth)
    if r.status_code >= 400:
        # A BYO-key provider refusing an unauthenticated probe is CORRECT behaviour, not
        # drift. Scheduled drift runs hold no keys, so failing here just trains everyone
        # to ignore a red drift check. Any OTHER status is still a genuine signal —
        # a 404 means the path moved whether or not we hold a key.
        if no_key and 400 <= r.status_code < 500:
            # ANY 4xx, not just 401/403. Providers spell "you did not authenticate"
            # differently — Entity Sport returns 400 "Invalid request" when the token
            # param is absent entirely — and for a provider we hold no key for, a 404 is
            # genuinely indistinguishable from an auth refusal anyway. Pretending we can
            # tell them apart would produce confident wrong verdicts; real coverage for
            # these providers requires a key, i.e. the operator's local run.
            echo(f"  {_DIM}→ SKIP: HTTP {r.status_code} — no key configured; "
                 f"cannot distinguish refusal from drift without one{_RESET}")
            return "skip"
        echo(f"  {_RED}→ FAIL: HTTP {r.status_code} ({size} bytes){_RESET}")
        return "fail"

    # CSV is a first-class response format (football-data.co.uk publishes only CSV), so
    # text/csv here is success, not the bot challenge it looks like to a JSON-only probe.
    if ep.response_format == "csv":
        ctype = r.headers.get("content-type", "")
        if "csv" not in ctype and "text" not in ctype:
            echo(f"  {_RED}→ FAIL: expected CSV, got {ctype or 'unknown'}{_RESET}")
            return "fail"
        rows = r.text.count("\n")
        if rows < 2:
            echo(f"  {_RED}→ FAIL: CSV had {rows} line(s) — expected a dataset{_RESET}")
            return "fail"
        echo(f"  {_GREEN}→ {r.status_code} OK (csv, ~{rows} rows, {size // 1024 or 1} KB){_RESET}")
        return "ok"

    # Parse regardless of content-type (some APIs serve JSON as text/plain); a parse
    # failure on a non-JSON type is the real bot-challenge signal.
    try:
        body = r.json()
    except ValueError:
        ctype = r.headers.get("content-type", "")
        if "json" not in ctype:
            echo(f"  {_RED}→ FAIL: non-JSON ({ctype or 'unknown'}) — likely a bot challenge{_RESET}")
        else:
            echo(f"  {_RED}→ FAIL: JSON content-type but body did not parse{_RESET}")
        return "fail"

    # Four providers report failures INSIDE a 200. Without this, doctor reported
    # "✓ passed" for api-tennis, cricketdata and iSportsAPI while every one of them was
    # returning an auth-error body — a false PASS, which is worse than a false failure
    # because it hides real breakage behind a green check.
    try:
        http._raise_on_error_signal(body)
    except ToolError as e:
        if no_key:
            echo(f"  {_DIM}→ SKIP: 200 carrying an auth error — expected, no key configured{_RESET}")
            return "skip"
        echo(f"  {_RED}→ FAIL: {e.message}{_RESET}")
        return "fail"

    echo(f"  {_GREEN}→ {r.status_code} OK ({_payload_shape(body)}, {size // 1024 or 1} KB){_RESET}")
    return "ok"


async def _probe_graphql(http: HTTPClient, spec: Spec, disp: Dispatcher, echo: Echo) -> str:
    op = _zero_variable_op(spec)
    n_ops = len(spec.graphql.operations) if spec.graphql else 0
    if op is None:
        echo(f"[{spec.provider.id}/{disp.group}] dispatcher registered ({n_ops} ops via {disp.catalog_resource})")
        echo(f"  {_DIM}→ SKIP: no zero-variable verified op to probe{_RESET}")
        return "skip"
    echo(f"[{spec.provider.id}/{disp.group}] {disp.method} {_full_url(spec.provider, disp.base or 'default', disp.endpoint or '')} ({op.name})")
    from .registry import make_dispatcher_handler

    handler = make_dispatcher_handler(disp, spec, http)
    try:
        body = await handler(operation=op.name, variables={})
    except PersistedQueryNotFoundError as e:
        echo(f"  {_YELLOW}→ WARN: {e.message}{_RESET}")
        return "skip"
    except (ToolError, httpx.HTTPError) as e:
        echo(f"  {_RED}→ FAIL: {e}{_RESET}")
        return "fail"
    echo(f"  {_GREEN}→ 200 OK ({_payload_shape(body)}){_RESET}")
    return "ok"


async def _run_provider(spec: Spec, enabled: set[str], cfg: Config, echo: Echo, res: _Result) -> None:
    provider = spec.provider
    prov_groups = {t.group for t in spec.all_tools()} & enabled
    if not prov_groups:
        return

    http = HTTPClient(provider, cfg)
    try:
        # 1. Mint every non-none auth key used by an enabled tool.
        auth_keys: set[str] = set()
        for tool in spec.all_tools():
            if tool.group in enabled:
                spec_auth = provider.auth.get(tool.auth)
                if spec_auth is not None and not isinstance(spec_auth, AuthNone):
                    auth_keys.add(tool.auth)
        for key in sorted(auth_keys):
            echo(f"[{provider.id}/auth:{key}] minting credential")
            try:
                # Optional schemes are valid unconfigured — anonymous mode is the
                # public tier, so skip rather than fail. Two shapes resolve that way:
                # a signer that constructs inactive (Kalshi RSA), and an `optional`
                # spec that collapses to the null provider (ESPN Fantasy's cookie,
                # optional OAuth).
                ap = http._auth_provider(key)
                if isinstance(ap, NullAuthProvider) or getattr(ap, "active", True) is False:
                    echo(f"  {_DIM}→ SKIP: optional auth not configured — running anonymous{_RESET}")
                    res.skipped += 1
                    continue
                name, _value = await http.mint_auth(key)
                echo(f"  {_GREEN}→ token acquired ({name}){_RESET}")
                res.ok += 1
            except Exception as e:  # noqa: BLE001 — doctor reports any mint failure
                # A BYO-key provider with REQUIRED auth (DataGolf, X) raises here rather
                # than collapsing to the null provider. Not holding a key is not drift,
                # and reporting it as such is why both sat on the known-blocked list —
                # which permanently blinds the check to their REAL drift. Skipping here
                # instead keeps that list for genuinely blocked providers.
                if provider.requires_user_key:
                    echo(f"  {_DIM}→ SKIP: no key configured for this provider{_RESET}")
                    res.skipped += 1
                else:
                    echo(f"  {_RED}→ FAIL: {e}{_RESET}")
                    res.failed += 1

        # 2. One representative probe per enabled group.
        for group in sorted(prov_groups):
            eps = [e for e in spec.endpoints if e.group == group]
            disps = [d for d in spec.dispatchers if d.group == group]
            if eps:
                ep, args = _pick_endpoint_probe(eps)
                if ep is None or args is None:
                    name = ep.name if ep else group
                    echo(f"[{provider.id}/{group}] {name}")
                    echo(f"  {_DIM}→ SKIP: needs params with no example to probe safely{_RESET}")
                    res.skipped += 1
                    continue
                outcome = await _probe_endpoint(http, provider, ep, args, echo)
            else:
                outcome = "skip"
                for disp in disps:
                    if disp.kind in ("graphql_persisted", "graphql_query"):
                        outcome = await _probe_graphql(http, spec, disp, echo)
                    else:
                        n = len(disp.operations)
                        echo(f"[{provider.id}/{group}] dispatcher registered ({n} ops via {disp.catalog_resource})")
                        echo(f"  {_DIM}→ SKIP: templated ops need resource ids; not probed{_RESET}")
                        outcome = "skip"
            res.ok += outcome == "ok"
            res.failed += outcome == "fail"
            res.skipped += outcome == "skip"
    finally:
        await http.aclose()


async def run_doctor(cfg: Config, specs: list[Spec], echo: Echo) -> bool:
    """Probe every enabled group. Returns True when no check failed."""
    enabled = set(expand_wildcard_groups(cfg.enabled_groups, specs))
    if not enabled:
        echo("No groups enabled — nothing to check. Set `enabled_groups` in your config.")
        return True
    echo(f"Config: {cfg.config_path or '(defaults)'}")
    echo(f"Enabled groups: {', '.join(sorted(enabled))}\n")

    res = _Result()
    for spec in specs:
        await _run_provider(spec, enabled, cfg, echo, res)

    echo("")
    summary = f"{res.ok} ok, {res.failed} failed, {res.skipped} skipped"
    if res.failed:
        echo(f"{_RED}✗ doctor found problems ({summary}).{_RESET}")
        return False
    echo(f"{_GREEN}✓ doctor passed ({summary}).{_RESET}")
    return True
