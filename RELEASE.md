# Releasing the standalone installer

The licensed product is a **signed, notarized download** (commerce Phase 3) — not a PyPI
package. The customer downloads `sportsdata-mcp.app`, and `sportsdata-mcp setup` registers
it into their AI client. No Python required.

## One-time: bake the entitlement key + URL

After deploying the entitlement Worker (`services/entitlement/README.md` step 7), set in
`src/sportsdata_mcp/licence.py`:

- `BAKED_PUBKEY_B64` = the **public** line from `gen-keypair.py`
- `DEFAULT_ENTITLEMENT_URL` = your deployed Worker URL

so the bundled binary verifies licences offline with no extra config.

## One-time: Apple Developer ID (for a Gatekeeper-clean download)

Add these repo **Actions secrets** (you already have these from the desktop app):

| Secret | What |
| --- | --- |
| `APPLE_CERT_P12_BASE64` | base64 of the exported "Developer ID Application" `.p12` |
| `APPLE_CERT_PASSWORD` | the `.p12` export password |
| `APPLE_SIGNING_IDENTITY` | `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` + `APPLE_APP_PASSWORD` + `APPLE_TEAM_ID` | notarytool creds (or the `APPLE_API_*` trio) |

## Cut a release

1. Bump the version in `pyproject.toml` + `src/sportsdata_mcp/__init__.py`.
2. Tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
3. The **Release (macOS installer)** workflow builds the bundle, and:
   - **with** the Apple secrets → signs + notarizes + staples a **DMG**, attached to the release;
   - **without** → uploads an **unsigned** `.app` zip (still installable, Gatekeeper warns).
4. Link the DMG from the fulfilment email + `feeds.html`.

## Validate the build without signing

Run the workflow manually (**Actions → Release → Run workflow**, or `workflow_dispatch`).
It produces the unsigned `.app` zip — confirms PyInstaller bundles the MCP + specs cleanly
before you wire the Apple secrets.

## Local build (macOS, optional)

```sh
pip install -e ".[build]"
sh scripts/build-installer.sh      # dist/sportsdata-mcp/  (+ zip)
sh scripts/make-macos-app.sh       # dist/sportsdata-mcp.app
sh scripts/sign-and-notarize.sh    # dist/sportsdata-mcp-X.Y.Z-macos.dmg  (needs the Apple ID)
```

## Windows

Not yet wired. PyInstaller builds a `.exe` the same way; add a `windows-latest` job +
Authenticode signing when you want a Windows download. macOS ships first.
