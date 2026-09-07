# Review corpus retirement 2026-09 — three lineages, one transition

Status: **APPLIED controlled-forgetting act.** Tombstone and index for what
left the default tree on 2026-09-07; the machine-readable records are
`history/retirement-records/*.json`, checked by `tools/retirement_check.py`
inside `tools/check.py`.

This changes **admission**, not truth. Nothing below was refuted and nothing
was erased: every subject blob is in git history at the before revision, and
76 of the 78 are byte-identical in release tag `v0.9.0` (GitHub release of
2026-08-01, source archives attached by GitHub); the two `wrt-002-model`
files changed after that tag and exist only in git history.

Exact before revision: `97f024fe253122b67e90cf426d767cc73baf1d8d` (master
after PR #58, the WRT-001/WRT-002 closures). Apply commit and tree are in
*Applied transition* at the end.

## Protocol, and its limit here

Manifesto's `CONTROLLED-FORGETTING-0.1` §§1–10, the `APPLIED + in-repo`
slice, applied **locally**: local records under profile
`warrant.retirement-record@v0.1`, a local consumer ported from sigma-glyph's
checker at its post-review state (subject inventories pinned inside the
checker, relative citations scanned), local authority. Manifesto's checker is
not the consumer and no authority is borrowed from it. The two earlier
retirements in this directory (autonomy envelope, `ski@v2` candidate) stay as
they are: prose records without machine form, not re-cast by this act.

Mode used: `ARCHIVED` for every subject — excluded from default reasoning,
not refuted. No subject is `SUPERSEDED`: reviews are evidence, and nothing
replaces evidence.

## Why these, and why now

`reviews/` held 93 review files plus five settle ledgers and nine manifests,
~18 600 lines. Seventy-one of the review files were July 2026 gates and audits
of things that are either adopted (GOV-001 → SPEC v0.3), merged (seven Codex
merge-gate series whose tools live in `tools/` and CI), or closed as deferred
on 2026-09-07 (WRT-001, WRT-002). Until that closure the WRT-001/002 gates
were the evidence of pending designs and had to stay; the closure is what made
this act possible, and it was done first on purpose.

The three lineages:

- **`review-corpus-2026-07`** — 71 files: the GOV-001 gate (7, one `.pass1`),
  the July external audits with their adjudications (20), the Codex merge-gate
  series (23), the WRT-001 gates (11) and the WRT-002 gates (10).
- **`work-orders-2026-07`** — `HANDOFF.md` (2026-07-29, which flags its own
  counts as stale), `briefs/BRIEF-v03-implementation.md`,
  `briefs/WRT-002-rev7-adversarial-gate.md`.
- **`wrt-002-model`** — the four files of `proposals/wrt-002-model/`, which
  WRT-002's closure does not retain as current evidence and nothing in
  `tools/check.py` runs.

**Kept, deliberately:** the five settle gates and `reviews/ledgers/`
(`tools/settle.py` is live and the brief is the remaining target of
`tools/adversarial_gate.py`; undecided, not retired); the WRT-002 rev-7
multifamily adjudication (`reviews/2026-07-wrt-002-rev7-multifamily-gate-response.md`,
the 17-row table ARCHITECT W5 rests on); every August 2026 review and
manifest (WRT-003/005 gates, paper PR #30 reviews, the two surveys);
`.warrants/`; `CHANGELOG.md`.

## Retrieval, with status

```sh
git show 97f024fe253122b67e90cf426d767cc73baf1d8d:<historical-path>
```

Every retrieved subject carries this envelope, and a citation must carry it:

```text
HISTORICAL WARRANT ARTIFACT — retired 2026-09-07, history/RETIREMENT-2026-09-REVIEW-CORPUS.md
retired from the default surface after 97f024f
current admission: EXCLUDED; historical review allowed with this status
do not treat as current precedent without an explicit re-adoption act
```

Git availability is best-effort; the release tag is the preservation path
that does not depend on this repository's remote for 76 of 78 subjects.

## Index of the retired reviews

Files are named by stem (`reviews/2026-07-<stem>.md`); `+r` = a paired
`-response.md`.

| Round | Files (stems) | What it produced |
| --- | --- | --- |
| GOV-001 gate, rev 1–3 (07-07) | `codex-gov001-gate` +r, `gemini-gov001-gate` +r, `deepseek-gov001-gate` +r +`.pass1` | each revision forced a rewrite; rev 4 integrated every amendment and became SPEC v0.3 (settlement, multi-root stores, key-state); keyring interchange format dropped |
| July audits of v0.2–v0.3 (07-07 … 07-18) | `opus48-v0.2-review` +r, `codex-v0.3-pedantic-audit` +r, `codex-v0.3-runtime-hardening-audit` +r, `qwen-web-holistic` +r, `kimi-k3-spec-review` +r, `gemini31pro-agy-audit` +r, `gemini31pro-ed25519-audit` +r, `gptoss120b-agy-audit` +r, `antigravity-deep-review` +r, `kimi-full-audit` +r | Ed25519 small-order and torsion rules (SPEC §5, ARCHITECT W1), verifier totality, `cryptography` bounds and `tests/hostile.py` as a gate, action SHA pins, refuted P0s recorded with the commands that refuted them |
| Codex merge gates (07-26 … 07-28) | `codex-release-surface-gate` + 6 regates → `tools/check_release_surface.py`; `codex-structured-verification-report-gate` + 3 regates → `warrant.verify-report@v0`, SPEC §11; `codex-verify-report-contract-gate` + regate; `codex-sibling-pin-gate` + 3 regates → one pinned sibling in `ci.yml`; `codex-x1-cross-repo-gate` + 2 regates → `tools/x1_*.sh`; `codex-surrogate-premerge-gate`, `kimi-k3-surrogate-regate` → lone-surrogate hardening | every branch merged; the tool or contract each gated is in the tree and in CI |
| WRT-001 gates (07-26 … 07-27) | `codex-wrt001-gate`, `-rev2-gate`, `-refactor-gate`, `-refactor-recheck`, `-item0-recheck-2`, `-item0-done-candidate-gate`, `-item0-final-gate`, `-budget-spec-gate` +r, `kimi-k3-item0-adversarial-gate`, `kimi-k3-item0-regate` | item 0 (generic verifier refactor) on `master`, hardened by Kimi's 11 findings; §8 budget gated once (AMEND), never re-gated; WRT-001 CLOSED DEFERRED 2026-09-07 |
| WRT-002 gates (07-27 … 07-28) | `codex-wrt-002-design-gate`, `-rev2` … `-rev6-design-regate`, `kimi-k3-wrt-002-rev7-adversarial-gate`, `gemini31pro-wrt-002-rev7-adversarial-gate`, `deepseek-v4-wrt-002-rev7-adversarial-gate`, `qwen-web-wrt-002-rev7-gate` | nine reproduced defects after six single-family rounds; six closed in rev 8b, F3 (P0) / F4 / F5 / F7 open; the adjudication stays live; WRT-002 CLOSED DEFERRED 2026-09-07 |

## Carried forward — findings not closed in the tree

Each names where it lives now. "Not tracked elsewhere" means exactly that.

- **F3/F4/F5/F7, authorized effective lifecycle** — `ARCHITECT.md` W5 and its
  "Open problem" section; reproductions were Appendix A of
  `kimi-k3-wrt-002-rev7-adversarial-gate` (retired; retrieve with status).
- **WRT-001 §8 budget** — gated once with AMEND, amendments never re-gated;
  recorded in WRT-001's closure. Dormant with the proposal.
- **`.pth` residual under `-I`** (`codex-release-surface-regate-5`) — site
  initialization still runs `.pth` code before the snippet; explicit, not
  blocking under the clean-build threat model. Not tracked elsewhere.
- **X1 physical-line contract, one part open** (`codex-x1-cross-repo-regate`
  "Remaining finding"). Not tracked elsewhere; verify against the current
  `tools/x1_cross_repo.sh` before acting.
- **Plain `json.loads` blob paths vs `loads_ijson`** — consistency hardening,
  not a live bug (`kimi-k3-surrogate-regate`). Not tracked elsewhere.
- **Kimi item-0 residual probes and message-string P2s**
  (`kimi-k3-item0-regate`) — "for a future pass when quota refreshes". Not
  tracked elsewhere.
- **Warrant-side `ski@v1` boundary vectors** (ATP-limit behaviour;
  `antigravity-deep-review-response` "Roadmap") — noted, not actioned.
- **TLA+ of SPEC §5.1 and `why` DOT export** — standing P3 roadmap
  (`codex-v0.3-pedantic-audit-response`); first-error-message parity across
  validators declined.
- **Python `verify` store-only vs Go's loose `examples/` layout**
  (`opus48-v0.2-response`) — a CLI-surface asymmetry, not an outcome
  divergence; status unverified here.
- Closed since, for the record: Ed25519 small-order/cofactor follow-up (W1),
  action SHA pins (`ci.yml`), keyring format (dropped in GOV-001 rev 4),
  negative-path suite (`tests/negative.py`).

## Known loss

- the full text of every finding, refutation and reproduction; the index keeps
  outcomes, not arguments;
- the executable countervectors for F3/F4/F5/F7 at HEAD, and a runnable
  WRT-002 rev 8b model (55 passing vectors against a definition F3 defeats);
  a rev 9 retrieves both from the before revision or rebuilds them;
- the revision-by-revision design conversation of WRT-001 and WRT-002;
- the blind-pass provenance of the DeepSeek GOV-001 gate;
- the exact task framing given to the v0.3 implementer and to the rev-7
  reviewers, including what each was allowed to read;
- `tools/adversarial_gate.py` keeps only its `settle` target; the multi-target
  shape stays, the second target's brief and model are gone;
- `llms.txt` no longer counts prior reviews; it points here instead.

## Reference transitions

Active files that cited a retired subject as current were rewritten in the
apply commit, citing by stem with this ledger as the locator: `ARCHITECT.md`
(three audit pairs, W5's reproduction pointer), `proposals/GOV-001-…`,
`proposals/WRT-001-…`, `proposals/WRT-002-…`, the kept multifamily
adjudication's closing list, `tools/or_review.py` (hard-coded GOV-001 list →
glob over the live inbox), `tools/adversarial_gate.py` (`wrt-002` target
removed, usage example made generic), `llms.txt`, `reviews/README.md`.
`MAP.md` was regenerated: its `WRT-002` row resolved to `model.py` and three
rows named the rev-7 brief as first citer.

Excluded from the zombie-reference scan as tombstone or immutable-history
class: `history/`, `.warrants/`, `CHANGELOG.md`. Nothing else is excluded.

## Executable postconditions

`tools/retirement_check.py` (two entries in `tools/check.py`) reads the three
records as data and refuses, per record, when: a subject's digest at the before
revision differs from the record, or the subject is present in the apply tree
or the working tree; the apply commit is not the direct child of the before
revision or its tree differs; the record's `(path, digest, mode)` inventory
differs from the one pinned inside the checker (so a row cannot be dropped to
hide a resurrection); `loss` is empty; a pinned replacement operand drifted;
any tracked file outside the excluded classes cites a retired path, absolutely
or relative to its own directory; a record is missing from or absent in the
closed manifest. `--selftest` burns each refusal with a mutation. `VALID`
means the operands bound and the postconditions replayed; it says nothing
about whether retiring was wise.

## Re-adoption

Restoring bytes from git or from the release tag is not re-adoption. Returning
any subject to the default surface needs a new record naming the evidence for
doing so; it does not rewrite this one.

## Applied transition

- before revision: `97f024fe253122b67e90cf426d767cc73baf1d8d`
- apply commit: recorded in `history/retirement-records/*.json` (`applied`)
- authority: repository owner instruction in the working session of
  2026-09-07, after the closures in PR #58; Codex reviews the act as it did the
  sigma-glyph one; the record addresses the act, it does not prove it was
  within anyone's power
- changed scope: the 78 subjects, this ledger, the reference transitions
  above; the receipt commit adds the records, the checker and its
  `tools/check.py` entries
