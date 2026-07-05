# Warrant

**A decision record for AI agents. Signed, hash-addressed, with reasons you can re-run.**

When an agent accepts, rejects, or proposes something, it writes a warrant: a small JSON record that says **what** was decided, **under** which policy, **because** of which reasons, based on **which** evidence — signed by the actor, addressed by its own hash, linked to the decisions that came before it.

```json
{
  "decision": "reject",
  "subject":  { "hash": "d5cf37…", "note": "PR-42" },
  "under":    [ "cb3a0a…  (policy in force, by hash)" ],
  "because":  [
    { "kind": "check", "check": "05d234…", "runtime": "cmd@v1",
      "verdict": "fail", "transcript": "9dc0c3…" },
    { "kind": "prose", "text": "policy clause 1: coverage drops 87.0 -> 84.2" }
  ],
  "evidence": [ "9dc0c3…" ],
  "actor":    { "id": "agent-b@vendor2" },
  "prior":    [ "00f79f…" ],
  "ts":       1751677200
}
```

The record's hash is its identity. Change one byte of the decision, the policy reference, or the reasons — the hash changes, and every later record that cited it stops resolving. Nothing can be quietly edited after the fact.

## Why not just logs?

A trace tells you what an agent did. A warrant proves **why it was allowed to** — and the proof survives the agent. Logs are mutable, vendor-shaped prose. Warrants are:

- **Immutable** — identity is the hash of the content.
- **Signed** — you know which actor decided.
- **Anchored** — `under` pins the exact bytes of the policy that was in force, not "the policy" in someone's memory.
- **Re-checkable** — a reason can be an executable check. Anyone can re-run it and get the same verdict.
- **Linked** — `prior` makes decisions a chain: propose → reject (with reasons) → revise → accept. `warrant why <hash>` walks the whole chain.

A rejection is a first-class record, not an absence. This is the part that matters as agents get autonomy: the "no, because" survives, gets cited by hash, and stops the same argument from being re-had from scratch.

## Ten minutes

```bash
git clone https://github.com/s0fractal/warrant && cd warrant
pip install cryptography                       # the one dependency (Ed25519)
alias warrant="python3 $PWD/impl/warrant.py"   # no packaging yet — this is it
```

```bash
warrant init                          # .warrants/ store in your repo
warrant keygen --out me.key           # Ed25519; prints your pubkey
POL=$(warrant policy add policy.txt)  # pin the rules in force -> hash

P=$(warrant propose --subject diff.patch --under $POL \
      --reason "utility fns needed" --actor me@host --key me.key)
R=$(warrant reject $P --check check.sh --verdict fail \
      --reason "clause 1: coverage drop" --actor me@host --key me.key)
A=$(warrant accept $R --check check.sh --verdict pass \
      --actor me@host --key me.key)

warrant why $A                        # decision -> reasons -> checks -> policy, verified
warrant verify                        # every hash, signature, and link in the store
```

The store is plain files, content-addressed, git-friendly. No server, no vendor, no account.

## What it is not

Not an agent framework. Not a blockchain. Not observability. It is one file format and five verbs, designed to be boring: any language can implement it from the spec in an afternoon, and two implementations agree on every hash.

## Spec and status

`SPEC.md` — the format (v0.2), canonicalization rules, and worked test vectors with real hashes and signatures (`examples/`). Reason runtimes: `prose`, `cmd@v1` (a check command run in a container), and — new in v0.2 — **`ski@v1`**: a portable, deterministic, budget-bounded check. The check is a content-addressed SKI term evaluated per [Σ-GLYPH Book I](https://github.com/s0fractal/sigma-glyph); the verdict is a hash comparison; work AND peak memory are bounded by the ATP budget, so re-verifying a stranger's reason is safe by construction. `warrant check <hash>` re-runs one.

`impl/warrant.py` — reference implementation (M1): the five verbs on a plain-file store, one file, stdlib + Ed25519 (`pip install cryptography`). It must pass its own law:

```bash
python3 impl/warrant.py conformance examples   # all SPEC §8 vectors, byte-exact
python3 impl/warrant.py selftest               # live round-trip + tamper detection
```

`impl-go/` — independent Go implementation for cross-checking the spec:

```bash
./impl-go/warrant-go conformance examples      # same SPEC §8 vectors
./impl-go/warrant-go selftest examples         # schema and verification edges
```

First real user: [sigma-glyph](https://github.com/s0fractal/sigma-glyph) files its review adjudications as warrants (`.warrants/` in that repo) — the maintainer's accept/reject decisions are signed, hash-addressed, and cite CI gates as `cmd@v1` checks.

License: MIT.
