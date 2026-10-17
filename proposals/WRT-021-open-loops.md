# WRT-021: Open loops: goals, commitments and obligations, and the records that close them

**Status:** DRAFT, 2026-10-17. Written by Claude at the owner's request. Nothing is decided,
nothing is implemented, and nothing in SPEC.md or `warrant verify` changes. The owner
decisions this draft needs are listed in §9.

## 1. Why

Warrant records the past: a decision that was taken, under a policy, for reasons, with
evidence. Several things a decision exists *for* have no record of their own:

- the **goal** it was meant to serve;
- the **commitment** or **obligation** it was meant to discharge;
- the **intent**, the outcome its author wanted it to reach.

Today these live in chat, in PR descriptions, in review files outside any repository, and in
"done" columns. Three practical consequences follow, and all three were observed this month.

1. **Two agents cannot work without the owner as a relay.** Between Codex and Claude, a review
   round is already shaped like warrant. A finding is raised against an exact SHA, with a
   reproducer (for example `repro.py` for warrant #131 at `cda525e`). It is answered by a fix
   SHA, a regression and a mutant, and then accepted or amended. But the round is carried by
   pasting text through the owner, and the evidence sits in `~/Documents/Codex/...`. Nothing
   records which findings are still open, and nothing closes a finding except someone saying so.
2. **A loop is closed by assertion, not by its condition.** "Fixed" closes a finding whether or
   not the regression fails on the old head for the stated reason.
3. **Nobody can ask what is current.** `warrant why` walks backwards from a decision. Nothing
   answers forwards questions: which obligations are open, which decisions rest on something
   that has since been superseded, or what a given actor still owes.

The proposal adds one missing kind of object, the **open loop**. It adds one rule: **a record
closes only the loop whose closure condition it discharges**. It also adds the queries that make
"the present" computable as the frontier between closed decisions and open loops.

## 2. What this rests on

| Source | What is taken | What it is used for here |
|---|---|---|
| manifesto `quotes/Monday/chat-0001/0040_Monday.md` (manifesto `a148caf`), "Obligation as open temporal loops" | obligation = memory with an open edge (§1–5); completion is settlement, not stopping (§10); abandonment, release and failure are legitimate closures (§11, §47, §48); persistence authority (§13); orphan tasks and parent provenance (§20–21); closure is typed, overclaiming is unauthorized closure propagation (§30–31); explicit closure predicate `C_O` (§36–38); one-shot / recurring / persistent-invariant loops (§39–40); expiry and revalidation, stale obligations (§44–46); asymmetric completion (§50–51) | the record kinds (§4), the closure kinds (§5), the typed-closure rule (§6.1) and the derived states (§6.2) |
| same file, §29 | "Warrant = portable settlement evidence for a proof/justification open loop" | the boundary: a loop is **not** a warrant; a warrant is what closes one (§3) |
| `0041_Monday.md`, "Desire, goal, value, duty, purpose, meaning" | Goal = a future state granted planning relevance (§3); Commitment = Goal + PersistenceAuthority (§4); obligation is deontic, not teleological (§13–14); purpose generates obligations and is non-terminal (§16–17, §31); the value stack is a typed DAG, not a tree (§21) | the four kinds and their persistence rules (§4); the `serves` edges form a DAG |
| `0003_Monday.md`, "Reasoning fabric" | Grounding / Claim / Reachability / **Intent**; intent sets a target region and proves nothing; backward and forward cones; the forward attack ("C true, desired D false") | intent as an edge, not a node (§4.3); the forward query and the intent-gap report (§7) |
| `0010_Monday.md`, "Time as geometry of the irreversible" | the present is the active surface of settlement; it is local to an agent | the `frontier` query (§7) is per actor |
| SPEC.md §2 (body), §7 (settlement, tunnel, novelty) | the existing body fields and settlement semantics | §8: the encoding uses the existing body; no new field is required in the first stage |
| REDESIGN-1 draft (warrant #131, `redesign/p3-p4-assessment`, head `e2f679c`) | PolicyProgram (a rule with typed params, no fact values); FactSet; recipient profile; closed-vocabulary assessment axes; `novelty()` | a closure predicate **is** a PolicyProgram with an obligation name; closure is assessed like a decision, with a closed vocabulary |
| WRT-010 (fact provenance) | facts derived from earlier decisions, with a chain | a closure may cite derived facts |
| WRT-017 (revocation), decided A | an operation the text specified and no implementation performed | lesson: every closure kind ships with an implementation and a vector, or it is not specified |
| AGENTS.md; `history/AUTONOMY-ENVELOPE-0.1-RETIREMENT.md` | records carry no authority they were not given; the retired envelope was about merge eligibility | §3: closing a loop grants no merge, release or publication authority |

The manifesto notes are ideas, not normative sources (manifesto's own rule: they are not graded
by use). Each idea taken from them is restated here as a rule with a test, and only the rule
binds.

## 3. Boundaries

- **A loop is not a warrant.** It records that an actor opened a loop, of which kind, under which
  closure condition and with which persistence. It is never verified as "true", "right" or
  "achieved". Verification answers only whether the loop is well formed, signed, open or closed,
  and closed by what.
- **Warrant still does not take decisions** (SPEC §10). A goal record is a declared intent, not
  a plan. Nothing here schedules, prioritizes or chooses.
- **Closing grants nothing.** That a review obligation is DISCHARGED does not authorize a merge.
  Merge, publication and release stay with each repository's own governance.
- **Sigma stays a separate layer.** Sigma evaluates a closure predicate (ski@v1, or the
  sigma-resume kernel). Warrant records the loop, the closure and the evidence. Neither absorbs
  the other.

## 4. Record kinds

### 4.1. The loop blob, `warrant.loop@draft-1`

```json
{
  "schema": "warrant.loop@draft-1",
  "kind": "goal | commitment | obligation | purpose",
  "shape": "one_shot | recurring | invariant",
  "statement": "<≤200 code points, for humans; never evaluated>",
  "owed_to": ["<actor id>", "..."],
  "serves": ["<loop WarrantID>", "..."],
  "closure": {
    "predicate": "<PolicyProgram blob hash> | null",
    "facts": ["<named slot>", "..."],
    "closers": ["<actor id>", "..."],
    "requires_beneficiary": true
  },
  "persistence": {
    "release_by": ["<actor id>", "..."],
    "expires_ts": 0,
    "revalidate_every": 0
  },
  "assumes": ["<WarrantID or blob hash>", "..."]
}
```

Every field is closed-vocabulary or typed, and unknown fields make the blob invalid, as in SPEC
§2.

### 4.2. The four kinds

| Kind | Source | Who may close it without discharge | Can it be DISCHARGED? |
|---|---|---|---|
| goal | 0041 §3 | its author, freely (ABANDONED) | yes, by its predicate |
| commitment | 0041 §4 | only `release_by` (RELEASED); the author alone cannot abandon it | yes |
| obligation | 0040 §2–6, 0041 §13 | `owed_to` or `release_by` (RELEASED) | yes; with `requires_beneficiary`, an `owed_to` actor must accept the discharge (0040 §50–51) |
| purpose | 0041 §16–17, §31 | `release_by` only | **no**: a purpose is non-terminal. It is a generator: loops that `serve` it are its output. |

Desire, value and meaning (0041) are **not** record kinds. A desire has no authority (0041 §2).
A value shapes the geometry and is not a target (0041 §6). That role is already played by
policies in `under`. Meaning is not a layer (0041 §21–23). Leaving them out is deliberate.

### 4.3. Intent is an edge, not a node

Following 0003, intent is the target region a decision is meant to reach, and it proves nothing.
In this proposal intent is the `serves` edge:

- an ordinary decision cites the loops it is meant to advance;
- a loop cites its parent loops.

A decision that `serves` a loop it does not close is legitimate: it advances the loop without
closing it. §6.1 forbids the inverse.

### 4.4. Shapes

`one_shot` closes once. A `recurring` loop is never DONE. Each period needs a REVALIDATED
record, and a missed period makes it LAPSED (0040 §39–40, §45). An `invariant` loop is a
standing condition that holds while its predicate holds; a FALSE replay makes it BREACHED.
Maintenance is therefore not an unfinished project (0040 §40).

## 5. Closure kinds

| Closure | Who files it | What it must carry | 0040 |
|---|---|---|---|
| DISCHARGED | a `closers` actor (plus an `owed_to` accept if `requires_beneficiary`) | a check whose replay of `closure.predicate` over the named facts is TRUE; with `predicate: null`, the closer's attestation only, and the derived state says ATTESTED, not DISCHARGED | §10, §36–38 |
| RELEASED | `release_by`, or `owed_to` for an obligation | a reason | §48–49 |
| ABANDONED | the author, goals only | a reason | §11 |
| FAILED | a `closers` or `release_by` actor | evidence that the predicate is unreachable or the obligation impossible, plus optionally a successor loop | §47 |
| TRANSFERRED | the author together with the receiving actor | a successor loop with `prior` pointing at this one | §10 |

There is no EXPIRED record. Expiry is computed from `expires_ts` against the verifying context's
time (§6.2), because "time passed" is not a decision anyone makes (0040 §44–45).

## 6. Rules

### 6.1. Typed closure (the central rule)

A closure record closes **exactly** the loop named as its subject, and only with the closure kind
its evidence supports.

- A DISCHARGED claim without a replayed TRUE predicate is reported as **OVERCLAIMED** and closes
  nothing. Neither does one filed by a non-closer, or one missing a required beneficiary accept.
- **Closure never propagates.** Discharging a child does not close the parent it `serves`, even
  when it is the parent's only child. The parent closes only by its own predicate or its own
  release. This is 0040 §31, "Overclaiming = unauthorized closure of downstream proof
  obligations", turned into a verifier rule.

### 6.2. Derived states (computed, never stored)

| State | When |
|---|---|
| OPEN | well formed, no valid closure, not expired |
| CLOSED(kind) | a valid closure of that kind; ATTESTED is distinct from DISCHARGED |
| OVERCLAIMED | a closure record whose kind its evidence does not support (it closes nothing; the loop's state is computed without it) |
| CONTESTED | two valid, incompatible closures, e.g. DISCHARGED and FAILED (analogous to WRT-016: scoped to the loop, not the store) |
| STALE | something in `assumes` has been superseded, or the loop's evidence slot names a fact whose provenance is now DERIVATION_MISMATCH (0040 §46) |
| ORPHANED | every loop it `serves` is closed by RELEASED, ABANDONED or FAILED (0040 §20); a DISCHARGED parent does not orphan its children |
| EXPIRED / LAPSED | `expires_ts` passed with no revalidation; a recurring loop missed a period |
| BREACHED | an invariant loop whose predicate replays FALSE |

### 6.3. Opening needs authority

Opening is a signed record `under` a policy. The policy says who may open which kinds against
whom. An obligation `owed_to` B that names A as a closer is opened by A, or by B if A accepts it.
Nobody can create an obligation for someone else unilaterally (0040 §13–15, "coercively created
obligation suspicious").

## 7. Queries

- **`frontier(actor)`**, the present (0010): loops where the actor is author, closer, `owed_to`
  or `release_by` and that are OPEN, STALE, ORPHANED, EXPIRED or CONTESTED, together with
  candidate closures not yet accepted. It is local to one actor.
- **`dependents(id)`**, the forward cone (0003): loops that `serve` a given loop, decisions that
  cite it, and loops whose `assumes` include it. `why` already gives the backward cone.
- **`stale()`**: everything §6.2 marks STALE or ORPHANED, each with the chain of causes. This is
  the decision-graph analogue of cap-lab's REPLAYED to STALE after an edit.
- **intent gap**: for a closed loop, the parent loops it `serves` that are still OPEN. Discharging
  "encrypted" leaves "secure" open, and the report says so (0003's forward attack).

## 8. Encoding: a profile first, the core later

**Stage 1 (proposed): a profile over the existing body.** No SPEC change.

- **Opening:** `propose`, with the loop blob as `subject.hash`, `under` = the opening policy, and
  `prior` = the loops it serves.
- **Closing:** `accept` (DISCHARGED, ATTESTED, beneficiary accept) or `supersede` (RELEASED,
  ABANDONED, FAILED, TRANSFERRED), with `prior` = the opening record. The closure kind is a
  `warrant.closure@draft-1` blob in `evidence`. For DISCHARGED, the predicate's check is in
  `because`.
- **The checker:** a profile checker (`impl/loops.py`) computes §6.2 and §7, in the same way that
  `impl/assessment.py` computes the redesign axes, and reports in a closed vocabulary.
  `warrant verify` is unchanged: a store full of loops verifies exactly as before.

**Stage 2 (only if stage 1 shows the need):** a body-version change that makes loops first class,
in Python, Go and Rust with vectors (WRT-017's lesson). That decision belongs to the owner after
the dogfood in §10.

**Open encoding questions.**

1. SPEC §7 makes an `accept` of a question blob a settlement. A loop blob as subject would be
   "settled" by a DISCHARGED accept. That is intended, but the interaction with re-litigation
   novelty has to be checked: should a later FAILED be re-litigation, or a CONTESTED state?
2. `serves` in `prior` mixes "responds to" with "is meant to advance". It may need its own field
   in stage 2.

## 9. Owner decisions needed

| # | Question | Options | This draft recommends |
|---|---|---|---|
| D1 | Profile or core | profile over the existing body / new body version now | profile first (§8) |
| D2 | Kinds | the four of §4.2 / fewer (goal + obligation) / more (desire, value) | the four; desire and value deliberately left out |
| D3 | Does a predicate replay alone discharge an obligation owed to someone? | always / never / per loop (`requires_beneficiary`) | per loop, with `true` as the default for obligations |
| D4 | Where the store lives | `.warrants/` in the repository tree / `refs/warrants/*` | in the tree: it travels with the code and shows in diffs; the subject is always the reviewed SHA, so the record's own commit is not a problem |
| D5 | First consumer | the Codex–Claude review loop / sokol / clients | the review loop: it is real, it happens weekly, and both agents run `warrant-mcp-server` |

## 10. Plan, and how each stage is falsified

| Stage | Content | It fails if |
|---|---|---|
| P0 | this draft; adversarial review by Codex | the kinds or the typed-closure rule cannot express a real case Codex brings |
| P1 | `impl/loops.py` + `tests/loops_test.py`: vectors per row of §5 and §6.2; one mutant per rule in §6, each on target (it removes exactly the guard it names) | a mutant survives, or a vector needs a field §4.1 does not have |
| P2 | dogfood: transcribe the warrant #131 round (review of `cda525e`, P1 snapshot, its fix and re-review) into `.warrants/` as loops and closures, with `repro.py` as evidence | the round cannot be expressed without prose doing the work, or the frontier after transcription disagrees with what the owner knows is open |
| P3 | `warrant-mcp-server` tools: `open_loop`, `close_loop`, `frontier`, `dependents` | an agent can close a loop through MCP that the checker reports OVERCLAIMED, and the tool did not refuse it |
| P4 | D1 revisited with P2's evidence | |

**Known gap.** The predicate of a review finding is "the regression fails on the old SHA for the
stated reason and passes on the new SHA, and a mutant that restores the defect fails it". That
predicate runs tests. ski@v1 cannot express it. `cmd@v1` with a transcript can record it, but a
recipient re-running it is a different trust level from replaying a term. Until that is
addressed, such findings close as ATTESTED with a transcript, not DISCHARGED. §6.2 says so
instead of hiding it.

## 11. Not in scope

Planning and scheduling. Priorities between loops. Incentives, reputation and blame (0040
§7–8, `0065_Monday.md`). Any automatic decision from a frontier. Desire, value and meaning as records.
Changing what `warrant verify` decides.
