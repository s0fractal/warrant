# WRT-012 — External witnessing and separation of control over history (rev 3)

**Status: DRAFT rev 3 (2026-09-10), after gate rounds 1 and 2 (Codex, AMEND,
§10–§11). A plan and an experiment protocol, not a decision, not an
adoption.** Rev 3 is a narrow amendment of the protocol: success controls,
direction of the freshness check, verification axis split into method and
result, no report as input, holder independence stated per holder.
Written by the maintainer actor `claude-fable-5-1`. The owner's "повністю
зрозумів" (2026-09-10) authorized writing the plan and preparing branches; it
is not a threshold warrant (warrant `AGENTS.md` rule 2). Rev 1 was titled
"ROOT-0.1: an ownerless trust root"; the title was too large a word and the
record conflated several guarantees. Rev 2 keeps the direction and separates
them. Filed as `~/Projects/ROOT-0.1-PLAN-2026-09-10.md` (durable copy) and
`proposals/WRT-012-ownerless-root.md` on warrant branch
`wrt-012-ownerless-root` (path kept for continuity of the branch; the word
"ownerless" is retired in the text).

Companions: `~/Projects/TRUST-ROOT-WITHOUT-OWNER-2026-09-10.md` (why),
`~/Projects/BLACK-HEART-STUDY-2026-09-10.md` (black-heart today).

---

## 0. Provenance — what exists, and what rev 1 missed

| Where | Existing thing | Establishes | Does not establish |
|---|---|---|---|
| `.triad/experiments/external-timestamp-001` | a real OTS submission of a commitment (`commitment.json`, `initial.ots`), two calendar paths, and in `followup-003` a **BitcoinBlockHeaderAttestation at height 966087** | a commitment digest was submitted; a block attestation was later supplied by calendar Alice | chain verification (`ots verify` exited 1: no node); latest head; custody |
| `.triad/continuity/ots_receipt_status.py` | offline receipt classifier | `file_binding_verified`, `FILE_BOUND_PENDING` vs `BLOCK_ATTESTATION_PRESENT_UNVERIFIED`; `time_verified:false` on both; `calendar_authenticity_verified:false`; `latest_head_discovery:false` | time; authenticity; freshness — and it says so in every output |
| `.triad/continuity/bootstrap.py` | history observation against a caller-pinned witness snapshot | `LATER_HISTORY_WITNESSED`, `MATCHES_AVAILABLE_WITNESS`, `WITNESS_UNAVAILABLE`, fork refusal; 14 CLI controls incl. **the undetectable joint rollback** | complete history; recoverable bytes; freshness beyond the supplied witness |
| `.triad/continuity/history_receipt.py` | links a commitment head into observed history | `LOCAL/WITNESSED_TIP` vs `_ANCESTOR` vs `UNLINKED`, `admission: NOT_EVALUATED` | time credit; completeness |
| black-heart `continuation/x1002_task_journal.py` + `continuation-task-002` | checkpoint pinning implementation digests; restore refuses 10 named divergences | detection of edits to journal/task/implementation | **old journal + old checkpoint is accepted by design** (joint rollback, again) |
| warrant `trust-config.json`, `trust/*.json`, WRT-010, WRT-011 | roster trust; fact provenance; bounded aggregation | provenance inside a pack | any witness outside the roster's custody |
| sigma-glyph SA-5 / SA-5b | honest custody count | 2-of-3 satisfied by one custody | a remedy |
| manifesto embedded-claims | `verifier` closure digest, `dep.sha256` | external verifier identity, operand pin | time; holding |
| Zenodo deposits `10.5281/zenodo.22172098`, `…22646920` | institutional custody of *those* bytes | those bytes exist under Zenodo's policies | custody of any later commitment or verifier closure |

Rev 1's §0 claimed the stack had no OTS prior art. Wrong: `.triad` had
submitted, classified and linked a real receipt two days earlier. The rev 2
design reuses its axis vocabulary rather than inventing a parallel one.

## 1. The direction, restated without the big word

The verifier of an artifact should be able to obtain evidence about that
artifact's past from a party other than whoever hands the verifier its current
environment. Today, in all four repos, the environment and the evidence come
from the same hand. This WRT separates:

1. the **commitment** (what is claimed to have existed),
2. **proofs** about the commitment, each from a different party with a named
   trust assumption,
3. a **report** that states each proof's outcome on its own axis and never
   folds them.

"Ownerless" is retired. Bitcoin time has no key to revoke, but header trust is a
choice; Zenodo has operators and policies; a verifier digest is chosen by
someone. The honest claim is *external* and *separated*, not *ownerless*.

## 2. Three objects, not one

### 2.1 Commitment (immutable, content-addressed, what gets stamped)

```json
{"type": "warrant.commitment@wrt012-dev",
 "subject": {"kind": "git-commit|file|bundle|warrant-record", "sha256": "<64hex>"},
 "verifier": {"closure_sha256": "<64hex>"},
 "stream": "<64hex stream id>", "sequence": 17, "prev": "<64hex|null>"}
```

Canonical JSON (sorted keys, compact, UTF-8, no floats). Its SHA-256 is the
commitment digest `C`. **Nothing about proofs is inside it.** That removes rev
1's cycle (a record containing the hash of the `.ots` that stamps the record).

### 2.2 Proofs (separate files, each about `C`)

| Proof | File | Produced by | Trust assumption named in the report |
|---|---|---|---|
| time | `C.ots` | `ots stamp` on the commitment bytes | calendars; then a chosen chain-header source |
| holder receipt | `<holder>/receipts/<C>.json` | **the holder**, in the holder's own store | that store is not under the committer's control |
| verifier recomputation | none (recomputed) | anyone with the pinned closure | the closure choice |

### 2.3 Report (derived, never authoritative)

```
verification:  method=EXTERNAL_CLOSURE|SELF_REFERENTIAL  result=PASS|FAIL|NOT_RUN  scope=<what was checked>
time:          FILE_BOUND_PENDING | BLOCK_ATTESTATION_PRESENT_UNVERIFIED | BITCOIN_VERIFIED(<height>, source=<name>) | NONE
holding:       EXTERNALLY_OBSERVED(<holder>, custody=<name>) | DEPOSITED(<institution>, record=<id>) | NONE
freshness:     UNKNOWN | LATER_STATE_WITNESSED(<holder>, path=C_i→C_j) | MATCHES_AVAILABLE_WITNESS
adoption:      NOT_EVALUATED | <roster warrant id>
```

`verification` is three fields, never one word: `method` says how the check
was performed (a pinned external closure, or code carried by the artifact
itself), `result` says what that check returned, `scope` says what it
covered. `result` is `NOT_RUN` until the substantive check has actually
executed; a pinned verifier closure names the code, not its outcome.

Axes are independent. A correct local computation is `result=PASS` with
`time: NONE`; a wrong one stamped in Bitcoin is `result=FAIL` with
`time: BITCOIN_VERIFIED`. The time axis attests existence, not correctness,
and the report is built so that it cannot say otherwise. For
black-heart's embedded runners `method` is `SELF_REFERENTIAL` by construction
(study §4); `result` and `scope` are whatever that runner actually computed,
established per runner from the study's list, never assigned by default. That
is where rev 1's instinct to demote the label was right, and it is now done on
the right axis and without asserting a result the runner did not produce.

`freshness` reuses `.triad/continuity/bootstrap.py` semantics and runs in one
direction only: the verifier holds a local `C_i`, obtains from a holder named
in its **own trusted configuration** a receipt for some `C_j`, and verifies the
`prev` path `C_i → C_j` link by link. Only then is `C_i` reported
`LATER_STATE_WITNESSED(holder, path=C_i→C_j)`. A receipt about `C_i` itself
says nothing about later state. A `C_j` with a larger `sequence` but no
verifiable path is another branch and yields `UNKNOWN` with note
`DISCONNECTED`. `MATCHES_AVAILABLE_WITNESS` explicitly does not exclude a
joint rollback of committer and witness (the `.triad` case, and black-heart
task-002's accepted rollback). Latest-head discovery is a separate protocol
(§8.1) and this WRT does not claim it.

Composition policy (which combinations a consumer accepts) is the consumer's,
stated per repo in §4. Warnings are allowed; what is refused is a downstream
line that upgrades a warned axis into a guarantee.

## 3. The tool — `tools/witness.py` (rename from `root.py`)

Stdlib + `opentimestamps` library where the OTS-enabled interpreter is
available (`.triad` uses `/opt/homebrew/opt/python@3.14/bin/python3.14`); the
`ots` CLI for submission only. Verbs:

| Verb | Does | Refuses |
|---|---|---|
| `commit` | writes a commitment (§2.1) for a subject, `prev` = last commitment in that stream | a `prev` that is not the current tip of the local stream |
| `stamp C` | `ots stamp` the commitment bytes; stores `C.ots` beside it | re-stamping an existing `C.ots` (never overwrite the initial receipt; `.triad` rule) |
| `classify C` | `.triad` classifier verbatim on `C` + `C.ots` → time axis | any mismatch of pinned digests |
| `upgrade C` | `ots upgrade` on a **copy**; if a block attestation appears, `BLOCK_ATTESTATION_PRESENT_UNVERIFIED`; `BITCOIN_VERIFIED` only after header check against a named source | `--no-bitcoin` as a way to print VERIFIED |
| `receipt C --as <holder>` | **run by the holder**: writes `{holder, C, holder_head, observed}` signed by the holder's key into the holder's store, and returns the receipt digest | a receipt for a `C` the holder cannot fetch and re-hash |
| `report C --holders <trusted-config>` | builds §2.3 from commitment + proofs only; for each holder in the verifier's trusted configuration (holder id → key → store locator, caller-pinned exactly as `.triad/bootstrap.py` pins its witness) it fetches receipts from that store, re-hashes, checks the signature against the configured key, and walks `prev` paths | a report as input (reports are recomputed, never accepted); a receipt, key or store locator that arrived together with the committer's material (counted as `holding: NONE` with note `UNCONFIGURED_HOLDER`) |

The holder's key is trusted only through the verifier's configuration. A
"published key" fetched from a site named by the receipt is not a binding:
receipt, site and key can be substituted together.

`hold --holder --head --custody` from rev 1 is removed: it recorded the
committer's claim about a holder, which is worth nothing. Observing a
sibling's HEAD by `git ls-remote` is *our* observation of *them*; it is not
their holding of *us*. A holding exists only as a receipt in the holder's
store. Custody independence is not the count of distinct strings; it is a
named assumption per holder in the report, and the honest number for the four
GitHub repos under one account is one.

Mutation tests: flip one byte of the commitment → `COMMITMENT_PIN` refusal;
edit `prev` → refusal; relabel `PENDING` as `BITCOIN_VERIFIED` in a stored
report → `report` recomputes from bytes and disagrees; present a
committer-authored receipt → `holding: NONE`; hold local `C1`, present a configured
holder's receipt for `C2` with a verified `prev` path `C1→C2` → `C1` reports
`LATER_STATE_WITNESSED(holder, path=C1→C2)`; present a receipt for `C3` with
`sequence` > `C1` but no verifiable path → `UNKNOWN`, note `DISCONNECTED`;
the newest local commitment always stays `UNKNOWN` unless a configured holder
has something later (that is the torn-end limit, stated, not hidden). A
`report` implementation that returns `UNKNOWN` unconditionally fails the
second control; both controls are mandatory (§4).

## 4. One end-to-end experiment before any policy spreads

Per gate round 1: prove the objects on one stream before touching four CIs.
Predeclared in `protocol.json` before running, `.triad` style.

**Stream:** warrant flagship release bytes at `d83984f` (subject) with the
current settle verifier closure (verifier).

**Steps and predeclared endpoints:**

1. `commit` → `C1`. Endpoint: canonical bytes reproduce `C1` on a second
   interpreter.
2. `stamp C1` → `C1.ots`. Endpoint: `classify` = `FILE_BOUND_PENDING`, altered
   commitment refused. (Submits one digest to two calendars; nothing else
   leaves the host. Same footprint as `.triad` external-timestamp-001.)
3. Holder receipt from a store the committer does not write to. What does
   **not** count, stated before running: a second GitHub account or
   organisation under the owner's control (no independence added); Codex's
   or any model's environment whose files live on the owner's host (same
   custody). What may count: Zenodo, through a **separate adapter** that
   deposits `C1` as a new version and later lets the verifier fetch Zenodo's
   own record id and checksum; this yields `holding: DEPOSITED(zenodo,
   record=<id>)`, which is institutional custody of bytes and *not* a signed
   receipt of §3 format. If no holder outside our custody is available, the
   external half of the experiment is recorded as **`NOT_DEMONSTRATED`**; the
   local half may still complete; `NOT_DEMONSTRATED` does not open §5.
4. `report C1 --holders <config>`. Endpoint: axes read exactly
   `verification: method=EXTERNAL_CLOSURE result=NOT_RUN` (steps 1–3 create a
   commitment, a timestamp and a holding; they do not run the flagship
   check) `/ FILE_BOUND_PENDING / <as obtained> / UNKNOWN / NOT_EVALUATED`.
   4b. Run the flagship check itself under the pinned closure and re-report:
   `result` becomes `PASS` or `FAIL` with `scope` named; every other axis is
   unchanged by this step (that invariance is an endpoint).
5. **Freshness controls, both mandatory.** Produce `C2` (sequence 18, prev
   `C1`), stamp it, obtain a holder receipt for `C2` from a configured
   holder.
   - Control A (no later witness available): present the verifier with the
     stream truncated at `C1`, `C1.ots`, and a holder configuration whose
     store contains no receipt for anything after `C1`. Endpoint: `C1` reports
     `freshness: UNKNOWN`, and nothing stronger.
   - Control B (verified continuation): same truncated local stream, holder
     configuration pointing at the store that holds the `C2` receipt.
     Endpoint: `C1` reports `LATER_STATE_WITNESSED(holder, path=C1→C2)`
     after walking the `prev` link; the run records the fetched receipt
     digest and the path.
   - Control C (disconnected branch): store holds a receipt for a `C2'` with
     `sequence` 18 and `prev` ≠ `C1`. Endpoint: `UNKNOWN`, note
     `DISCONNECTED`.
   The experiment passes only if A, B and C all hit their endpoints. An
   implementation that returns `UNKNOWN` unconditionally fails B; one that
   trusts `sequence` fails C. If the only available holder is under our
   custody, B and C run against it and the run is labelled
   `NOT_DEMONSTRATED (holder not independent)`.
6. Later, on a copy: `upgrade C1`; if a block attestation appears, classify
   it `…_UNVERIFIED`; choose and name a header source (§8.2) before any
   `BITCOIN_VERIFIED` line exists.

Recorded under `warrant/experiments/wrt-012-e2e-001/` with `SHA256SUMS`,
exact commands, zero model calls.

## 5. Per-repo plan — gated on §4

Nothing below starts until §4 has run and its report is in the branch.

### 5.1 warrant
WRT-012 rev 2 (this) + `tools/witness.py` + tests + the §4 experiment.
`SPEC.md` unchanged. Consumers' composition policy lives in each consumer.

### 5.2 sigma-glyph
SA-5 gains a per-adoption line with the five axes; every row today reads
`holding: NONE, freshness: UNKNOWN`. Adoption records get `commit`+`stamp` at
adoption time (SA-5b's one non-delegable command gains one line). No arbiter
change.

### 5.3 manifesto
`claims.py run` gains `--commit`: the compiled-bundle digest becomes a
commitment, stamped, classified; the report's document-level line carries the
five axes. Per-record `REPLAYED/MISMATCH/STALE` unchanged. Retirement norm:
keep commitment + `.ots` + receipts; the report is derivable and removable.
(Rev 1 §9 said the `.ots` could restore a lost JSON. It cannot; a hash is not
a backup.)

### 5.4 black-heart
Now, independent of this WRT: fix the `cli.py verify` crashes (study §3) with
one test per branch, and the `cegis_kernel.parse_term` `eval`. After §4:
`cli.py verify` prints the five-axis report; its embedded runners' `VERIFIED`
lines become `verification: method=SELF_REFERENTIAL result=<what the runner
returned> scope=<what it checked>`, with `scope` established per runner from
the study (e.g. colony `--audit`: `prev_epoch_hash` links only). Inputs are
`--commitment`, the proofs, and `--holders <trusted-config>`; the report is
recomputed, never accepted as input. Absence of proofs is `NONE`, not
failure.

### 5.5 CI check, revised
Not a grep over prose. Each consumer parses the structured report and applies
its own stated policy over the five fields; the job fails when the policy's
required combination is not met, and the failure names the axis. A weak
`freshness` never refutes a `verification.result=PASS`; it refuses only the
combinations the consumer's policy says need freshness (e.g. adoption). A
`WARNING` is acceptable output; a downstream line that upgrades a warned axis
into a guarantee is not.

## 6. Custody accounting (unchanged in substance, corrected in method)

Custody is a named assumption per holder, printed in the report; it is not a
count of strings. Bitcoin: header source is the assumption. Zenodo: its
operators and policies, reachable only through the §4.3 adapter. GitHub
`s0fractal/*` including all CI keys, and any second account the owner
controls: one custody. Codex's environment for these experiments: files on the
owner's host, same custody. Model sessions: hold nothing between sessions. As
of rev 3 there is **no holder outside our custody with a §3-format receipt**;
the first experiment is expected to end `NOT_DEMONSTRATED` on the external
half unless the Zenodo adapter is built first.

## 7. What this does not claim

Not consensus, not a mesh. Not correctness from time. Not freshness from
`prev`: `prev` verifies a supplied chain and cannot reveal a hidden
continuation or equivocation between successors; only a holder's later receipt
can, and only for holders the verifier reaches independently. Not adoption.
Not a fix for black-heart's engines.

## 8. Open questions (for gate round 2)

1. **Latest-head discovery** as its own protocol: which holders to query, how
   a verifier learns of them without the committer's help. `.triad`'s
   `bootstrap.py` witness snapshot is the current answer and it is
   caller-pinned, i.e. still supplied by someone.
2. **Header source** for `BITCOIN_VERIFIED`: local node (none available), or
   a named public explorer pair with the trust assumption printed. The
   `.triad` followup-003 note applies: never label explorer comparison as
   full-node validation.
3. **Independent holder in practice**: does a second GitHub identity count
   for anything, and what does Codex's environment retain between runs?
4. Whether `method=SELF_REFERENTIAL` should also be assigned to any runner
   that imports its engine from `sys.path` rather than embedding it (the
   engine bytes are then chosen by whoever controls the directory, not by the
   artifact).

## 9. Relation to the stack

WRT-010 says where a fact came from; WRT-012 says where evidence about the
pack's past can be fetched from outside the pack's supplier. WRT-005 settlement
records are natural subjects. `.triad/continuity` is the reference
implementation of the time and freshness axes; this WRT should import, not
reimplement, its classifier.

## 10. Gate round 1 — disposition (Codex, 2026-09-10, AMEND)

Read against `4d4c6c5`. All six points accepted; two with a refinement.

| # | Finding | Disposition |
|---|---|---|
| 1 | External witness must not replace the verification result; keep independent axes; a warning is not by itself an overclaim | **Accepted.** §2.3 axes. Refinement: for black-heart's embedded runners the verification axis value is `SELF_REFERENTIAL_CONSISTENT` because that is the predicate they compute; the demotion is on the right axis now, not by overwriting with `UNROOTED`. |
| 2 | `prev` + Bitcoin do not solve the torn end; a stamped old checkpoint cannot reveal a newer one; need latest-state discovery | **Accepted.** `freshness` axis with `.triad` semantics; §4 step 5 makes the undetected case a predeclared endpoint; §8.1 keeps discovery as a separate protocol. |
| 3 | `hold` counted our claims; `ls-remote` observes the sibling, does not prove the sibling holds us; custody ≠ distinct strings; old Zenodo deposit ≠ custody of a new record | **Accepted.** `hold` removed; receipts are written by the holder in the holder's store and fetched by the verifier (§3); custody is a named assumption (§6); Zenodo counts only for bytes it holds (§0). |
| 4 | Circularity between record and `.ots`; split commitment / proofs / report; a hash is not a backup | **Accepted.** §2; rev 1 §9 corrected in §5.3. |
| 5 | "Ownerless" is too big a word; profile can live in warrant, mandating it elsewhere needs separate acceptance | **Accepted.** Title and §1 rewritten; §5 gated on §4 and on each repo's own adoption. |
| 6 | `.triad` already did the OTS submission, receipt classification, and head linkage; §0 must cite it | **Accepted, and it was my miss.** §0 rewritten; §3 imports the classifier; §4 reuses the experiment shape. |

Codex's recommended next step (fix spec → one e2e experiment with commitment,
real external receipt and rollback attack → only then spread) is adopted as
§4 and the gate on §5. The black-heart `cli.py verify` fixes proceed now,
independently.

## 11. Gate round 2 — disposition (Codex, 2026-09-10, narrow AMEND)

Read against `86de8e6`. All points accepted.

| # | Finding | Disposition |
|---|---|---|
| 0 | The §4.5 success condition let an implementation that always returns `UNKNOWN` pass; two mandatory controls needed; without an independent holder the external half is `NOT_DEMONSTRATED` and does not open the spread | **Accepted.** §4.5 rewritten as controls A/B/C, all mandatory; `NOT_DEMONSTRATED` defined in §4.3 and §6; §3 mutation test names the always-`UNKNOWN` failure. |
| 1 | §3 had the time direction backwards; verify local `C1`, obtain receipt for `C2`, verify path `C1→C2`; a larger `sequence` without a verified link may be another branch | **Accepted.** §2.3 freshness paragraph and §3 mutation tests rewritten; control C covers the disconnected branch. |
| 2 | `FINITE_SCOPE_VERIFIED` was pre-assigned in §4.4; the flagship check had not run; correct value `NOT_RUN`; a pinned closure names code, not outcome | **Accepted.** `verification` split into `method / result / scope`; §4.4 endpoint is `NOT_RUN`, §4.4b runs the check and requires the other axes to stay invariant. |
| 3 | `--witness <report>` contradicted "report is not authority"; accept commitment, proofs and separately trusted holder configuration, recompute; a "published key" needs a trusted binding | **Accepted.** `report --holders <trusted-config>` in §3, caller-pinned like `.triad/bootstrap.py`; §5.4 rewritten; substitution of receipt+site+key named as the refused case. |
| 4 | `SELF_REFERENTIAL_CONSISTENT` asserts a result; establish per runner what it checked; §5.5 should check structured fields under a consumer policy, and weak freshness must not refute correct local computation | **Accepted.** `method` is separated from `result`/`scope` (§2.3); §5.4 sets `scope` per runner from the study; §5.5 is a structured policy check, not a grep. |
| — | Holder independence: a second account under our control adds nothing; Codex's environment is on this host; Zenodo needs a separate adapter and is not a §3 receipt | **Accepted.** §4.3 lists what does not count before running; `DEPOSITED(...)` is a distinct holding value; §6 states that no independent §3-format holder exists as of rev 3. |

Codex's disposition — one more narrow AMEND, then implementation and the
experiment — is followed: rev 3 changes protocol text only. `cli.py verify`
and `cegis_kernel.parse_term` fixes in black-heart continue independently.

## 12. Implementation notes (prototype, 2026-09-10) — deviations from the text above

Prototype: `tools/witness.py`, harness `tests/witness.py` (49 checks, 5 mutants
killed), experiment `experiments/wrt-012-e2e-001/` (all 9 endpoints met,
external half `NOT_DEMONSTRATED`). Where the code differs from rev 3 text, the
code is the current reading:

- `freshness` values are `UNKNOWN | LATER_STATE_WITNESSED(holder, path, steps)`.
  `MATCHES_AVAILABLE_WITNESS` is not emitted: a holder's receipt for `C_i`
  itself appears on the holding axis (`EXTERNALLY_OBSERVED`) and grants no
  freshness. Typed notes under `UNKNOWN`: `PATH_INCOMPLETE` (a link's bytes
  are missing), `DISCONNECTED` (proven not the same chain: stream mismatch,
  sequence inconsistency, genesis reached, or sequence reached without meeting
  the local commitment), `LINK_TAMPERED` (bytes at an address do not hash to
  it), `PATH_BOUND_EXCEEDED` (default bound 10 000 links), `RECEIPT_REFUSED`,
  `STORE_UNAVAILABLE`. None grants later state.
- The path is checked link by link: address ↔ bytes, stream equality,
  `sequence == child − 1`, `prev` leads to a verified predecessor; the local
  commitment is met only with `sequence == local + 1`.
- `time` values the tool can emit: `NONE | FILE_BOUND_PENDING |
  BLOCK_ATTESTATION_PRESENT_UNVERIFIED | FILE_BOUND_UNSUPPORTED_ATTESTATION |
  UNCLASSIFIED`. `BITCOIN_VERIFIED` is never produced: no chain-header source.
- `verification.result` comes only from a run record written by
  `run-verifier`, which refuses a script whose bytes do not hash to the
  commitment's closure; `method=SELF_REFERENTIAL` requires an explicit
  `--scope`. A run record whose closure differs from the commitment's is
  refused by `report`.
- `report` takes commitment + proofs + `--holders <trusted-config>` (absolute
  store paths, holder public keys) and nothing else; it is offline and prints
  `authority: none`, `network_calls: 0`, and `inputs_sha256` for every byte it
  read, so two reports on frozen proofs can be compared input by input.
- Receipts are written only by `receive` on the holder side (domain-separated
  Ed25519 over the canonical body), never overwrite, and chain through
  `holder_head`. Initial `.ots` receipts and run records are create-only.

## 13. Review repair after 8bb3fdf (Codex)

Implementation amended on `fix/wrt-012-verification-bindings`. The independent
review found unsigned run-claim laundering, absent subject binding, a script
mistaken for an execution closure, execution before retry refusal, holder-ID
misattribution and an omitted trust-configuration input hash.

The supported verification profile is now deliberately narrower:
`warrant.byte-equality@v1`, a built-in byte predicate with pinned subject and
policy. Report recomputes its result. Legacy run records confer NOT_RUN only;
arbitrary `--script` execution is refused before launch. This does not establish
that the original flagship PDF was substantively checked. A bound flagship
adapter remains deferred; the old experiment is preserved as historical output.

See `experiments/wrt-012-repair-001/REPORT.md` for F1–F6 dispositions, recovery
limits, commands and measured outcomes. There is still no independent holder,
no adoption and no opening of the per-repository rollout in §5.
