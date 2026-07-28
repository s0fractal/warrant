# Release-surface gate — independent Codex review

**Reviewed exact head:** warrant `feat/release-surface-gate` at `4f75472`,
based on master `f646b7f`.

**Scope:** documentation discovery, Markdown/shell extraction, CLI-surface
decision, built-wheel isolation, and publish-workflow placement.

**Verdict:** **AMEND**

The built-artifact boundary is real: an exact-head wheel
`warrant_verify-0.5.0-py3-none-any.whl` was built, installed into a clean venv,
and checked while the current directory was `/tmp`. The gate interrogated the
installed console scripts and reported all 18 currently extracted flags
supported. There was no checkout import leak.

The whole-token `offers()` change also closes the specific prefix defect:
`--js`, `--store`, `--store-mod`, and `--jsonl` no longer match longer real
flags.

The remaining failures are one layer earlier. The gate does not yet define a
total `Markdown shell -> argv` boundary, so it silently skips documented
commands and loses option syntax and scope before `offers()` sees them.

## P1 — Multiline and command-substitution invocations are not extracted

`documented_invocations()` processes each physical line independently, calls
plain `.split()`, and requires `tokens[0]` to be exactly a known CLI.

Consequently the README's principal filing flow is not checked:

```sh
P=$(warrant propose --subject diff.patch --under $POL \
      --reason "utility fns needed" --actor me@host --key me.key)
```

Neither `P=$(warrant` nor the continuation line begins with `warrant`. The
same problem affects the documented multiline `warrant-mcp` invocation: the
gate observes only `warrant-mcp \` and none of `--store`, `--actor`, `--key`,
or `--effects`.

### Executed countervector

Changed the README command above from `--reason` to nonexistent `--reas`.

Observed:

```text
RELEASE SURFACE: ALL PASS
exit=0
```

The gate therefore accepts a broken command in the ten-minute path it is
intended to protect.

### Required closure

Parse fenced shell as logical commands, not physical lines:

1. join backslash continuations;
2. tokenize with shell-aware rules (`shlex`, not `str.split`);
3. find owned CLI invocations inside assignment/command-substitution wrappers;
4. preserve the ordered argv rather than extracting an unordered flag list.

Add permanent controls for the README assignment form and the multiline
`warrant-mcp` form.

## P1 — “Flag appears in help” does not mean the documented argv is accepted

The extractor removes everything after `=`:

```python
flag = token.split("=")[0]
```

and later searches combined top-level plus subcommand help, losing both option
value form and option scope.

### Executed countervector: unsupported explicit value

Changed the valid command to:

```sh
warrant ... verify --store-mode --json=true
```

Observed:

```text
release-surface gate: exit 0
actual CLI:          exit 2
warrant verify: error: argument --json: ignored explicit argument 'true'
```

### Executed countervector: global option in subcommand scope

Moved the global `--store` after the subcommand:

```sh
warrant verify --store ./evidence-pack/.warrants --store-mode --json
```

Observed:

```text
release-surface gate: exit 0
actual CLI:          exit 2
warrant: error: unrecognized arguments: ./evidence-pack/.warrants
```

The gate promises to ask whether the installed CLI accepts documented
subcommands and flags; these countervectors show it currently asks only whether
similar text occurs somewhere in a help transcript.

### Required closure

Preserve exact argv spelling and scope. The safest non-mutating check is to feed
each reconstructed invocation through the installed argparse surface with help
termination at the selected command, so parsing is exercised without performing
the operation. Alternatively, build a structured option model from top-level
and subcommand help, but it must retain:

- global-before-subcommand ordering;
- subcommand-local option scope;
- whether `--flag=value` is accepted;
- positional arity and the `--` delimiter.

The permanent matrix must call the same invocation validator used by CI, not
only `offers()`.

## P1 — A new user-facing documentation directory is silently outside the gate

The branch replaces a hand-maintained file list with a hand-maintained directory
list:

```python
DOC_ROOTS = [".", "demos", "profiles", "docs", "integrations"]
```

This still fails open when a new documentation area is added.

### Executed countervector

Added:

```text
guides/new-user-guide.md
```

containing:

```sh
warrant verify --definitely-not-a-real-flag
```

Observed:

```text
RELEASE SURFACE: ALL PASS (18 documented flags ...)
exit=0
```

Walk `ROOT.rglob("*.md")` and apply the explicit exclusion set, instead of
enumerating allowed roots. Then a new directory is covered by default and only
an intentionally named exclusion can remove it.

Add a discovery control using a synthetic, previously unseen directory.

## P2 — `warrant-go` scope contradicts the implementation

The source says:

```text
`warrant-go` ... is checked too when present
```

but `KNOWN_CLIS` contains only:

```python
{"warrant", "warrant-mcp", "warrant-anchor"}
```

The existing README `warrant-go verify --store-mode --json ...` invocation is
silently ignored. This may be correct for the wheel gate because the Python
wheel does not ship warrant-go, but then the comment and “every warrant*
invocation” claim are false, and checkout CI needs a separate explicit Go
surface check. Choose and document one scope; do not silently skip it.

## What holds

- `offers()` rejects prefix/superstring flag names as intended.
- Its eight-case local matrix is non-vacuous for that narrow function.
- The exact branch passes `git diff --check`.
- Checkout and installed-wheel entrypoints currently expose the extracted
  surface.
- The wheel test is hermetic with respect to Python imports.
- The publish gate runs before artifact upload and before the irreversible PyPI
  job.
- Version/tag equality and OIDC publishing remain unchanged.

No merge, push, release, adoption, or governance action was performed.
