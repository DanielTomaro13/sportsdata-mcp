"""Command-line interface: serve / list-groups / lint / doctor / refresh-hashes / version."""

from __future__ import annotations

import logging
import os
import sys
from importlib import metadata
from pathlib import Path

import click

from . import __version__
from .config import load_config
from .spec_loader import all_groups, load_all_specs
from .spec_loader import lint as lint_specs


def _version_string() -> str:
    def _v(pkg: str) -> str:
        try:
            return metadata.version(pkg)
        except metadata.PackageNotFoundError:
            return "?"

    return f"sportsdata-mcp {__version__} (FastMCP {_v('fastmcp')}, httpx {_v('httpx')})"


@click.group(invoke_without_command=True)
@click.option("--config", "config_path", type=click.Path(path_type=Path), default=None, help="Path to config YAML.")
@click.option("-v", "--verbose", is_flag=True, help="DEBUG-level logging on stderr.")
@click.pass_context
def cli(ctx: click.Context, config_path: Path | None, verbose: bool) -> None:
    """sportsdata-mcp — an MCP server for sports-data APIs."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not verbose:
        # httpx/httpcore log every request/connection at INFO/DEBUG — too noisy for normal runs.
        for noisy in ("httpx", "httpcore"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    else:
        # hpack dumps every HTTP/2 header, including `:path` — pure noise, and the path
        # carries query-string credentials for the seven providers that authenticate
        # that way. Nobody debugging a provider needs HPACK table internals.
        for noisier in ("hpack", "hpack.hpack", "hpack.table", "h2"):
            logging.getLogger(noisier).setLevel(logging.WARNING)

    # Belt and braces: redact known credential values from EVERY log record regardless of
    # which library emitted it. `-v` is what people turn on when a provider misbehaves,
    # and its output is what they paste into a bug report — httpx logs the fully-composed
    # URL, so without this a query-string API key goes straight into the paste.
    from . import redact

    redact.install()
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    if ctx.invoked_subcommand is None:
        ctx.invoke(serve)


@cli.command()
@click.option(
    "--http", "use_http", is_flag=True, envvar="SPORTSDATA_MCP_HTTP",
    help="Serve over HTTP instead of stdio (for remote clients / hosting).",
)
@click.option(
    "--transport", type=click.Choice(["stdio", "http", "sse", "streamable-http"]),
    default=None, help="Transport to use. Overrides --http.",
)
@click.option(
    "--host", default="127.0.0.1", envvar="SPORTSDATA_MCP_HOST", show_default=True,
    help="HTTP bind address. Anything but loopback exposes an UNAUTHENTICATED endpoint.",
)
@click.option(
    "--port", default=3000, type=int, envvar="SPORTSDATA_MCP_PORT", show_default=True,
    help="HTTP port.",
)
@click.pass_context
def serve(ctx: click.Context, use_http: bool, transport: str | None, host: str, port: int) -> None:
    """Start the MCP server. Defaults to stdio (what Claude Desktop / Cursor expect)."""
    from .server import serve_http, serve_stdio

    cfg = load_config(explicit_path=ctx.obj.get("config_path"))
    chosen = transport or ("http" if use_http else "stdio")
    if chosen == "stdio":
        serve_stdio(cfg)
        return
    if host not in ("127.0.0.1", "::1", "localhost"):
        # Loud, on stderr, before a single request is served — this endpoint has no
        # auth, and the operator is about to publish their provider credentials to
        # whatever network they just bound to.
        click.echo(
            click.style(
                f"WARNING: binding {host}:{port} — the MCP endpoint is UNAUTHENTICATED. "
                "Anyone who can reach it can use every enabled tool and any provider "
                "credentials in this process's environment. Put it behind an "
                "authenticating reverse proxy with TLS.",
                fg="red",
                bold=True,
            ),
            err=True,
        )
    serve_http(cfg, host=host, port=port, transport=chosen)


@cli.command("list-groups")
def list_groups() -> None:
    """Print every group across every spec, with tool count and description."""
    specs = load_all_specs()
    groups = all_groups(specs)
    if not groups:
        click.echo("No groups found.")
        return
    width = max(len(g) for g in groups)
    for name in sorted(groups):
        g = groups[name]
        click.echo(f"{name:<{width}}  [{g['tools']:>2} tools]  {g['description']}")

    # Presets are the practical entry point — nobody should have to read 88 group
    # names to get started, so print them where the group list is already being read.
    from .spec_loader import PRESETS, expand_wildcard_groups

    click.echo("")
    click.echo("Presets (SPORTSDATA_MCP_GROUPS=<preset>):")
    pw = max(len(p) for p in PRESETS)
    for preset in PRESETS:
        resolved = expand_wildcard_groups([preset], specs)
        tools = sum(groups[g]["tools"] for g in resolved if g in groups)
        provs = len({g.split(".")[0] for g in resolved})
        click.echo(f"  {preset:<{pw}}  {len(resolved):>2} groups · {provs:>2} providers · {tools:>3} tools")
    click.echo("")
    click.echo("Selectors: '*' all · 'espn' or 'espn.*' one provider · '-twitter' to exclude")
    click.echo("  e.g. SPORTSDATA_MCP_GROUPS='free,-espnfantasy'  or  '*,-twitter,-datagolf'")


@cli.command()
@click.argument("specs", nargs=-1, type=click.Path(path_type=Path))
def lint(specs: tuple[Path, ...]) -> None:
    """Validate specs against the schema + capability catalogue. Exit nonzero on failure."""
    # `specs` args are accepted for parity with the documented CLI; linting always
    # runs over the packaged specs dir so cross-spec checks see every provider.
    errors, warnings = lint_specs()
    for w in warnings:
        click.echo(click.style(f"warning: {w}", fg="yellow"), err=True)
    for e in errors:
        click.echo(click.style(f"error: {e}", fg="red"), err=True)
    if errors:
        click.echo(click.style(f"\n✗ lint failed ({len(errors)} error(s))", fg="red"), err=True)
        raise SystemExit(1)
    click.echo(click.style(f"✓ lint passed ({len(warnings)} warning(s))", fg="green"))


@cli.command()
@click.pass_context
def doctor(ctx: click.Context) -> None:
    """Per-provider reachability + auth + REST-contract check. Exit nonzero on failure."""
    import asyncio

    from .doctor import run_doctor

    cfg = load_config(explicit_path=ctx.obj.get("config_path"))
    specs = load_all_specs()
    ok = asyncio.run(run_doctor(cfg, specs, echo=lambda s: click.echo(s, err=True)))
    raise SystemExit(0 if ok else 1)



def format_hash_change(change) -> str:
    """One line of the refresh diff.

    `old` is None for an operation that never carried a hash — a newly-added one, or a
    full-query provider. Subscripting that crashed the entire refresh report with
    `TypeError: 'NoneType' object is not subscriptable`, at exactly the moment it had
    something useful to say. Extracted from the echo loop so the case is testable rather
    than only reachable by running a real refresh.
    """
    was = f"{change.old[:8]}…{change.old[-7:]}" if change.old else "(new)"
    return f"{change.name}: {was} → {change.new[:8]}…{change.new[-7:]}"


@cli.command("refresh-hashes")
@click.argument("provider")
@click.option("--dry-run", is_flag=True, help="Show the diff without writing the spec back.")
def refresh_hashes(provider: str, dry_run: bool) -> None:
    """Refresh persisted-query hashes for PROVIDER from its live front-end bundle."""
    from .refresh.entain_hashes import RefreshError, run_refresh
    from .spec_loader import packaged_specs_dir

    specs = load_all_specs()
    spec = next((s for s in specs if s.provider.id == provider), None)
    if spec is None:
        click.echo(click.style(f"unknown provider '{provider}'", fg="red"), err=True)
        raise SystemExit(1)
    if spec.provider.hash_refresh is None:
        click.echo(
            click.style(f"provider '{provider}' has no hash_refresh block — nothing to refresh", fg="red"),
            err=True,
        )
        raise SystemExit(1)

    spec_path = packaged_specs_dir() / f"{provider}.yaml"
    try:
        result = run_refresh(spec, spec_path, write=not dry_run, echo=lambda s: click.echo(s, err=True))
    except RefreshError as e:
        click.echo(click.style(f"refresh failed: {e}", fg="red"), err=True)
        raise SystemExit(1) from e

    click.echo("", err=True)
    click.echo(f"📋 Diff against {spec_path.name}:", err=True)
    for c in result.changed:
        click.echo(f"   • {format_hash_change(c)}  ✏️", err=True)
    click.echo(f"   • {len(result.unchanged)} unchanged", err=True)
    manifest_only = result.extracted - len(result.documents)
    if manifest_only:
        click.echo(
            click.style(
                f"   ⚠ {manifest_only} op(s) have no printed document (manifest hash only) — "
                f"no runtime APQ self-heal for those",
                fg="yellow",
            ),
            err=True,
        )
    if result.register_failed:
        click.echo(
            click.style(
                f"   ⚠ gateway registration did not stick for {len(result.register_failed)} op(s): "
                f"{', '.join(result.register_failed[:5])}"
                + (" …" if len(result.register_failed) > 5 else "")
                + " — the runtime APQ retry will re-register them on first use",
                fg="yellow",
            ),
            err=True,
        )
    if result.missing_from_bundle:
        click.echo(
            click.style(
                f"   ⚠ {len(result.missing_from_bundle)} op(s) not found in the bundle "
                f"(retired or renamed): {', '.join(result.missing_from_bundle[:5])}"
                + (" …" if len(result.missing_from_bundle) > 5 else ""),
                fg="yellow",
            ),
            err=True,
        )
    click.echo("", err=True)
    if dry_run:
        if result.changed:
            click.echo(
                click.style(f"(dry-run) {len(result.changed)} hash(es) would be refreshed — not written.", fg="yellow")
            )
        else:
            click.echo(click.style(f"✓ {spec_path.name} already up to date (0 hashes changed)", fg="green"))
        return
    if result.documents_written:
        click.echo(
            f"📄 {result.documents_written} printed document(s) → {provider}.documents.json "
            f"(runtime APQ self-heal)"
        )
    if not result.changed:
        click.echo(click.style(f"✓ {spec_path.name} already up to date (0 hashes changed)", fg="green"))
    else:
        click.echo(click.style(f"✅ {spec_path.name} updated ({len(result.changed)} hashes refreshed)", fg="green"))
        click.echo("   Restart the MCP server for changes to take effect.")


@cli.command()
@click.option("--license", "license_key", default="",
              help="Optional licence key — the MCP is free; only needed for gated premium feeds.")
@click.option(
    "--client",
    type=click.Choice(["claude-desktop", "cursor", "both"]),
    default="both",
    show_default=True,
    help="Which AI client to configure.",
)
@click.option("--command", "command", default=None, help="Override the launch command (defaults to this binary).")
@click.option("--print", "print_only", is_flag=True, help="Print the config block instead of writing it.")
def setup(license_key: str, client: str, command: str | None, print_only: bool) -> None:
    """Register this MCP into your AI client(s) — the 'set it up for me' step. Free:
    no licence needed; the full catalogue serves out of the box."""
    import json as _json

    from .setup_client import CLIENTS, client_config_path, full_config, register

    cmd = command or _default_setup_command()
    if print_only:
        click.echo(_json.dumps(full_config(license_key, cmd), indent=2))
        return

    if client == "both":
        # Configure whichever clients are actually present — don't litter configs for
        # apps that aren't installed.
        targets = [c for c in CLIENTS if client_config_path(c).parent.exists()]
    else:
        targets = [client]

    wrote = False
    for c in targets:
        try:
            path = register(c, license_key, cmd)
            click.echo(click.style(f"✓ {c}: {path}", fg="green"))
            wrote = True
        except Exception as exc:  # noqa: BLE001 — one client failing shouldn't abort the others
            click.echo(click.style(f"… {c}: skipped ({exc})", fg="yellow"), err=True)

    if wrote:
        click.echo("\nRestart your AI client, then ask it to “list available sportsdata groups”.")
    else:
        click.echo(
            click.style("No AI clients configured. Re-run with --print to copy the block manually.", fg="red"),
            err=True,
        )
        raise SystemExit(1)


def _default_setup_command() -> str:
    from .setup_client import default_command

    return default_command()


@cli.command("update-specs")
@click.option("--url", default=None, help="Spec-bundle feed URL (default: $SPORTSDATA_SPEC_FEED_URL).")
@click.option("--clear", is_flag=True, help="Remove any applied overlay and revert to the packaged specs.")
def update_specs(url: str | None, clear: bool) -> None:
    """Fetch + apply a signed provider-spec update (OTA) so drifting specs (e.g. Entain
    GraphQL hashes) can be refreshed without a new app build. --clear reverts to packaged."""
    from . import ota

    if clear:
        ota.clear_overlay()
        click.echo(click.style("✓ spec overlay cleared — using the packaged specs.", fg="green"))
        click.echo("   Restart the MCP server for the change to take effect.")
        return

    feed = url or os.environ.get(ota.SPEC_FEED_URL_ENV, "")
    if not feed:
        click.echo(
            click.style("no feed URL — pass --url or set SPORTSDATA_SPEC_FEED_URL", fg="red"), err=True
        )
        raise SystemExit(1)
    try:
        result = ota.fetch_and_apply(feed)
    except ota.SpecFeedError as e:
        click.echo(click.style(f"update failed: {e}", fg="red"), err=True)
        raise SystemExit(1) from e
    click.echo(
        click.style(
            f"✅ applied spec bundle {result['version']}: {len(result['applied'])} spec(s) updated",
            fg="green",
        )
    )
    click.echo("   Restart the MCP server for changes to take effect.")


@cli.command()
def version() -> None:
    """Print version info."""
    from . import ota

    click.echo(_version_string())
    applied = ota.applied_version()
    if applied:
        click.echo(f"spec overlay: {applied} (OTA-applied; `update-specs --clear` reverts)")


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Emit raw JSON.")
def stats(as_json: bool) -> None:
    """Your own usage: per-tool call counts, error rates and slow providers.

    Read from local files written by past sessions. Nothing here has been transmitted;
    this works identically whether or not sharing is enabled.
    """
    import json as _json
    from collections import defaultdict

    from . import telemetry

    sessions = telemetry.load_local()
    if not sessions:
        click.echo("No recorded sessions yet.")
        click.echo("Counters are written when a server session ends having made at least one call.")
        return
    if as_json:
        click.echo(_json.dumps(sessions, indent=2))
        return

    agg: dict[str, dict] = defaultdict(lambda: {"calls": 0, "errors": 0, "empty": 0, "codes": defaultdict(int)})
    for sess in sessions:
        for tool, st in sess.get("tools", {}).items():
            a = agg[tool]
            a["calls"] += st["calls"]
            a["errors"] += st["errors"]
            a["empty"] += st["empty"]
            for code, n in st.get("codes", {}).items():
                a["codes"][code] += n

    total = sum(a["calls"] for a in agg.values())
    errs = sum(a["errors"] for a in agg.values())
    click.echo(f"{len(sessions)} session(s), {total} call(s), {errs} error(s) "
               f"({errs / total * 100:.0f}%)" if total else "no calls recorded")
    click.echo("")

    # Worst first — a healthy tool needs no attention, and a list sorted by call count
    # buries the one that is broken.
    rows = sorted(agg.items(), key=lambda kv: (-kv[1]["errors"], -kv[1]["calls"]))
    width = max((len(t) for t, _ in rows), default=10)
    click.echo(f"{'tool':<{width}}  {'calls':>6} {'errors':>7} {'empty':>6}  top error")
    for tool, a in rows[:25]:
        top = max(a["codes"].items(), key=lambda kv: kv[1])[0] if a["codes"] else ""
        line = f"{tool:<{width}}  {a['calls']:>6} {a['errors']:>7} {a['empty']:>6}  {top}"
        click.echo(click.style(line, fg="red") if a["errors"] else line)

    # Feedback is the only signal here that somebody chose to send rather than one we
    # inferred, so it goes last where it is read, not first where it scrolls away.
    notes = [f for sess in sessions for f in sess.get("feedback", [])]
    if notes:
        click.echo("")
        click.echo(f"Feedback ({sum(1 for f in notes if not f['helpful'])} negative of {len(notes)}):")
        for f in notes[-10:]:
            mark = "✓" if f["helpful"] else "✗"
            click.echo(f"  {mark} {f['at'][:10]}  {f.get('tool') or '(general)'}  {f.get('note') or ''}")

    click.echo("")
    click.echo("A high `empty` count on a tool with no errors usually means the upstream")
    click.echo("has no data for what was asked — not that the call is malformed.")
    if not telemetry.is_enabled():
        click.echo("")
        click.echo("Sharing is OFF. `sportsdata-mcp telemetry` explains what turning it on would send.")


@cli.command()
@click.option("--show-payload", is_flag=True, help="Print exactly what a flush would transmit.")
def telemetry(show_payload: bool) -> None:
    """Show telemetry status, and exactly what sharing would send.

    Sharing requires TWO explicit acts and has no transmitting default:
      SPORTSDATA_TELEMETRY=1                 — consent, env var only
      SPORTSDATA_TELEMETRY_ENDPOINT=<url>    — where to
    With either unset, nothing leaves the machine.
    """
    import json as _json

    from . import telemetry as tel

    enabled, url = tel.is_enabled(), tel.endpoint()
    click.echo(f"consent  (SPORTSDATA_TELEMETRY)          {'ON' if enabled else 'off'}")
    click.echo(f"endpoint (SPORTSDATA_TELEMETRY_ENDPOINT) {url or 'not set'}")
    if enabled and url:
        click.echo(click.style("\nSharing is ON — session summaries will be POSTed to the endpoint above.", fg="yellow"))
    else:
        click.echo(click.style("\nSharing is OFF. Nothing is transmitted.", fg="green"))
    click.echo(f"install id: {tel.install_id()}  (random; delete ~/.sportsdata-mcp/install-id to reset)")

    if show_payload:
        click.echo("\nA flush would send exactly this shape — note there is no field for")
        click.echo("tool arguments, response data, keys, paths, hostnames or IPs:")
        click.echo(_json.dumps(tel.get().payload(), indent=2))
    else:
        click.echo("\nRun with --show-payload to see the exact JSON. Details: docs/TELEMETRY.md")


@cli.command()
@click.argument("provider", required=False)
@click.option("--manual", is_flag=True, help="Paste the credential instead of reading the browser.")
def connect(provider: str | None, manual: bool) -> None:
    """Connect a provider that needs a credential — automatically where possible.

    With no argument, lists what can be connected and what already is. With a provider
    name, reads the credential from your browser (one Keychain prompt), verifies it
    against a live call, and saves it to ~/.config/sportsdata-mcp/config.yaml (0600).

    Nothing is printed that could be a credential, and only the one host's cookies are
    ever read.
    """
    from . import connect as conn_mod

    if not provider:
        click.echo("Providers that need a credential:\n")
        for pid, label, have in conn_mod.status():
            mark = click.style("✓ connected", fg="green") if have else click.style("· not connected", fg="yellow")
            click.echo(f"  {pid:<14} {label:<34} {mark}")
        click.echo("\nEverything else needs nothing at all.")
        click.echo(f"Connect one with:  sportsdata-mcp connect {next(iter(conn_mod.CONNECTORS))}")
        return

    c = conn_mod.CONNECTORS.get(provider)
    if c is None:
        raise click.ClickException(
            f"'{provider}' does not need connecting, or is not supported yet. "
            f"Known: {', '.join(conn_mod.CONNECTORS)}"
        )

    cookies: dict[str, str] = {}
    if not manual:
        click.echo(f"Reading {c.cookie_host} cookies from your browser…")
        click.echo(click.style("  macOS may ask permission for the keychain — that is this step.", fg="cyan"))
        cookies = conn_mod.read_browser_cookies(c.cookie_host, c.cookie_names)
        if cookies:
            click.echo(f"  found: {', '.join(sorted(cookies))}")
        else:
            click.echo(click.style("  nothing found (browser not supported, permission declined, or not logged in)", fg="yellow"))

    if not cookies:
        click.echo(f"\nLog in at {c.login_url}, then {c.manual_hint}.")
        for name in c.cookie_names:
            val = click.prompt(f"  {name}", default="", hide_input=True, show_default=False)
            if val:
                cookies[name] = val
    if not cookies:
        raise click.ClickException("no credential supplied")

    header = conn_mod.build_cookie_header(cookies)
    ok, why = conn_mod.verify(c, header)
    if not ok:
        raise click.ClickException(f"not saved — {why}")
    path = conn_mod.save_secret(c.env_var, header)
    click.echo(click.style(f"\n✓ {c.label} connected — {why}", fg="green"))
    click.echo(f"  saved to {path} (0600) as {c.env_var}, fingerprint {conn_mod.fingerprint(header)}")
    for note in c.notes:
        click.echo(f"  note: {note}")


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
