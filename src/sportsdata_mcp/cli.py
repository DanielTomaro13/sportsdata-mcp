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
from .spec_loader import all_groups, lint as lint_specs, load_all_specs


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
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    if ctx.invoked_subcommand is None:
        ctx.invoke(serve)


@cli.command()
@click.pass_context
def serve(ctx: click.Context) -> None:
    """Start the MCP stdio server (default command)."""
    from .server import serve_stdio

    cfg = load_config(explicit_path=ctx.obj.get("config_path"))
    serve_stdio(cfg)


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
        click.echo(f"   • {c.name}: {c.old[:8]}…{c.old[-7:]} → {c.new[:8]}…{c.new[-7:]}  ✏️", err=True)
    click.echo(f"   • {len(result.unchanged)} unchanged", err=True)
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
    if not result.changed:
        click.echo(click.style(f"✓ {spec_path.name} already up to date (0 hashes changed)", fg="green"))
    elif dry_run:
        click.echo(
            click.style(f"(dry-run) {len(result.changed)} hash(es) would be refreshed — not written.", fg="yellow")
        )
    else:
        click.echo(click.style(f"✅ {spec_path.name} updated ({len(result.changed)} hashes refreshed)", fg="green"))
        click.echo("   Restart the MCP server for changes to take effect.")


@cli.command()
@click.option("--license", "license_key", required=True, help="Your sportsdata licence key (sd_live_…).")
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
    """Register this MCP into your AI client(s) with your licence — the 'set it up for me' step."""
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


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
