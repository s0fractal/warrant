# Release-surface gate — independent Codex re-gate 6

**Reviewed exact head:** warrant `feat/release-surface-gate` at
`55d682995819af193937b688624aa0d5aab8e6a4`, based on
`af97ff08a5c46e7c28c354b78a09f68a7147b011`.

**Scope:** wheel-as-provenance-root closure, installed module binding, exact
entry-point targets, generated console-script behavior, and side-effect safety.

**Verdict:** **AMEND**

The provenance architecture is now correct:

- `--bin` without `--wheel` refuses;
- module hashes and full `module:function` entry points come from the external
  wheel archive;
- installed modules are checked against wheel bytes, not installed `RECORD`;
- changing a module and its installed `RECORD` together no longer helps;
- `warrant_mcp:not_main` is rejected;
- checkout, fresh wheel/install, 39-case selftest, and the full Python/Go suite
  are green.

One executable seam remains. The installed console wrapper is not bound to the
wheel or to the verified entry-point target. Running it with `--help` proves
only that some executable can print the command name and exit zero. It also
reintroduces execution side effects into a gate that was deliberately changed
to parser-only.

## P1 — A fake side-effecting wrapper can impersonate `--help`

`check_installation()` accepts a console script when:

```python
script exists
script is executable
script --help exits 0
command name appears anywhere in stdout/stderr
```

There is no relationship between the bytes of that script and the wheel's
trusted declaration `warrant-mcp = warrant_mcp:main`.

The comment says:

```text
--help exits before any work
```

That is true only after the genuine wrapper has imported the genuine module and
reached argparse. Wrapper code and module top-level code execute before argparse
sees `--help`. Therefore safety is not “by construction”.

### Executed countervector against a real wheel/install

Built and installed exact-head `0.5.0`, then replaced only the generated
`<venv>/bin/warrant-mcp` with an executable Python script that:

1. creates an absolute-path marker file;
2. prints `usage: warrant-mcp`;
3. exits zero for every argv;
4. never imports or calls `warrant_mcp:main`.

The external wheel, entry-point metadata, and installed parser modules remained
untouched.

Observed:

```text
RELEASE SURFACE: ALL PASS (25/25)
gate exit: 0
marker created by the gate: yes

fake warrant-mcp <documented argv>:
  usage: warrant-mcp
  exit 0
  no proxy/sealing behavior executed
```

This is both a false binding and a side effect caused by the validation step.

### Required closure

Do not use free-form `--help` output as proof of wrapper identity.

Two reasonable closures:

1. **Static trusted-wrapper validation.** Parse the generated script and accept
   only the minimal pip console-wrapper structure:
   exact interpreter/shebang policy, import of `main` from the wheel-declared
   module, and direct `sys.exit(main())`, with no additional executable
   statements. Then an optional `--help` execution is about the verified wrapper,
   not arbitrary code.

2. **Trusted install receipt.** Immediately after pip install, verify the
   generated script against its pip-written `RECORD` hash and exact wheel
   entry-point metadata, explicitly treating that record only as the trusted
   installer's receipt for generated scripts—not as provenance for wheel files.
   This is weaker against a party that can rewrite both script and installed
   record, so state that threat boundary.

In either case run any dynamic probe with a sanitized environment, bounded
timeout, controlled cwd, and no inherited `PYTHONPATH`/Python startup variables.
The safest route is static wrapper validation plus the existing path-loaded
`parse_cli()`; it may make dynamic wrapper execution unnecessary.

Add a permanent countervector whose script prints the expected command name,
exits zero, performs a side effect, and never dispatches to the declared
function. It must fail before execution and must not create the marker.

## P2 — The new wheel tests miss the successful impersonator

`_wheel_root_checks()` tests a console script that exits `99`. That proves the
exit-code check, but not identity. It does not test a wrong script that returns
the exact expected observable (`exit 0` plus command name).

The helper also calls its synthetic zip/tree a “real wheel plus a real
installation”, but it is not installed by pip and contains no normal
`WHEEL`/`RECORD`; its scripts are hand-written shell fixtures. That is fine for
unit-testing `inspect_wheel()`/`check_installation()`, but the final wrapper
control should use an actual pip-built and pip-installed wheel because generated
script form is precisely the subject.

The fast selftest still omits explicit prior-less `accept` and `reject` cases
even though the implementation is currently correct.

## Re-gate target

1. A fake executable that prints valid help and exits zero is rejected without
   being executed.
2. The rejected wrapper cannot create an absolute-path marker.
3. The genuine pip-generated wrappers are bound to the exact wheel-declared
   `module:main` targets.
4. All four `warrant.parse_cli` invariants have explicit controls.
5. Wheel-root/module/metadata checks, checkout, fresh install, old release, and
   agreement suites remain green.

Do not merge `feat/release-surface-gate` or its dependent
`feat/adoption-surface` on this head.
