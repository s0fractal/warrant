# Release-surface gate — independent Codex re-gate 2

**Reviewed exact head:** warrant `feat/release-surface-gate` at
`ad0a85ca5179f04acbb5fd28d6576b6eadb9dca9`, based on master `f646b7f`.

**Scope:** parser-only closure of the previous gate, artifact isolation,
documented-shell coverage, abbreviation handling, and permanent controls.

**Verdict:** **AMEND**

The five previously reported defects are closed in their original forms:

- validation no longer dispatches `keygen` or other command bodies;
- timeout, missing interpreter/import, and unexpected exits fail closed;
- tokenization precedes shell segmentation;
- abbreviation is disabled in the public parsers, including subparsers;
- wheel Python and source Go counts are no longer combined.

The checkout surface selftest and checkout gate pass, and the full Python/Go
agreement suite passes after building the Go verifier.

Three new composition countervectors remain. Two concern the meaning of
“parser-only”: the probe is not bound to the artifact under test, and
`parse_args()` is not the whole CLI acceptance contract. The third shows that
an existing installed-wheel command in `PUBLISHING.md` is outside discovery.

## P1 — The wheel probe can import a different checkout's parser

`validate()` launches the selected Python with the caller's full environment:

```python
cmd = [python, "-c", PARSE_SNIPPET, extra_path or "", mod] + argv[1:]
p = subprocess.run(..., env={**os.environ, "COLUMNS": "200"})
```

In wheel mode `extra_path` is empty, but the subprocess still honors inherited
`PYTHONPATH`. Nothing asserts where the imported module came from.

### Executed countervector

I built and installed the old `0.4.0` master wheel, which has no
`build_parser()`, then ran the candidate checker against that venv:

```text
normal:
  RELEASE SURFACE: CANNOT VALIDATE
  AttributeError: module 'warrant' has no attribute 'build_parser'
  exit 1
```

With only this inherited environment change:

```text
PYTHONPATH=<ad0a85c checkout>/impl
```

the same command, still naming the old wheel's venv, reported:

```text
RELEASE SURFACE: ALL PASS
  (24 documented invocations accepted by the wheel installed in <old-venv>/bin)
exit 0
```

The gate therefore attests to one artifact while executing another artifact's
parser.

### Required closure

Run the target interpreter in isolated mode (`-I`, which ignores
`PYTHONPATH`/user-site) and bind module provenance to the artifact being tested.
For wheel mode, assert that every imported CLI module resolves to the selected
venv's installed distribution/site-packages. For checkout mode, assert that it
resolves under the explicitly supplied checkout `impl/`.

Add a permanent countervector: install a pre-`build_parser` wheel, poison
`PYTHONPATH` with the candidate checkout, and require `CANNOT VALIDATE`.

## P1 — `parse_args()` accepts argv that the real CLI rejects

The checker calls only:

```python
mod.build_parser().parse_args(argv)
```

but public CLI validity also contains post-parse invariants in `main()`.
For example, `warrant-mcp` declares its downstream command as
`argparse.REMAINDER`, then separately rejects an empty remainder:

```python
args = ap.parse_args(argv)
server_cmd = args.server
if server_cmd and server_cmd[0] == "--":
    server_cmd = server_cmd[1:]
if not server_cmd:
    ap.error("provide the downstream server command after --")
```

`warrant` has the same split for `propose --subject`, prior-less
`accept`/`reject --subject --under`, and `supersede <id>`.

### Executed countervector

I changed the existing MCP documentation block from:

```sh
warrant-mcp ... --effects effects.json \
    -- <your MCP server command>
```

to:

```sh
warrant-mcp ... --effects effects.json
```

Observed:

```text
surface gate: ALL PASS (24/24), exit 0
real warrant-mcp:
  error: provide the downstream server command after --
  exit 2
```

Thus “safe parser-only” currently means only “argparse grammar accepted”, not
“the documented invocation is accepted by the CLI”, despite the report and
documentation claiming the latter.

### Required closure

Expose one side-effect-free public argv boundary per CLI, for example
`parse_cli(argv)`, which performs both `parse_args()` and all pure post-parse
usage validation, then returns the namespace without dispatch. `main()` and the
release checker must call that same boundary.

Move the constraints above into that boundary (or encode them directly in
argparse where possible). Add permanent vectors for:

- MCP without a downstream command;
- `propose` without `--subject`;
- prior-less `accept`/`reject` without `--subject --under`;
- `supersede` without the target WarrantID;
- `keygen --out <absolute path>` accepted without creating the file.

## P1 — Path-qualified installed CLI invocations are silently outside coverage

`invocations()` records a command only when:

```python
argv[0] in known
```

The repository already documents this installed-wheel invocation:

```sh
/tmp/tv/bin/warrant selftest
```

in `PUBLISHING.md`. Its basename is a wheel CLI, but its literal `argv[0]` is
not `"warrant"`, so the gate does not count or validate it.

### Executed countervector

Changed that existing command to:

```sh
/tmp/tv/bin/warrant selftest --definitely-not-real
```

Observed:

```text
RELEASE SURFACE: ALL PASS (24 documented invocations accepted by this checkout)
exit 0
```

The release gate is blind to the repository's own TestPyPI verification command.
The same exact-name rule also skips common wrappers such as
`env X=y warrant ...` and `command warrant ...`.

### Required closure

Normalize path-qualified commands by basename before mapping them to an owned
CLI, while retaining the original spelling for diagnostics. Decide and document
which wrappers are supported; at minimum cover the path-qualified form already
present in `PUBLISHING.md`.

Add a permanent mutation/control placing an unknown flag on that exact
`/tmp/tv/bin/warrant` command and require the gate to fail at its file and line.

## P2 — Claimed timeout/exit/side-effect controls are not permanent tests

The reported closure says the 15-case selftest covers a sleeping interpreter,
an interpreter exiting 7, and the `keygen` no-side-effect property. The exact
head's 15 checks do not contain those cases. They cover an unreachable
interpreter, but no timeout, unexpected non-2 exit, artifact-origin poisoning,
or dispatch-side-effect assertion.

The code paths currently fail closed by inspection, and the manual keygen probe
is valid, but this repository's own lesson is that a property without a control
does not survive refactoring.

Add the fake sleeping/exit-7 interpreters and the absolute-output `keygen`
control to `selftest()`, using the real `validate()` path. The wheel-provenance
countervector above should be an integration test because it needs two distinct
artifacts.

## Re-gate target

Re-gate the composition, not only the three local fixes:

1. an old wheel plus hostile `PYTHONPATH` must remain `CANNOT VALIDATE`;
2. every accepted argv must pass the same pure validation boundary that
   `main()` uses before dispatch;
3. path-qualified documented wheel commands must contribute to the count and
   fail on an injected unknown option;
4. parser validation must remain side-effect-free;
5. checkout and freshly installed wheel must still produce the intended,
   separately scoped results.

Do not merge `feat/release-surface-gate` or its dependent
`feat/adoption-surface` on this head.
