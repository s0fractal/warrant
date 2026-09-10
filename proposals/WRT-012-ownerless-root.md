# WRT-012 — External witnessing and separation of control over history (rev 2)

**Status: DRAFT rev 2 (2026-09-10), after gate round 1 (Codex, AMEND, §10).
A plan and an experiment protocol, not a decision, not an adoption.**
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
verification:  FINITE_SCOPE_VERIFIED | SELF_REFERENTIAL_CONSISTENT | FAILED | NOT_RUN
time:          FILE_BOUND_PENDING | BLOCK_ATTESTATION_PRESENT_UNVERIFIED | BITCOIN_VERIFIED(<height>, source=<name>) | NONE
holding:       EXTERNALLY_OBSERVED(<holder>, custody=<name>) ... | NONE
freshness:     UNKNOWN | LATER_STATE_WITNESSED(<holder>) | MATCHES_AVAILABLE_WITNESS
adoption:      NOT_EVALUATED | <roster warrant id>
```

Axes are independent. A correct local computation is `FINITE_SCOPE_VERIFIED`
with `time: NONE`; a wrong one stamped in Bitcoin is `FAILED` with
`time: BITCOIN_VERIFIED`. The time axis attests existence, not correctness,
and the report is built so that it cannot say otherwise. `verification` for
black-heart's embedded runners is `SELF_REFERENTIAL_CONSISTENT` by
construction (study §4), not `FINITE_SCOPE_VERIFIED`; that is the one place
where rev 1's instinct to demote the label was right, and it is done on the
verification axis, not by overwriting it with a holding word.

`freshness` reuses `.triad/continuity/bootstrap.py` semantics: it is `UNKNOWN`
unless a holder's later receipt for the same `stream` is presented and
verified; `MATCHES_AVAILABLE_WITNESS` explicitly does not exclude a joint
rollback of committer and witness (the `.triad` case, and black-heart
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
| `report C [--receipt path...] [--witness path]` | builds §2.3; each receipt is fetched from the holder's store by the *verifier*, re-hashed, signature checked against the holder's published key | a receipt supplied by the committer alone (it is counted as `holding: NONE` with a note) |

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
committer-authored receipt → `holding: NONE`; present a holder receipt for an
older `C` in the same stream → `freshness: LATER_STATE_WITNESSED` on the
older one, and the newer one stays `UNKNOWN` (that is the torn-end limit,
stated, not hidden).

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
3. Holder receipt from a store the committer does not write to. Two
   candidates, both to be tried: (a) Zenodo, by depositing `C1` as a new
   version with Zenodo's own checksum as `holder_head`; (b) a **second GitHub
   account or organisation** the owner does not push from, or Codex's
   environment if it has one. If neither exists, the endpoint records
   `holding: NONE` and the experiment still runs. A holding from
   `s0fractal/sigma-glyph` is recorded with custody `github:s0fractal` and
   counted as **not independent**.
4. `report C1`. Endpoint: axes read exactly `FINITE_SCOPE_VERIFIED /
   FILE_BOUND_PENDING / <as obtained> / UNKNOWN / NOT_EVALUATED`.
5. **Rollback attack.** Produce `C2` (sequence 18, prev `C1`), stamp it, obtain
   a holder receipt for `C2`. Then present the verifier with the stream
   truncated at `C1` plus `C1.ots` plus `C1`'s receipt. Endpoint: with only
   the committer's material, `freshness: UNKNOWN` (the attack is *not*
   detected, and the report says so); with the holder's store fetched,
   `freshness: LATER_STATE_WITNESSED(holder)`. Both outcomes are the
   predeclared result; the experiment fails only if the first case prints
   anything stronger than `UNKNOWN`.
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
lines become `verification: SELF_REFERENTIAL_CONSISTENT` because that is the
predicate they compute. `--witness <report>` is optional and adds the other
axes; absence is `NONE`, not failure.

### 5.5 CI grep, revised
Fail a job when an output line contains a guarantee word from one axis while
the same report's other axis is weaker and the line does not name it. A
`WARNING` is acceptable output; a `VERIFIED` that hides `freshness: UNKNOWN`
in the same tool run is not.

## 6. Custody accounting (unchanged in substance, corrected in method)

Custody is a named assumption per holder, printed in the report; it is not a
count of strings. Bitcoin: header source is the assumption. Zenodo: its
operators and policies. GitHub `s0fractal/*` including all CI keys: one
custody. Model sessions: hold nothing between sessions.

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
4. Whether `SELF_REFERENTIAL_CONSISTENT` should be the verification value for
   any runner that imports its engine from `sys.path` rather than embedding it.

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
