# Codex review — release-surface gate, final bounded re-gate

Date: 2026-07-28

Reviewed:

- branch: `feat/release-surface-gate`
- head: `2f1fe3a533d0e6243fb1567debde6c8e18598584`
- parent: `55d682995819af193937b688624aa0d5aab8e6a4`

Scope was deliberately narrow: verify the previous wrapper-execution fix, attack
only the replacement static wrapper recognizer, run the normal surface gates,
and stop. This was not another expansion of the release-gate threat model.

## Verdict

**AMEND — one bounded, same-layer P1.**

The important previous defect is closed: the gate no longer executes installed
console wrappers while trying to validate them. However, the replacement AST
allowlist accepts a wrapper with an extra side effect, despite the stated
contract that only the minimal pip wrapper form is allowed.

After this exact issue is fixed and its countervector is permanent, this review
recommends closing the feature rather than opening another general
meta-verification cycle.

## What is now demonstrated

- The wheel, rather than installed metadata, is the provenance root.
- Installed module bytes are compared with the wheel.
- Declared entry points include the target function.
- Wrapper validation is static; the gate does not invoke the wrapper.
- The ordinary selftest, checkout, and fresh wheel/install paths remain green.

Observed on the reviewed head:

- selftest: `46/46`
- checkout surface: `25/25`
- fresh wheel plus installation: `25/25`
- `git diff --check`: clean

## P1 — the AST allowlist is not the claimed minimal wrapper grammar

`check_wrapper()` traverses every node below a top-level `if` with
`ast.walk()`. It recognizes the expected `sys.exit(main())`, and rejects some
calls whose callee is an `ast.Name`, but an arbitrary attribute call whose
attribute is not `exit` is not rejected.

This wrapper is therefore accepted:

```python
#!<venv>/bin/python3
import sys
from warrant_mcp import main
if __name__ == "__main__":
    sys.modules["os"].system("touch <marker>")
    sys.exit(main())
```

The countervector was exercised twice against the exact reviewed source:

1. Calling `check_wrapper()` directly returned no issues.
2. Replacing only the installed `warrant-mcp` wrapper in an otherwise genuine
   wheel installation still produced `ALL PASS (25/25)` and exit code 0.

The gate itself did **not** create the marker. That confirms that removal of
wrapper execution is real. Running the approved wrapper afterwards did create
the marker. Thus the remaining bug is specifically the static recognizer:
it certifies a wrapper containing behavior outside the promised pip form.

The same recognizer also does not structurally require the exact
`if __name__ == "__main__"` predicate and exact body shape. `ast.walk()` is
appropriate for finding forbidden syntax, but is unsafe as an acceptor for a
small closed grammar.

### Required bounded closure

Validate the wrapper as an exact structure, not as a collection of locally
acceptable nodes:

1. exact allowed imports, without extra imported names or aliases;
2. exact `from <declared module> import <declared function>`;
3. exactly one main guard with an empty `else`;
4. an exact guard predicate equivalent to
   `__name__ == "__main__"`;
5. only the known optional pip `argv[0]` normalization statement, if supported;
6. one final exact `sys.exit(<declared function>())`;
7. no additional statement, expression, call, decorator, handler, or branch.

The countervector above must be a permanent negative test. The test should also
assert that no marker is created while the gate runs.

## P2 — keep the CLI-family coverage explicit

The selftest has positive wrapper coverage, but the surface corpus should retain
explicit valid cases for prior-less `accept` and `reject`, since their
post-parse invariant differs from the prior-bearing forms. This is coverage
hardening, not a merge blocker for the wrapper fix.

## Stop boundary

This finding is in the exact layer under review and is a small mechanical
closure, so accepting it as residual debt would weaken the gate's current
claim. Fix it once.

Afterwards, run:

- the new attribute-call countervector;
- the existing wrapper selftests;
- checkout validation;
- fresh wheel/install validation;
- the normal warrant suite.

If those pass, land the feature. Do not require another open-ended adversarial
round over the checker itself. Any newly imagined environment-level threat
outside the declared wheel/install/wrapper model should be recorded as a
known boundary or proposed as a separate feature with its own value argument.

