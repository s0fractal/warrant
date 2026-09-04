# Replay this pack cold

You have a checkout of this repository and nothing else installed. You want to
know whether the public `warrant` command, built from *this* commit, reproduces
the per-record results this pack promises — and whether it refuses when it
should. One command:

```sh
bash demos/air-canada/replay-clean.sh
```

It builds a wheel from the checkout, installs it into a fresh virtual
environment, copies the pack and the frozen vector into a temporary directory,
and runs the replay driver from there. The checkout is neither the working
directory nor on any import path while the CLI runs. Nothing is downloaded from
GitHub Releases: a published wheel may be older than this tree, and replaying it
here would say nothing about this commit.

Network is needed twice unless a cache serves it — the isolated wheel build
fetches `setuptools`, and installing the wheel fetches `cryptography`. Neither
touches the evidence. If you already have a wheel built from this commit, hand
it over instead:

```sh
WARRANT_REPLAY_WHEEL=dist/warrant_verify-0.9.0-py3-none-any.whl bash demos/air-canada/replay-clean.sh
```

## What the frozen vector is

[`replay.json`](replay.json) freezes four things, and the driver refuses to run
if any of them is not what it finds:

- **exact input bytes** — a SHA-256 for each of the 16 files in `pack/`, and
  the rule that no other file may be present;
- **the evaluator** — `ski@v1` is executed by `sigma_glyph_v05.py` at digest
  `80299d68…`; the installed module is hashed before anything runs;
- **the profile** — a `warrant-verify` installation whose `warrant.py` and
  evaluator import from the installation prefix, no `SIGMA_GLYPH` override, no
  differential flag, no `PYTHONPATH`;
- **the per-record vector** — for each of the two records, the findings
  `warrant verify --json` must emit *for that record* at base and at settlement
  grade, and for the refusal, what `warrant check` must print.

The expected result, per record:

| record | decision | `verify --json` (base) | with `trust.json` (settlement) | `check` |
| --- | --- | --- | --- | --- |
| `7d8f2e7d…` | propose by `chatbot@aircanada` | 1 WARN: binding unverified (no keyring) | no findings | — |
| `9084cd23…` | reject by `policy-guard@aircanada` | 1 WARN: binding unverified (no keyring) | no findings | `pass  result=65cd957f…  atp_spent=17` |

There is deliberately no row for "the pack". The CLI reports per record and
so does the replay; its last line is a count of records and controls, not a
verdict.

## The controls, and what each one is for

Every control runs on a fresh copy of the pack, through the same `warrant`
command — not through a helper that bypasses the CLI.

| control | what is done | what must happen |
| --- | --- | --- |
| `verdict-fail` | a second check blob, at its *true* address, same term, wrong `expect` | `check` prints `fail  result=65cd957f…  atp_spent=17`, exit 1. The evaluator ran and disagreed; the positive `pass` is therefore not vacuous. |
| `evaluator-absent` | `SIGMA_GLYPH` names a directory that does not exist | `check` refuses `runtime unavailable`, prints no verdict; base `verify` reports the reject record `ski@v1 unverified: runtime unavailable`; settlement `verify` fails with one global `settlement requires the pinned Σ-GLYPH evaluator`. Setting `WARRANT_SIGMA_DIFFERENTIAL=1` changes nothing. No fallback to the bundled engine. |
| `evaluator-broken` | `SIGMA_GLYPH` names a `sigma_glyph.py` that raises on import | same as above; a traceback fails the control. |
| `cas-root` | the check blob `b423b6a8…` rewritten in place under its own name | `check` refuses `content does not match its address`; `verify` reports an ERR on the citing record at both grades. |
| `cas-nested` | the thunk `962c8974…` (`term → left → right`) rewritten in place | `check` refuses with the same path-free reason; base `verify` reports a WARN `ski@v1 unverified: …` and exits 0; settlement `verify` reports an ERR and exits 1. |

## What this does not establish

- **Base grade does not fail closed on an unexecutable reason.** A nested
  address lie, or a missing evaluator, is a per-record `WARN` and exit 0 at
  base grade — "could not re-run" is not "false" (SPEC §6). Only settlement
  grade turns it into an ERR. The replay freezes both behaviours; it does not
  change either.
- The nested control proves detection for *this* term, whose reduction forces
  the mutated thunk. It is not a proof about thunks a term never reaches.
- `why` is checked by exit status only.
- The keyring is inside the pack, so settlement-grade "bound" means consistent
  with the file you were handed.
- One specimen, one locally built artifact. Not an independent review, not a
  conformance grade, not a statement about any published release.

## Reading a refusal

`REPLAY: REFUSED <kind>: …` with exit 3 means the run could not be performed as
frozen. It is not a pass and not a finding against the pack:

- `environment` — no `warrant` command, no interpreter beside it, or a command
  that did not answer;
- `artifact` — the modules would import from outside the installation (a
  sibling checkout on the path), `warrant-verify` is not installed there, or
  the evaluator's bytes do not hash to the frozen pin;
- `inputs` — a pack file is missing, changed, or something extra is present.

`REPLAY: FAIL` with exit 1 means the installed CLI did run and printed something
other than the frozen vector. That is the result worth reporting.

## Keeping the freeze honest without a network

`python3 tests/evidence_pack.py` (run by `tools/check.py` and CI) holds
`replay.json` to the tree offline: every frozen digest against the file, the
evaluator pin against `SKI_EVALUATORS`, and the per-record vector against what
this implementation produces. A pack rebuilt with different bytes, or an
evaluator pin that moved, fails there first.
