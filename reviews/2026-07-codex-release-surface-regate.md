# Release-surface gate — independent Codex re-gate

**Reviewed exact head:** warrant `feat/release-surface-gate` at `5898239`,
based on master `f646b7f`.

**Scope:** closure of the first release-surface review: logical shell
extraction, exact argv validation, documentation discovery, abbreviation
handling, wheel/source scope, and selftest coupling.

**Verdict:** **AMEND**

The previous three countervectors are closed in their original forms:

- backslash-continued command substitutions are now discovered;
- `--json=true` and a global `--store` after `verify` are rejected;
- Markdown discovery is repository-wide minus explicit exclusions.

The MCP documentation's comment-after-backslash bug is also a real and correctly
fixed copy/paste defect.

However, the new validator executes command bodies and infers parsing success
from runtime behavior. That creates both fail-open decisions and side effects.
The shell extractor also splits metacharacters before quote-aware tokenization.

## P1 — Timeout is accepted without evidence that parsing happened

`validate()` contains:

```python
except subprocess.TimeoutExpired:
    return True, "timed out after parsing (accepted)"
```

A timeout proves only that the process did not exit. It does not prove that the
entrypoint reached, let alone completed, argument parsing.

### Executed countervector

A fake entrypoint slept immediately, before constructing or invoking a parser.
It was called with an invalid documented argv.

Observed:

```text
validate(...) = (True, "timed out after parsing (accepted)")
```

Thus a wheel whose entrypoint hangs during import or startup is reported as
supporting every documented surface.

Any timeout in a release gate must fail closed. A long-running command such as
`warrant-mcp` cannot be validated by executing it and treating non-termination
as parser evidence.

## P1 — The “dry parse” executes real command side effects

Each documented invocation is executed normally in a temporary cwd. A temporary
cwd is not a sandbox: absolute paths, network access, inherited environment,
subprocesses, and other host resources remain available.

### Executed countervector

Called the candidate's real `validate()` with:

```text
warrant keygen --out <absolute path outside validate's temporary cwd>
```

Observed:

```text
validate = (True, "exit 0")
outside file created = True
outside file size = 65 bytes
```

A documentation-only change can therefore cause CI or the publish workflow to
perform command side effects. Future `warrant-mcp -- <server>` examples can
also reach downstream process execution once their runtime prerequisites are
satisfied.

### Required closure

Validate the parser without dispatching the command:

- expose a parser factory / `parse_argv()` in each Python entrypoint and call
  that from an installed-artifact probe; or
- add an explicit machine-only parse mode that exits immediately after
  successful parsing and before any filesystem/network/subprocess action.

The parse-only boundary must produce an unambiguous machine result. Do not infer
parser success from timeouts, arbitrary runtime exits, or English stderr.

For warrant-go, provide an equivalent parse-only/selftest surface or keep it in
a separate source gate.

## P1 — Exit-code classification is fail-open and the selftest does not call it

`validate()` rejects exit 2 only when stderr contains one of a hand-maintained
set of English substrings. Every other exit, including an unrecognized exit 2,
is accepted.

### Executed countervector

A fake entrypoint emitted usage text and:

```text
error: surface rejected for an unclassified reason
```

then exited 2.

Observed:

```text
validate(...) = (True, "exit 2")
```

This classifier is sensitive to argparse version, localization, custom
`parser.error()` text, and future types/actions.

The nine-case selftest does **not** call `validate()` or
`abbreviations()`. Its last two cases merely ask whether static strings contain
members of `ARGPARSE_ERRORS`. Therefore both the hanging pre-parser and the
unclassified exit-2 countervectors pass the real validator while all nine
selftest cases remain green—the protection and protected code are again
different paths.

The replacement selftest must invoke the actual parse-only validator through
fake/fixture entrypoints and prove:

- valid argv accepted;
- unknown option, wrong scope, unsupported `=value`, missing positional, and
  invalid choice rejected;
- timeout/startup failure rejected;
- no command side effect occurs.

## P1 — Regex segmentation before `shlex` ignores shell quoting

`SEGMENT_SPLIT.split(logical_line)` runs before `shlex.split()`. It therefore
treats `|`, `>`, `;`, `&&`, `)`, and `$(` inside quoted argument values as shell
structure.

### Executed countervector

Changed a documented reason to contain a literal quoted pipe and placed an
unknown flag after it:

```sh
warrant propose ... --reason "utility | fns" \
  --definitely-not-real --actor me@host ...
```

Observed:

```text
RELEASE SURFACE: ALL PASS
exit=0
```

The regex split the quoted value before quote-aware parsing; the resulting
unbalanced segment was silently discarded, hiding the entire invocation.

Tokenize with shell punctuation in a quote-aware pass first, then segment the
tokens. If a logical line contains an owned CLI name but cannot be parsed or
mapped to an invocation, fail closed with its file and line—never `continue`.

Add permanent controls for quoted `|`, `>`, `#`, `;`, `$(` text and unbalanced
quotes.

## P1 — Abbreviation detection chooses a flag value as the subcommand

The code identifies the subcommand with:

```python
next(a for a in argv[1:] if not a.startswith("-"))
```

For the canonical command:

```text
warrant --store ./pack verify ...
```

this selects `./pack`, not `verify`, so `help_of()` never loads `verify --help`.
An abbreviated verify flag is consequently absent from the exact-option model
and is not reported.

### Executed countervector

Changed `--store-mode` to argparse-accepted abbreviation `--store-m` in the
canonical global-store invocation.

Observed:

```text
RELEASE SURFACE: ALL PASS
exit=0
```

The safest fix is to disable argparse abbreviation in the actual public parser
(`allow_abbrev=False`) and validate through the parser-only boundary. Then the
real CLI and the documentation gate share the same exact-option rule. If
abbreviation remains supported, derive the selected subparser from parser state,
not positional heuristics.

## P2 — Wheel results are contaminated by a checkout Go build

`known` includes `warrant-go` whenever `ROOT/impl-go/warrant-go` happens to
exist, even under `--bin <venv>`. The runner then takes that one command from
the checkout while taking Python commands from the wheel.

Executed from exact-head exports:

```text
checkout after building Go:
  ALL PASS (25 documented invocations)

clean wheel/venv with no checkout Go binary:
  ALL PASS (24 documented invocations)
```

Therefore the reported “wheel 25/25” is not a wheel result; it is a composite of
the wheel and a residual source-tree build artifact. The count and tested scope
change based on dirty/build state.

Keep scopes explicit and deterministic:

- `--bin` checks only `WHEEL_CLIS` from that directory;
- a separate source-mode invocation checks warrant-go and requires its binary;
- summaries identify each scope independently;
- absence of an explicitly requested implementation is fatal, not a note.

## What holds

- `ROOT.rglob("*.md")` plus exclusions covers newly added documentation
  directories.
- The original multiline command-substitution and angle-placeholder examples
  are now discovered.
- The installed-wheel Python entrypoints are reached without checkout import
  leakage.
- The checkout passes 25 currently extracted invocations when Go is built.
- The clean wheel passes its 24 Python-entrypoint invocations.
- The exact branch passes `git diff --check`.
- The publish check remains before upload and irreversible publication.

No merge, push, release, adoption, or governance action was performed.
