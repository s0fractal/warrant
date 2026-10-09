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

> **Already done.** `warrant-verify` is live on PyPI, and every release since
> **0.3.0** (2026-07-16) has gone out through Trusted Publishing. This section
> is kept for the next project and for re-establishing the publisher if it is
> ever lost; skip it unless one of those applies. The current release is
> whatever PyPI (<https://pypi.org/project/warrant-verify/#history>) and
> GitHub Releases (`gh release list`) say was actually published, each
> under its tag `v<version>`; `version` in `pyproject.toml` is only the
> tooling version this checkout declares, which `publish.yml` refuses to
> publish under a disagreeing tag — and if this file and PyPI ever
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

1. Bump `version` in `pyproject.toml` **and in `impl-rs/Cargo.toml`** (e.g.
   `0.6.0` → `0.6.1`; one tooling version, CHANGELOG.md — the `crate` job fails
   the release if the two disagree), run `cargo update -p warrant-verify
   --manifest-path impl-rs/Cargo.toml` so the lock file follows, and merge to
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

**Never actually performed.** Every real release has gone straight to PyPI; the
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

## crates.io — the Rust implementation (`warrant-verify` crate)

`impl-rs/` publishes to crates.io as **`warrant-verify`** (library
`warrant_verify`, binary `warrant-rs` — not `warrant`, so it never shadows the
Python CLI on a PATH that has both). The bare name `warrant` is taken on
crates.io, as it is on PyPI.

**Status: prepared, never published.** Everything up to the upload runs on every
release and every manual dispatch: the `crate` job in `publish.yml` packages the
crate from its listed files only, builds and tests *that package* (not the
checkout), runs its CLI's conformance and selftest, and dry-runs the upload. The
`crates-io` job, which uploads, is gated on the repository variable
`CRATES_IO_TRUSTED_PUBLISHING`, which is not set.

### One-time setup (the owner, on the web and once at a terminal)

crates.io Trusted Publishing is configured on an *existing* crate, so the first
version goes up by hand:

1. Sign in at <https://crates.io> with the GitHub account that owns
   `s0fractal/warrant`, create an API token scoped to **publish-new** (and
   `publish-update`) for the crate name `warrant-verify`, and from a clean
   checkout of the release tag:

   ```bash
   cd impl-rs
   cargo login                   # paste the token; it stays in ~/.cargo/credentials.toml
   cargo publish --dry-run --locked
   cargo publish --locked        # irreversible: a version can be yanked, never replaced
   ```

   Then revoke that token: every later version goes through OIDC.
2. On the crate's page → Settings → Trusted Publishing → add GitHub with
   **exactly**: owner `s0fractal`, repository `warrant`, workflow
   `publish.yml`, environment `crates-io`.
3. In the GitHub repository → Settings → Environments, create `crates-io`
   (required reviewers recommended, as for `pypi`), and under Variables set
   `CRATES_IO_TRUSTED_PUBLISHING` = `true`.

From then on a published GitHub Release uploads both packages, each from the
same tag, each by OIDC with no stored token.

### What the crate claims, and what checks it

The crate's README states its parity claim and its limits (signing is not
constant-time; `keygen` is Unix-only; the MCP/anchoring programs of the Python
package are not part of it). The claim is checked by CI's `rust` job:
`cargo fmt/clippy/test`, the conformance pack at settlement grade, the
three-way verifier agreement at both grades, `tests/reference_defects_2026_10.py`,
and `tests/rs_parity.py` (byte-identical output against the Python reference).

## Manual fallback (if you ever bypass CI)

```bash
python3 -m build && twine check dist/*
twine upload dist/*                    # needs your PyPI token in ~/.pypirc
```
