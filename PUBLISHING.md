# Publishing `warrant-verify` to PyPI

The package is release-ready. These are the exact steps to publish it. Publishing
is **irreversible** (a version + name, once uploaded, can't be reused), so the
final `twine upload` is left for the maintainer to run with their own token.

- **Distribution name:** `warrant-verify` (the bare `warrant` is taken on PyPI).
- **Import module & CLI command:** `warrant` (unchanged).
- **What ships:** the `warrant` verifier + the bundled Σ-GLYPH Book I oracle, so
  `ski@v1` reasons re-execute offline with no separate install.

## 1. Build + validate (safe, no upload)

```bash
python3 -m pip install --upgrade build twine
python3 -m build                       # -> dist/warrant_verify-0.3.0{.tar.gz,-py3-none-any.whl}
twine check dist/*                      # both must report PASSED
```

Validate the built wheel in a throwaway env (this is the artifact users get):

```bash
python3 -m venv /tmp/wv && /tmp/wv/bin/pip install dist/warrant_verify-0.3.0-py3-none-any.whl
( cd /tmp && /tmp/wv/bin/warrant conformance "$OLDPWD/examples" )   # CONFORMANCE: ALL PASS (20/20)
/tmp/wv/bin/warrant --store demos/air-canada/pack/.warrants verify  # 0 errors
```

## 2. Dry run on TestPyPI (recommended)

```bash
twine upload --repository testpypi dist/*
python3 -m venv /tmp/tv
/tmp/tv/bin/pip install -i https://test.pypi.org/simple/ warrant-verify
/tmp/tv/bin/warrant selftest
```

## 3. Publish to PyPI (the irreversible step — maintainer runs this)

```bash
twine upload dist/*                     # prompts for API token (or ~/.pypirc)
```

Then confirm the public install works:

```bash
pipx install warrant-verify            # or: pip install warrant-verify
warrant selftest && warrant conformance <clone>/examples
```

## 4. After publishing

- Flip the READMEs' "coming once published" note to the real one-liner
  (`pipx install warrant-verify`) in `README.md` and `demos/air-canada/README.md`.
- Tag the release: `git tag warrant-verify-v0.3.0 && git push --tags`.

## Follow-up: the `warrant-mcp` console command

`integrations/mcp/warrant_mcp.py` currently runs as `python3
integrations/mcp/warrant_mcp.py …`. To ship it as a `warrant-mcp` console command
in a later release, add it to the package as a third top-level module and wire a
second entry point in `pyproject.toml`:

```toml
[project.scripts]
warrant = "warrant:main"
warrant-mcp = "warrant_mcp:main"
```

This needs `warrant_mcp.py` to be discoverable as an installed module (e.g. moved
alongside `impl/warrant.py`, or the project switched to a package layout). Left
out of 0.3.0 to keep the core verifier's single-purpose surface boring.
