# A settled question, reopened by a consequence nobody had drawn

`demos/air-canada` shows one decision with one re-runnable reason. That proves a
check re-runs. This demo shows the thing the format is actually for, and which
nothing else in the repository demonstrates end to end:

> **a settlement that cannot be reopened by argument, can be reopened by a
> demonstrable consequence, and whose reopening propagates by itself to every
> decision built on top of it.**

Build it and watch, in about a second:

```bash
python3 demos/refund-chain/build.py
```

Then check the pack the way a stranger would, with no trust in whoever built it:

```bash
python3 impl/warrant.py --store demos/refund-chain/pack/.warrants verify
python3 impl/fact_provenance.py --store demos/refund-chain/pack/.warrants
```

## The three acts

**ACT I — the chain.** Three decisions: *eligibility*, then *timeliness*, then
*grant*. The first two rest on observations, and their provenance documents say
so: a person at a desk read a form and wrote down what they saw. Nothing about
those facts is proven, and the record does not pretend otherwise.

The third is different. Its two facts are not observations at all — each is the
**answer of a prior decision**, cited by that decision's WarrantID:

```
fact eligible: bool = true from "87d423187c7d…"
fact timely:   bool = true from "c11f646902b2…"
```

Nobody retyped a verdict. A verifier re-runs the cited check and recovers the
value, so a wrong number here is not something a reviewer has to notice: it is
`contradicted`, mechanically. This is [WRT-008](../../proposals/WRT-008-fact-provenance.md).

**ACT II — an objection made of words.** An objector files a re-litigation
carrying one prose reason: the grant *does not sit right with the spirit of the
policy*. The format answers, from `settlement_admissibility()` and not from this
README:

```
§7 verdict: inadmissible: cites nothing new
```

The store does not change. Rhetoric is legal; SPEC §3.1 puts it exactly: *"it
just doesn't count as proof."*

**ACT III — a consequence nobody had drawn.** The policy has four clauses, and
all four have been pinned in `under` since the first decision. Clause 4 requires
travel to begin within 10 days of the death. The claim blob has said
`days_between_death_and_travel: 45` since the first decision too.

Nobody ever compiled the two together. Someone now does:

```
check days_between_death_and_travel <= max_days_under_clause_4     -> false
```

**No new evidence is filed.** The re-litigation cites exactly one evidence hash,
the same claim blob the first decision cited, so §7(a) cannot admit it. It is
admitted on the other ground, and the build script *asserts* this rather than
narrating it — if the demo were ever admitted under (a) it would fail to build:

```
evidence cited: only 42e274376bef…, already in the tunnel
§7 verdict: admissible: (b) new outcome fingerprint
```

The settlement reopens and eligibility is superseded.

## The payoff

The grant was filed sixty days before any of this. No registry recorded that it
depended on the eligibility decision. No service notified it. Nobody remembered
the dependency existed.

Re-check it today and its own provenance document is enough:

```
grant, re-checked today:
  !! eligible   stale     cited warrant was superseded by 861f3c6b5b54…
     timely     derived   from c11f646902b2…
```

`stale` is not an opinion about the grant. It is two mechanical facts at once:
the cited decision **still re-runs** to the value this policy pinned, **and**
that decision has been replaced. Offline, from the bytes, by anyone.

That is the honest version of the ambition. The format does not stop a wrong
observation from entering. It makes the discovery of one **propagate**.

## Two answers, and they are not the same question

The two commands above deliberately disagree, and that is the discipline SPEC
§6(7) requires rather than a defect:

| Command | Answer | What it means |
|---|---|---|
| `warrant … verify` | 5 records, **0 errors** | every record is well-formed, signed, and its check re-runs to its own `expect` |
| `fact_provenance.py` | **1 finding** (exit 1) | one derived fact rests on a decision that has since been replaced |

The profile also reports, per record, whether it saw *all* of that record's
provenance: `complete`, `not-applicable` (a record that legitimately cites
none), or `incomplete` (some cited evidence is missing or off-address, so a
removed provenance document cannot be told from one that never existed).

A store can be perfectly valid and still be resting on something that moved.
Collapsing those two into one green token is the defect this stack keeps
finding in its own reviews; keeping them apart is the whole point.

## Honest scope

- The story is modelled on **Moffatt v. Air Canada, 2024 BCCRT 149**, in which
  an airline chatbot told a passenger a bereavement fare could be claimed
  retroactively and the tribunal held the airline liable. **Clause 4 and the
  45-day interval are invented for this demo.** They are not that case's facts.
- The `warrant.fact-provenance@v0` profile is a **proposal**
  ([WRT-008](../../proposals/WRT-008-fact-provenance.md) rev 4), not an adopted
  part of the specification. It has had **three** adversarial gates, all AMEND,
  every finding closed with a negative fixture, plus two more the proposal's own
  [binding enumeration](../../proposals/wrt-008-model/BINDING-EDGES.md) found
  before a reviewer did. Three rounds by one reviewer on one host is not
  adoption. A base-grade verifier ignores the provenance blobs entirely and is
  still conformant.
- **A derivation must also be cited.** A fact may only derive from a warrant
  inside the citing record's `prior` closure, because SPEC §7 builds the
  settlement tunnel from `prior`: a dependency outside it would be invisible to
  re-litigation, and the propagation above would silently not happen.
- **The profile checks no signature.** Where it prints a record's actor it says
  so. Whether a record was signed by the actor it names, and whether that key is
  theirs, is SPEC §5.1 with a trust configuration, in `warrant verify`.
- **`derived` is not whole-chain validity.** It means the immediate cited
  answer matched what the policy pinned. If that decision itself rests on a
  contradicted value, the whole-store report surfaces it there, not here.
- **Staleness is transitive but bounded.** If the decision a fact came from
  itself rested on something since replaced, the staleness travels through the
  named link. The walk has a depth limit, a record budget and a cycle guard,
  and hitting any of them is reported as `underived`, never as success.
- Provenance **never changes the term.** Every check in this pack compiles
  byte-identically with its `from` clauses stripped; `tests/fact_provenance.py`
  enforces it.
- Re-running a cited check proves what it computes, never that its author had
  standing to decide. Authority stays where SPEC §5 and §12 put it: in the
  verifier's own trust configuration.
- The five `binding unverified` warnings from `verify` are expected — the demo
  ships `trust.json` but the command above does not load a keyring. That is
  SPEC §5.1 reporting an unconfigured keyring, not a defect in the pack.

## The envelope

The build also writes `refund-chain.pdf`: the entire pack as **one file that is
both a readable document and its own archive**. It opens in Preview, Acrobat or
a browser as a one-page summary of the chain, and it runs as a Python script:

```bash
python3 demos/refund-chain/refund-chain.pdf --extract /tmp/pack
python3 impl/warrant.py --store /tmp/pack/.warrants verify
```

The extracted store is byte-identical to the one in `pack/`, and the same input
always produces the same output bytes, so the envelope is content-addressable.

**It deliberately does not verify itself.** A self-executing document that
prints its own green checkmark proves nothing: whoever edited the evidence
edited the checker in the same edit. So running it extracts and lists, and
points you at a verifier you obtained independently. `tests/pack_pdf.py`
enforces that absence — it fails if the envelope ever prints `verified`, `sound`
or `Q.E.D.` about its own contents, and if the embedded runner ever gains an
`exec`, an `import` or a `subprocess`.

## Files

| Path | What it is |
|---|---|
| `build.py` | builds the pack through the real libraries; every hash and ATP figure comes from the code, none is hand-computed |
| `policies/1-eligibility.wpl` | link 1 — two observed facts |
| `policies/2-timeliness.wpl` | link 2 — the clause the chatbot got wrong |
| `policies/3-grant.wpl.tmpl` | link 3 — two **derived** facts; WarrantIDs substituted at build time, as `.warrant/gate.wpl` substitutes its measured facts |
| `policies/4-proximity.wpl` | the check nobody ran |
| `pack/` | the generated evidence pack: store, `trust.json`, `manifest.json`, readable mirrors |
| `refund-chain.pdf` | the envelope: the whole pack as one file that opens as a document and runs as its own archive |
