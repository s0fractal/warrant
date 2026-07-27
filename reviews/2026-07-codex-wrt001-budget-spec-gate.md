# WRT-001 §8 deterministic budget — independent adversarial gate

Date: 2026-07-27  
Branch: `wrt-001-budget-spec` (`10e5346`, one commit over `master`)  
Scope: normative §8, its interaction with the runtime/check schema and deferred
ordering, plus the inherited item-0 claims repeated by this proposal  
Verdict: **AMEND — GOOD BUDGET DIRECTION, BUT THE CURRENT TEXT DOES NOT YET
DEFINE A SAFE OR CROSS-IMPLEMENTATION-EXACT METER**

The proposal makes several correct choices: the ceiling is content-addressed,
cost is integer-only, exhaustion is not a verdict, over-budget execution must
stop, and exact/one-under/cross-implementation vectors are explicitly required.
The issues below are seams in that contract, not objections to adding a budget.

## Reproduced baseline

- `python3 impl/warrant.py selftest`: `SELFTEST: ALL PASS`.
- `tests/agree_check.sh`: differential 45/45, settlement all agree,
  runtime-hook all pass, pedantic 15/15.
- Sigma `tools/test-all.sh`: `TEST-ALL: ALL GREEN`.
- All three Sigma precedent probes run successfully.
- The Sigma budget sketch reports deterministic cost `4701`; its half-budget
  case returns exhausted and its double-budget case passes.

Green suites do not exercise the findings below.

## Findings

### [P1] The committed ceiling is unavailable when the first bounded read is required

Section 1 puts `budget` inside the check blob. Section 8 then requires every blob
read—including the check blob—to use:

```text
remaining = check.budget - cost
```

But the verifier cannot know `check.budget` until it has already resolved,
materialized, authenticated, and parsed that check blob. A malicious local CAS
file or remote response under the named check hash may therefore be arbitrarily
large before the committed meter exists. This is a circular bootstrap, and the
prototype demonstrates it by calling `read_bytes()` on the check path before
parsing `budget`.

Close the bootstrap explicitly. Two honest designs are:

1. commit `budget` directly in the Warrant reason and require the check blob to
   repeat/match it; or
2. define a small protocol-level `WAVE_CHECK_MAX_BYTES` derived from the exact
   closed check schema, read at most that bound plus a sentinel, authenticate and
   parse, and only then enter the citation's meter.

A local operator cap alone is not the committed ceiling and must not silently
be substituted for it.

### [P1] The bounded-read arithmetic exceeds its own cost ceiling

Blob cost is `1 + n`. If `remaining = R`, the largest affordable blob has
`n = R - 1`. Section 8 instead permits reading `R + 1` bytes. That can
materialize two bytes beyond the largest affordable action before reporting
exhaustion.

The bounded probe should read at most `R` bytes:

- fewer than `R` bytes means `1 + n <= R` and the blob fits;
- exactly `R` bytes is the sentinel proving the blob is already unaffordable
  (whether its total size is `R` or larger);
- `R == 0` exhausts before any read.

Specify whether filesystem metadata/EOF probing is trusted; do not describe an
`R + 1` materialization as stopping before cost exceeds the ceiling.

### [P1] The meter does not bound Book III selection work

The cost function charges one unit per candidate handed to `select()`.
Book III's current `select()` sorts candidates and may compare the Warrant
`actor.id` field. Warrant permits an arbitrary nonempty actor string; its bytes
are in the record body, not in the assertion blob charged by §8.

Countervector: two accepted candidates use an actor-order policy and actor IDs
with an attacker-sized common prefix. The specified wave cost is unchanged
apart from two record/candidate units, while comparison work and memory grow
with that prefix. With many candidates, sorting also performs more than linear
comparisons. Instrumenting the current selector on shuffled candidates produced:

```text
16 candidates   ->   64 comparisons
64 candidates   ->  370 comparisons
256 candidates  -> 2001 comparisons
1024 candidates -> 9960 comparisons
```

The same gap exists when the runtime copies or inspects unbounded Warrant body
arrays: `+1 per record` is not a size bound.

Either:

- meter canonical record bytes plus every comparator/code-point operation and
  pin the selection algorithm; or
- add profile-level size/cardinality limits and use a selection algorithm whose
  work is demonstrably bounded by the charged units.

The budget must dominate every input dimension that the wave runtime touches,
not only CAS assertion bytes.

### [P1] “Exact cost” is not yet a function of the specification

The text names cost categories but not the billable event trace needed for two
implementations to agree:

- is one active record charged once, or once in each snapshot/cardinality/
  projection/assertion pass?
- is the same blob hash charged once, once per semantic role, or once per
  accessor call, and may an implementation cache it?
- what is charged for a missing reference, wrong digest, noncanonical bytes, or
  failed validation?
- what WarrantID traversal order fixes early-error versus early-exhaustion
  precedence?
- is the already-shared settlement-context construction logically charged to
  every citation, even though it completed before dispatch?

Most importantly, item 5 itself says the metered set becomes stable only after
items 1–2 define authorized effective lifecycle and R1. Therefore §8 can
currently specify a **cost framework**, but cannot yet truthfully be marked
“SPECIFIED” as an exact cross-implementation function.

Define a small-step pseudocode machine or a canonical ordered event stream after
items 1–2 freeze membership. The vectors should compare every event/cumulative
cost, not only the terminal integer.

### [P1] Item 0's claimed I-JSON parity still excludes escaped lone surrogates

The inherited item-0 text claims one strict trust/pinned-input domain. Raw invalid
UTF-8 is now rejected, but JSON escape sequences can still create non-Unicode
scalar strings.

With exact hash-pinned `genesis.json` bytes containing a valid root and two keys
`"\uD800"` / `"\uD801"`:

```text
Python: root adopted, 0 warnings
Go:     duplicate-after-U+FFFD replacement, root not adopted
```

With an empty store and trust config:

```json
{"actors":{"\uD800":[],"\uD801":[]}}
```

I reproduced:

```text
Python: exit 0, clean
Go:     exit 1, settlement trust config unavailable
```

This is inside the deliberately narrowed item-0 scope. Recursively reject lone
surrogate code points after decode in both implementations (while accepting
valid surrogate pairs), and add trust plus pinned-genesis vectors.

### [P2] Local refusal policy is mixed with deterministic semantics

The text calls the ceiling `min(check.budget, local_cap)`, then says
`check.budget > local_cap` is rejected without execution. Those are different
rules. It also says implementations agree exactly while making the cap
environment-configurable.

Mirror the already-honest `ski@v1` rule in `SPEC.md`:

- semantic cost and `check.budget` are portable;
- `local_cap` is verifier willingness policy;
- if `budget > local_cap`, that verifier refuses and reports `unverified`;
- differently configured verifiers may differ on execution availability, while
  implementations that do execute must agree on exact cost/verdict.

## Gate recommendation

Keep §8 as **DRAFT COST FRAMEWORK**, not specified/frozen. The next revision
should:

1. solve check-budget bootstrapping;
2. correct the bounded-read arithmetic;
3. meter or bound record/string/selection work;
4. define a canonical event trace after items 1–2;
5. separate local refusal from portable semantics; and
6. close the escaped-surrogate item-0 vector.

No governance adoption or merge of the budget proposal yet. The overall
architecture—committed budget, fail-closed exhaustion, fixed-version cost
semantics—is worth keeping.
