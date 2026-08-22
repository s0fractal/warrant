# Publishing `warrant-verify` to PyPI

Publishing is automated with **Trusted Publishing (OIDC)** — no API tokens are
stored anywhere. Cutting a GitHub Release builds, validates, and publishes the
package (`.github/workflows/publish.yml`). You do a **one-time** setup on PyPI,
then every release publishes itself.

- **Distribution name:** `warrant-verify` (the bare `warrant` is taken on PyPI).
- **Import module & CLI command:** `warrant` (unchanged).
- **What ships:** the `warrant` verifier + the bundled Σ-GLYPH Book I oracle, so
  `ski@v1` reasons re-execute offline with no separate install.

## One-time setup (you, on the web — I can't do this part)

> **Already done.** `warrant-verify` is live on PyPI. Four releases have gone
> out through Trusted Publishing: **0.3.0** and **0.4.0** (2026-07-16),
> **0.5.0** (2026-07-30) and **0.6.0** (2026-07-31, the current release, tag
> `v0.6.0`). This section is kept for the next project and for re-establishing
> the publisher if it is ever lost; skip it unless one of those applies. The
> current released version is checkable at
> <https://pypi.org/project/warrant-verify/> — and if this note and PyPI ever
> disagree, PyPI is right.

### 1. Add a "pending publisher" on PyPI

If the project did not yet exist on PyPI you would use a *pending* publisher (it
creates the project on first publish). Go to
<https://pypi.org/manage/account/publishing/> → "Add a pending publisher" and
enter **exactly**:

| Field | Value |
|---|---|
| PyPI Project Name | `warrant-verify` |
| Owner | `s0fractal` |
| Repository name | `warrant` |
| Workflow name | `publish.yml` |
| Environment name | `pypi` |

(Optional dry runs: repeat on <https://test.pypi.org/manage/account/publishing/>
with Environment `testpypi`.)

### 2. Create the GitHub Environments

In the repo → Settings → Environments, create `pypi` (and optionally `testpypi`).
Add protection to `pypi` if you want a manual approval gate before each publish
(recommended: "Required reviewers" = you).

## Releasing (every version, automated)

1. Bump `version` in `pyproject.toml` (e.g. `0.6.0` → `0.6.1`) and merge to
   `master`.
2. Build the evidence packs the README tells strangers to download. The README's
   "no clone, no build, no account" quest is only true if these assets exist on
   the release:

   ```bash
   tools/build_release_packs.sh          # -> dist/*.zip + dist/SHA256SUMS
   ```

   The script refuses to publish a pack containing anything key-shaped, and
   verifies each zip unzipped in an empty directory with no repo on the path —
   i.e. as the stranger will.
3. Cut a GitHub Release with tag **`v0.6.1`** (the `v` + the exact pyproject
   version — the workflow fails the build if they disagree), attaching those
   assets:

   ```bash
   gh release create v0.6.1 --generate-notes dist/*.zip dist/SHA256SUMS
   ```
4. The `publish` workflow builds, runs `twine check`, installs the wheel, proves
   it runs offline, and checks that the wheel actually offers every CLI surface
   the documentation promises (`tools/check_release_surface.py`), then publishes
   to PyPI via OIDC. Watch it:

   ```bash
   gh run watch
   ```
5. Confirm the public install:

   ```bash
   pipx install warrant-verify        # or: pip install warrant-verify
   warrant selftest
   ```

## Dry run on TestPyPI (optional)

**Never actually performed.** All four real releases went straight to PyPI; the
`testpypi` job has never run, so this path is documented and unexercised — read
it as a plan, not as a tested procedure. After the TestPyPI pending publisher +
`testpypi` environment exist, trigger the workflow manually to publish to
TestPyPI only:

```bash
gh workflow run publish.yml
gh run watch
python3 -m venv /tmp/tv && /tmp/tv/bin/pip install -i https://test.pypi.org/simple/ warrant-verify
/tmp/tv/bin/warrant selftest
```

## After the first publish — done

`README.md` and `demos/air-canada/README.md` carry the real one-liner
(`pipx install warrant-verify`); there are no "coming once published" notes
left. Kept as a record of what the step was.

## What ships

The wheel installs four console commands, plus the bundled Σ-GLYPH oracle:

| Command | Module | What it is |
|---|---|---|
| `warrant` | `warrant.py` | the verifier / record CLI |
| `warrant-mcp` | `warrant_mcp.py` | the sealing **proxy**: wraps another MCP server and seals its tool-calls |
| `warrant-mcp-server` | `warrant_mcp_server.py` | the MCP **server**: the agent files its own decisions (added in 0.8.0; first published on PyPI in 0.9.0) |
| `warrant-anchor` | `warrant_anchor.py` | RFC 6962 Merkle batching / anchoring |

Every module ships from `impl/`, because `package-dir = {"" = "impl"}` gives the
flat namespace exactly one root — a module anywhere else cannot be in the wheel
at all. That is why `warrant_mcp_server.py` was moved there from
`integrations/mcp-server/` rather than being shipped from where it was written.

**A release that adds a console script also owes the MCP Registry a manifest
bump.** `integrations/mcp-server/server.json` names the PyPI package *and its
version*, and the registry refuses a version that is not on PyPI yet — so the
order is: publish to PyPI, then `mcp-publisher publish`. `LISTINGS.md` has the
ownership-marker requirement that must already be in the published README.

## Manual fallback (if you ever bypass CI)

```bash
python3 -m build && twine check dist/*
twine upload dist/*                    # needs your PyPI token in ~/.pypirc
```
