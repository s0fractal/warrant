# Release-surface gate — independent Codex re-gate 5

**Reviewed exact head:** warrant `feat/release-surface-gate` at
`af97ff08a5c46e7c28c354b78a09f68a7147b011`, based on
`e434d5a71475965a46c556c015708730b9a03a32`.

**Scope:** filesystem-only artifact preflight, `RECORD` integrity, exact
console-entry-point binding, and permanent artifact controls.

**Verdict:** **AMEND**

The previous exact countervectors are closed:

- a parser can no longer forge `MODULE-DIST` through its own output;
- `warrant-verify-evil` is rejected as a different canonical distribution;
- a module changed without changing `RECORD` is rejected;
- missing, non-executable, no-shebang, and undeclared scripts are rejected;
- parser modules are loaded from the checked paths rather than selected by
  their top-level import names.

The exact-head 34-case selftest, checkout gate, fresh-wheel gate, and full
Python/Go agreement suite are green.

The new design makes the correct decision before running target code, but its
trust root is still inside the installed venv: the module is checked against a
`RECORD` that can be rewritten with it. Console-script bytes and the callable
part of entry-point mappings are not checked at all.

## P1 — `RECORD` is still self-provenance unless bound to the wheel

The gate reads modules and their expected hashes from the same installed tree:

```python
record = read(<venv>/*.dist-info/RECORD)
actual = sha256(<venv>/site-packages/warrant_anchor.py)
require actual == record["warrant_anchor.py"]
```

This detects an accidental module change while `RECORD` remains untouched, but
does not establish provenance. The installed subject supplies both the bytes
and the statement about which bytes are correct.

### Executed countervector

Against a freshly installed exact-head wheel:

1. appended code/text to `warrant_anchor.py`;
2. recomputed its SHA-256;
3. replaced that one digest and size in the installed `RECORD`;
4. ran the unchanged release-surface gate.

Observed:

```text
RELEASE SURFACE: ALL PASS
  (25 documented invocations accepted by warrant-verify 0.5.0)
exit 0
```

This is the same principle that motivated the current rewrite: the subject
cannot be its own provenance. Moving the assertion from the module into its
adjacent mutable manifest does not create an external trust root.

### Required closure

Add the built wheel itself as an explicit input, for example:

```text
check_release_surface.py --wheel dist/warrant_verify-0.5.0-*.whl \
                         --bin /tmp/venv/bin
```

Read canonical name, version, module hashes, and `entry_points.txt` from the
wheel archive. Compare installed files and installed metadata to that external
manifest. Optionally also accept/pin the wheel SHA-256 so CI logs exactly which
artifact was checked.

The publish workflow already has the wheel path; it should be the provenance
root. `--bin` alone can check installation self-consistency but must not claim
artifact identity.

Add a permanent control that changes a module **and updates installed RECORD**.
It must still fail because neither matches the wheel archive.

## P1 — An executable shebang is not the installed console entry point

`check_artifact()` currently checks:

```python
script.exists()
os.access(script, os.X_OK)
script.read_bytes()[:2] == b"#!"
```

It does not verify script bytes against installed `RECORD`, bind them to the
wheel's entry-point metadata, or execute a safe parser/help probe through the
actual script.

The entry-point comparison also checks only:

```python
declared.split(":")[0] == expected_module
```

so `warrant_mcp:not_main` is accepted in place of
`warrant_mcp:main`. `entry_points.txt` itself is not hash-checked.

### Executed countervectors

**Broken executable script:** replaced the real `warrant-mcp` wrapper with:

```sh
#!/bin/sh
echo "broken replacement" >&2
exit 99
```

and kept it executable.

```text
surface gate: ALL PASS (25/25), exit 0
actual warrant-mcp --help: exit 99
```

**Wrong callable:** changed installed metadata to:

```ini
warrant-mcp = warrant_mcp:not_main
```

The gate again returned `ALL PASS 25/25`.

The docs promise an executable command, not merely an executable file plus an
importable parser module elsewhere in the venv.

### Required closure

From the trusted wheel archive require exact mappings:

```text
warrant        = warrant:main
warrant-mcp    = warrant_mcp:main
warrant-anchor = warrant_anchor:main
```

Then:

- compare installed `entry_points.txt` to the wheel metadata;
- verify generated script bytes against pip's installed `RECORD`, with that
  installed record itself bound to the wheel/install operation;
- run every actual installed script with `--help` in the bounded sanitized
  environment and require exit 0;
- continue using the path-loaded `parse_cli()` for detailed documented argv
  validation.

Add permanent controls for an executable shebang script that exits 99 and for
the correct module with the wrong callable.

## P2 — The permanent matrix still omits known contract edges

The code correctly rejects prior-less `accept` and `reject`, but the 34-case
selftest still covers only `propose` and `supersede`. A regression removing
`accept`/`reject` from the guarded tuple remains green.

The artifact matrix covers:

- changed module with unchanged `RECORD`;
- missing/non-executable/no-shebang/undeclared scripts;

but not:

- changed module plus changed `RECORD`;
- executable wrong script;
- wrong callable after `:`;
- modified `entry_points.txt`;
- wheel-to-install identity.

Add these as integration controls against a real tiny wheel/install pair rather
than only a synthetic mutable venv.

## Residual `.pth` risk

The stated `.pth` limitation is accurate: `-I` still performs normal site
initialization, and executable `.pth` code runs before the snippet. This need
not block the declared clean-build CI threat model if it remains explicit.

If the gate later needs hostile-environment integrity, use `-I -S`, inspect the
target paths without site initialization, and append only the verified
site-packages directory without processing `.pth` files.

## Re-gate target

1. The exact built wheel—not its installed copy—is the provenance root.
2. Module, metadata, and entry-point changes cannot be hidden by rewriting the
   installed `RECORD`.
3. Exact `module:main` mappings are enforced.
4. The actual installed console scripts are exercised safely and cannot be
   replaced by arbitrary executable shebang files.
5. All four `warrant.parse_cli` invariants and the new manifest/script
   countervectors are permanent.
6. Old-wheel, hostile-`PYTHONPATH`, checkout, fresh-wheel, and agreement results
   remain green.

Do not merge `feat/release-surface-gate` or its dependent
`feat/adoption-surface` on this head.
