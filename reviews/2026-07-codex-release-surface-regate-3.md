# Release-surface gate — independent Codex re-gate 3

**Reviewed exact head:** warrant `feat/release-surface-gate` at
`f921c4ad48d8c856573ae87aa175ae5750c7500f`, based on
`ad0a85ca5179f04acbb5fd28d6576b6eadb9dca9`.

**Scope:** closure of artifact substitution, the pure `parse_cli` contract,
path-qualified discovery, and permanent hostile controls.

**Verdict:** **AMEND**

The exact previous countervectors are closed:

- old `0.4.0` plus `PYTHONPATH=<new checkout>/impl` is now
  `CANNOT VALIDATE`;
- `warrant-mcp` without a downstream command is rejected by the same
  `parse_cli()` used by `main()`;
- `/tmp/tv/bin/warrant selftest --definitely-not-real` is discovered and
  rejected at the correct `PUBLISHING.md` line;
- timeout, exit 7, and `keygen` no-side-effect checks are now permanent tests.

The exact-head 22-case selftest, checkout surface gate, fresh `0.5.0` wheel
surface gate, and full Python/Go agreement suite are green.

However, the fixes close the examples more narrowly than their stated
contracts. The main `warrant` CLI still has post-parse usage checks outside
`parse_cli()`. Wheel provenance is directory-based rather than
distribution-based, allowing a venv with no wheel to pass. The gate also does
not verify that the documented console scripts were installed.

## P1 — `warrant.parse_cli()` still omits the post-parse invariants

The new `warrant.parse_cli()` is:

```python
def parse_cli(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    return args
```

The exact pure invariants named in the previous review remain in `main()`, after
store construction and `store.require()`:

```python
if not args.subject:
    sys.exit("propose requires --subject")

if args.prior_id is None:
    if args.cmd == "supersede":
        sys.exit("supersede requires the warrant id being superseded")
    if not (args.subject and args.under):
        sys.exit(f"{args.cmd} without a prior requires --subject and --under")
```

Only the MCP invariant was moved. The 22-case selftest also checks only MCP,
so it reports the generalized contract as protected while leaving all four
`warrant` cases uncovered.

### Executed countervectors

Directly through the candidate's real `validate()`:

```text
propose without --subject                         -> accepted
prior-less accept without --subject/--under       -> accepted
prior-less reject without --subject/--under       -> accepted
supersede without target WarrantID                -> accepted
```

I then removed `--subject diff.patch` from the existing README `propose`
command.

Observed:

```text
surface gate: RELEASE SURFACE: ALL PASS (25/25), exit 0
real CLI against an initialized store:
  propose requires --subject
  exit 1
```

This is the same composition seam as the MCP finding, still reachable through
the primary CLI.

### Required closure

Move every pure usage invariant from `main()` into `warrant.parse_cli()`.
`main()` must start dispatch only after that function returns.

Add all four previously requested permanent vectors, not only MCP:

- `propose` without `--subject`;
- prior-less `accept` without `--subject --under`;
- prior-less `reject` without `--subject --under`;
- `supersede` without its target WarrantID.

The gate and the real CLI must reject each through the same `parse_cli()` call.

## P1 — A venv with no Warrant wheel can attest `ALL PASS`

The provenance predicate is:

```python
str(Path(origin).resolve()).startswith(str(Path(expect_origin).resolve()))
```

In wheel mode `expect_origin` is the entire venv root (`binroot.parent`), not
the installed `warrant-verify` distribution. This has two problems:

1. string prefix is not path containment (`/tmp/v5-evil` starts with
   `/tmp/v5`);
2. even real containment only proves “some file inside the venv”, not
   “a file shipped by the wheel under test”.

### Executed countervectors

**Prefix collision:** created an empty venv `v5`, put dummy `warrant.py`,
`warrant_mcp.py`, and `warrant_anchor.py` under sibling `v5-evil`, and added
that path through a `.pth` file processed by the isolated interpreter.

**Inside-venv substitution:** repeated with the dummy modules under
`v6/evil`, still with no `warrant-verify` distribution installed.

Each dummy module exposed only:

```python
def parse_cli(argv=None):
    return None
```

Both venvs produced:

```text
RELEASE SURFACE: ALL PASS
  (25 documented invocations accepted by the wheel installed in <venv>/bin)
exit 0
```

There was no wheel installed. `-I` correctly closes inherited `PYTHONPATH`, but
does not turn a directory-containment check into artifact identity; normal venv
`.pth` processing remains active.

### Required closure

For `--bin` mode, use the selected interpreter's
`importlib.metadata.distribution("warrant-verify")` and require:

- the distribution exists;
- its version/metadata can be reported;
- each expected CLI module resolves to the exact file recorded by that
  distribution, not merely somewhere under the venv;
- the three declared console entry points map to the expected modules/functions.

Use real path comparison (`Path.is_relative_to` where containment is actually
intended), never string prefix.

Add an integration countervector with an empty venv plus `.pth`-injected dummy
modules. It must return `CANNOT VALIDATE`, not `ALL PASS`.

## P1 — Missing console scripts do not affect the wheel verdict

The wheel gate invokes `<venv>/bin/python -I -c ...` and imports modules
directly. It never checks that the commands promised to users exist in
`<venv>/bin`, nor that installed entry-point metadata maps them correctly.

### Executed countervector

Built and installed the exact-head `0.5.0` wheel, confirmed `25/25`, then moved
only:

```text
<venv>/bin/warrant-mcp
```

out of the way. The documented `warrant-mcp` command was no longer executable.

Observed before and after:

```text
RELEASE SURFACE: ALL PASS (25/25)
exit 0
```

Thus the release-surface gate can approve parser modules while the released
command surface is absent.

### Required closure

In wheel mode, require every documented wheel CLI's console script to exist and
be executable, and bind it to the distribution's declared entry point. A
permanent control must remove/rename one installed script and make the gate fail
with that command named.

This can share the distribution-metadata boundary from the previous finding:
artifact identity, entry-point identity, module identity, and parser behavior
should be one preflight, not four independent assumptions.

## P2 — The path-qualified “validated” selftest is vacuous

The selftest correctly proves that `invocations()` recognizes a qualified path.
Its next check calls:

```python
accepted(["/tmp/tv/bin/warrant", "verify", "--definitely-not-real"])
```

But `accepted()` passes `argv[0]` directly to `validate()`, whose module map has
no key named `/tmp/tv/bin/warrant`. Therefore it returns false before inspecting
the option:

```text
/tmp/tv/bin/warrant selftest                  -> rejected
/tmp/tv/bin/warrant verify --bad             -> rejected
reason: no parser-only entry point known for `/tmp/tv/bin/warrant`
```

The production composition currently works—the mutated `PUBLISHING.md` command
does fail—but this test does not protect it.

Compose the two real stages in the test:

1. call `invocations("/tmp/tv/bin/warrant ...")`;
2. pass the normalized argv it returns into `validate()`;
3. prove a valid path-qualified command passes and the same command with an
   unknown flag fails.

## Re-gate target

1. All pure `warrant` usage invariants live in and are tested through
   `parse_cli()`.
2. Empty/prefix-collision venvs with injected modules cannot claim to contain a
   wheel.
3. Removing one console script or changing one entry-point mapping makes wheel
   preflight fail.
4. The exact old-wheel hostile-`PYTHONPATH`, MCP, path-qualified, timeout,
   exit-7, and no-side-effect controls remain green.
5. Checkout, freshly installed wheel, and the Python/Go agreement suite remain
   green.

Do not merge `feat/release-surface-gate` or its dependent
`feat/adoption-surface` on this head.
