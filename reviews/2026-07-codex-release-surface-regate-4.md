# Release-surface gate — independent Codex re-gate 4

**Reviewed exact head:** warrant `feat/release-surface-gate` at
`e434d5a71475965a46c556c015708730b9a03a32`, based on
`f921c4ad48d8c856573ae87aa175ae5750c7500f`.

**Scope:** generalized `parse_cli` closure, distribution ownership, installed
console-entry-point binding, and non-vacuous permanent controls.

**Verdict:** **AMEND**

The CLI-contract half of the previous review is now correctly closed:

- `propose`, prior-less `accept`/`reject`, and `supersede` usage invariants live
  in `warrant.parse_cli()`;
- the checker and `main()` use that same pure function;
- all four invalid argv forms are rejected by the real validator;
- a valid `propose --subject ...` remains accepted;
- path-qualified valid and invalid commands now differ for the right reason.

The exact-head 26-case selftest, checkout surface gate, freshly installed wheel
surface gate, and full Python/Go agreement suite are green.

The artifact half is not yet closed. The code asks the not-yet-authenticated
module to share the same output channel used to authenticate it, accepts a
lookalike distribution name by prefix, and treats arbitrary non-executable text
as an installed console script.

## P1 — The untrusted parser can forge its own ownership result

The child process writes its computed owner to stderr:

```python
sys.stderr.write("MODULE-DIST " + (owner or "<none>") + "\n")
```

then imports/runs the candidate's `parse_cli()`. The parent scans all stderr
lines and keeps the last matching line:

```python
elif ln.startswith("MODULE-DIST "):
    dist = ln[len("MODULE-DIST "):].strip()
```

Therefore the module whose ownership is being established can print another
`MODULE-DIST` line after the trusted probe. Authentication evidence and
attacker-controlled application output share one unauthenticated protocol.

### Executed countervector

Created a venv with:

- no `warrant-verify` distribution;
- three modules injected through a normal `.pth`;
- each module exposing:

  ```python
  def parse_cli(argv=None):
      print("MODULE-DIST warrant-verify 9.9", file=sys.stderr)
  ```

- three ordinary non-executable text files in `bin/`, each merely mentioning
  the expected module name.

The trusted scan emitted owner `<none>`. Each fake `parse_cli()` emitted the
forged owner afterward, which replaced it in the parent.

Observed:

```text
warrant-verify distribution: ABSENT
all three “scripts”: mode -rw-r--r--
RELEASE SURFACE: ALL PASS (25/25)
exit 0
```

### Required closure

Make the identity decision inside trusted probe code **before** importing or
calling the candidate module. On mismatch, exit with a dedicated nonzero code;
do not send identity data through a channel the module can also write.

Prefer an interpreter started without site initialization (`-I -S`) and inspect
the target site-packages explicitly. A `.pth` file can execute code during
normal site initialization even under `-I`.

Only after exact distribution/file verification succeeds should the probe add
the verified site-packages directory and import the parser.

Add this exact forged-`MODULE-DIST` venv as a permanent integration
countervector.

## P1 — A lookalike distribution name satisfies the owner check

The parent accepts:

```python
dist.startswith("warrant-verify")
```

The child serializes owner as `"Name Version"`. Consequently
`warrant-verify-evil 1.0` is accepted as `warrant-verify`.

### Executed countervector

Created a second venv containing only:

- dummy parser modules;
- a minimal `warrant_verify_evil-1.0.dist-info` whose `RECORD` claims those
  modules;
- metadata `Name: warrant-verify-evil`;
- the three textual pseudo-scripts.

No output spoof was used.

Observed:

```text
installed warrant-like distributions:
  [('warrant-verify-evil', '1.0')]

RELEASE SURFACE: ALL PASS (25/25)
exit 0
```

### Required closure

Resolve the expected distribution directly:

```python
distribution("warrant-verify")
```

and compare canonicalized names for equality, never prefix. Require each parser
file to be an exact member of that distribution's `RECORD` with a nonempty
supported hash, and verify the installed bytes against that hash.

If the publish gate is intended to attest to a particular built wheel rather
than merely an installed distribution, pass the wheel path/digest to the gate
and bind the installed `RECORD` to that wheel's `RECORD`.

Add `warrant-verify-evil` as a permanent negative control.

## P1 — Arbitrary non-executable text passes as a console script

`check_entry_points()` currently requires only:

```python
script.exists()
mod in script.read_text()
```

It does not require a regular executable file, inspect distribution entry-point
metadata, verify the installed script against `RECORD`, or execute a safe
`--help` probe.

### Executed countervector against a real wheel

Built and installed the exact `0.5.0` wheel, then replaced only
`<venv>/bin/warrant-mcp` with:

```text
this is not executable and does not dispatch; warrant_mcp appears only as text
```

The replacement had mode `-rw-r--r--`.

Observed before and after:

```text
RELEASE SURFACE: ALL PASS (25/25)
exit 0
```

Thus the “exists and dispatches” claim is not what the code checks.

### Required closure

For each expected command:

1. require exact entry-point metadata:
   `warrant = warrant:main`,
   `warrant-mcp = warrant_mcp:main`,
   `warrant-anchor = warrant_anchor:main`;
2. require the installed path to be a regular executable file;
3. verify its bytes against the hash recorded by the exact distribution's
   `RECORD` (pip records the generated scripts there);
4. optionally invoke the installed script with `--help` in a sanitized,
   bounded environment to prove the wrapper reaches its entry point without
   dispatching a command body.

Add permanent controls for a missing script, a non-executable script, a script
whose body merely mentions the module, and a wrong entry-point mapping.

## P2 — Permanent controls still cover less than the closure claim

The implementation now correctly rejects prior-less `accept` and `reject`, but
the 26-case selftest contains only `propose` and `supersede` invariant cases.
Removing `accept`/`reject` from the guarded command tuple would leave selftest
green.

The diff also contains no permanent integration test for:

- fake/no-distribution venv;
- lookalike distribution;
- missing/non-executable/replaced console script.

Those cases were manually demonstrated, but this review cycle has repeatedly
established that manual evidence is not regression protection.

Add the two missing argv cases to the fast selftest and put artifact
construction/mutation cases in a separate wheel-integration test run by the
same CI/publish job as the gate.

## Re-gate target

1. Artifact identity is decided before candidate-module code runs and cannot be
   changed by its output.
2. Only the exact canonical `warrant-verify` distribution is accepted.
3. Parser modules and console scripts are exact, hash-verified members of that
   distribution.
4. Console entry-point metadata, executability, and expected mapping are
   checked.
5. All forged-output, lookalike-distribution, fake-script, missing-script, and
   four `warrant.parse_cli` controls are permanent and non-vacuous.
6. Exact old-wheel, hostile-`PYTHONPATH`, checkout, fresh-wheel, and agreement
   results remain green.

Do not merge `feat/release-surface-gate` or its dependent
`feat/adoption-surface` on this head.
