# Profile: EU AI Act Article 12 (record-keeping)

**Status:** DRAFT, non-normative, **not legal advice**. This maps Warrant record
fields onto the text of Article 12 so an engineer and a compliance reviewer can
argue about the same table instead of about vibes. It is a *mapping*, not a
compliance claim: no format makes a deployment compliant, and several Article 12
obligations are organisational, not representational.

**Applicability, as amended.** The AI Act's original dates for high-risk systems
were superseded by the *Digital Omnibus on AI* — provisional agreement 7 May
2026, Parliament's final approval 16 June 2026 — which defers them:

| High-risk category | Original | As amended |
|---|---|---|
| Annex III (stand-alone high-risk) | 2 August 2026 | **2 December 2027** |
| Annex I (AI embedded in regulated products) | 2 August 2027 | **2 August 2028** |

Article 12 requires automatic recording of events over the system's lifetime;
Article 19 + Article 26(6) set the retention floor (at least six months unless
other Union or national law says longer). We found no amendment to the
record-keeping or retention duties themselves — the Omnibus is a timeline and
simplification instrument — but it **renumbers and inserts articles**, so treat
every article number in this document as a pointer to the consolidated text
rather than as a citation, and check it against that text before relying on it.

*Dates verified 2026-07-27 against contemporaneous law-firm summaries of the
agreed Omnibus, not against the Official Journal. An earlier draft of this
profile stated the obligations apply from 2 August 2026, which the amendments had
already made wrong — a reminder that a compliance mapping decays without a date
on it.*

---

## 0. What Warrant does and does not claim here

Article 12 is about **logs**. Warrant is not a log — it is a **decision record**.
The distinction is the whole point of this profile:

| | A log line | A Warrant record |
|---|---|---|
| answers | *what happened* | *why it was permitted* |
| authority | the system asserts it | an actor signs it |
| the rule in force | named, if you're lucky | pinned **by hash** (`under`) |
| the reason | prose | may be an **executable check** anyone re-runs |
| after the fact | editable by the holder | editing changes the hash and breaks every citation |

So Warrant is a good fit for the *decision* events Article 12(2) cares about,
and a poor fit for high-volume telemetry. **Use both.** A sane deployment writes
ordinary logs for volume and files a Warrant at the points where a decision was
made, refused, or escalated. The Warrant chain is what survives into a dispute.

---

## 1. Field mapping

### Article 12(1) — automatic recording of events over the lifetime

| Requirement | Warrant mechanism | Notes |
|---|---|---|
| Events recorded automatically | `warrant-mcp` seals MCP tool-calls; framework adapters file on decision points | Sealing must be in the call path, not a post-hoc batch job |
| Recorded *over the lifetime* | append-only content-addressed store; `prior` chains records | The store is plain files; retention is a filesystem/DR question, see §3 |
| Tamper-evident | WarrantID **is** the SHA-256 of the canonical body; every citing record breaks on edit | This is the strongest claim in the profile and is machine-checkable: `warrant verify` |
| Attributable | Ed25519 signature over the canonical body; `actor.id` | Binding actor→key needs a trust configuration; without one the verifier says `binding unverified`, honestly |

### Article 12(2)(a) — situations that may present a risk, or a substantial modification

| Requirement | Warrant mechanism |
|---|---|
| Identify risk situations | a `reject` warrant is a **first-class record**, not an absence — refusals are the risk signal, and they are queryable |
| The rule that made it risky | `under` pins the **exact bytes** of the policy in force, by hash — not "policy v3" by name |
| Machine-decidable basis | a `because` entry of kind `check` with runtime `ski@v1`: a content-addressed, deterministic, budget-bounded predicate a reviewer re-executes offline |
| Substantial modification | a policy change is new bytes → a new hash → records before and after cite **different** `under` values; the change is visible without a changelog |

### Article 12(2)(b) — facilitating post-market monitoring (Article 72)

| Requirement | Warrant mechanism |
|---|---|
| Reconstructable decision history | `warrant why <id>` walks decision → reasons → checks → policy, verifying as it goes |
| Aggregation across deployments | the store is content-addressed, so packs from different sites merge without an ID authority; identical bytes deduplicate |
| No vendor lock for the reviewer | verification is offline and needs only an MIT tool; **trust the hash, not the host** |

### Article 12(2)(c) — monitoring of operation (Article 26(5) deployer duty)

| Requirement | Warrant mechanism |
|---|---|
| Deployer can monitor | `warrant verify --store-mode --json` emits one `warrant.verify-report@v0` object for CI/monitoring; `ok == (errors == 0)` |
| Detect the record set being altered | any edit changes a WarrantID; `verify` reports it as an error, not a warning |
| Human oversight point (Art. 14) | an oversight decision is itself a warrant: signed by the human actor, citing what they saw |

### Article 12(3) — logs for high-risk systems in Annex III(1)(a) (biometric)

Period of use, reference database, input data, and the identity of verifying
natural persons are **deployment-specific payloads**. Warrant carries them as
`evidence` blob hashes with a policy that pins their schema — the format is
agnostic. This profile does **not** specify that schema; a biometric deployment
needs its own.

### Article 19 + Article 26(6) — retention

| Requirement | What the format gives you | What it does not |
|---|---|---|
| Keep logs ≥ 6 months | the store is ordinary files: back them up like any other data | Warrant has **no** retention mechanism, no expiry, no GC — retention is your infrastructure's job, and this profile does not pretend otherwise |

---

## 2. GDPR interaction (read this before shipping)

An append-only, hash-chained store and a right to erasure are in direct tension.

- **Do not put personal data in a warrant body.** Bodies are small and are meant
  to be quotable forever.
- Put personal data behind an `evidence` **hash**, in storage you can actually
  delete. Deleting the blob leaves the hash citation intact and resolvable-as-
  missing: the record still proves *that* a decision cited some evidence, and the
  verifier reports the reference as unresolved rather than silently passing.
- The same applies to `subject`: prefer a hash of the request over the request.
- A `prose` reason is free text written by an agent. Treat it as publishable.

This is a design constraint, not a warning label: a chain you cannot lawfully
retain is worse than no chain.

---

## 3. What an Article 12 evidence pack contains

```
pack/
├── .warrants/          the store: signed records + content-addressed blobs
│   ├── records/        one JSON envelope per decision
│   └── blobs/          policy bytes, subjects, ski checks, transcripts
├── manifest.json       what this pack is; which record settles the matter
├── trust.json          actor → public keys, for signature binding
├── policies/           human-readable mirror, filename carries the blob hash
└── README.md           the walkthrough a reviewer reads first
```

A reviewer's whole procedure:

```sh
pipx install warrant-verify
unzip pack.zip
warrant --store pack/.warrants verify --store-mode --json | jq -e '.ok'   # integrity
warrant --store pack/.warrants why <decision-id>                          # the argument
warrant --store pack/.warrants check <check-hash>                         # re-run the reason
```

Nothing in that procedure contacts the deployer.

---

## 4. Honest gaps

Named rather than hidden, because a compliance mapping that overclaims is worse
than none:

1. **Timestamps are unauthenticated.** `ts` is an integer the filer chose. Order
   comes from the `prior` DAG, not from clocks. Article 12 does not mandate
   trusted timestamping, but a reviewer may expect it; RFC 3161 / transparency-log
   anchoring is a real gap (`feat/merkle-anchoring` is unlanded work in this repo).
2. **Actor identity is a key, not a legal person.** Binding `agent-b@vendor2` to
   an accountable entity is an out-of-band trust decision. The verifier is honest
   about this: without a trust configuration it says `binding unverified`.
3. **Completeness is not provable.** A store proves every record in it is
   authentic; it cannot prove no decision was omitted. That is a governance
   property (who is accountable for filing), not a format property.
4. **Settlement semantics are v0.3 DRAFT.** Integrity verification is stable and
   has three independent implementations. Settlement-grade verification is
   specified and implemented but not yet independently gated to the same depth.
5. **This profile has had no legal review.** It is an engineer's reading of the
   Article text.

---

## 5. Status and how to argue with it

This document is DRAFT and deliberately falsifiable. The useful form of
disagreement is a **counter-vector**: a concrete deployment where the mapping in
§1 produces a record a reviewer would reject. File it in `reviews/`.

*Sources: Regulation (EU) 2024/1689, Articles 12, 19, 26, 72. Not legal advice.*
