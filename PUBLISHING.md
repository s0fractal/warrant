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

> **Already done.** `warrant-verify` is live on PyPI (0.3.0 and 0.4.0, published
> 2026-07-16 via Trusted Publishing). This section is kept for the next project
> and for re-establishing the publisher if it is ever lost; skip it unless one of
> those applies. Current released version is checkable at
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

1. Bump `version` in `pyproject.toml` (e.g. `0.3.0` → `0.3.1`) and merge to
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
3. Cut a GitHub Release with tag **`v0.3.1`** (the `v` + the exact pyproject
   version — the workflow fails the build if they disagree), attaching those
   assets:

   ```bash
   gh release create v0.3.1 --generate-notes dist/*.zip dist/SHA256SUMS
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

## Dry run before the first real release (recommended)

After the TestPyPI pending publisher + `testpypi` environment exist, trigger the
workflow manually to publish to TestPyPI only:

```bash
gh workflow run publish.yml
gh run watch
python3 -m venv /tmp/tv && /tmp/tv/bin/pip install -i https://test.pypi.org/simple/ warrant-verify
/tmp/tv/bin/warrant selftest
```

## After the first publish

- Flip the "coming once published" notes in `README.md` and
  `demos/air-canada/README.md` to the real one-liner (`pipx install
  warrant-verify`).

## What ships

The wheel installs two console commands: `warrant` (verify) and `warrant-mcp`
(seal an MCP server's actions into an evidence pack), plus the bundled Σ-GLYPH
oracle. All three modules live in `impl/`.

## Manual fallback (if you ever bypass CI)

```bash
python3 -m build && twine check dist/*
twine upload dist/*                    # needs your PyPI token in ~/.pypirc
```
