# Cross-vendor witnessing — the seam a hosted platform can't serve

Two AI agents at **different vendors**, sharing **no identity provider**, jointly
settle an outcome. Each vendor co-signs the same decision. Later, a third party —
a dispute handler, an auditor, a court — needs to confirm that *both* consented.

A hosted log can't do this: Microsoft won't verify a chain of Google's agents for
free, and either vendor's log is just one party's word. A co-signed warrant can,
because verification runs from the bytes, and the **verifier** supplies the
keyring — trusting neither vendor's server.

```bash
cd demos/cross-vendor
warrant --store .warrants verify --settlement --trust-config trust.json
```

```
INFO 62b770f1e1af  signature bound: key 64c30815ff26 claims actor agent@vendor-a
INFO 62b770f1e1af  signature bound: key 4508a07aa941 claims actor auditor@vendor-b

verify: 1 records, 0 errors, 0 warnings
```

**Both signatures bound, zero warnings.** The record is one `accept` — a
cross-vendor settlement of order ORD-7788 — co-signed by `agent@vendor-a` and
`auditor@vendor-b` over the same WarrantID, `under` a **2-of-2** threshold policy
pinned by hash. `trust.json` is the *verifier's* keyring, naming who each vendor
is; neither vendor supplied it.

## You are the root of trust, not either vendor

Drop `--trust-config` and the tool refuses to assume who the keys belong to:

```bash
warrant --store .warrants verify        # binding unverified — bring your own keyring
```

Trust only vendor A (leave vendor B out of your `trust.json`) and vendor A binds
while vendor B stays unproven — the verifier decides, always.

## Forgery doesn't survive

Flip one nibble of vendor B's co-signature and re-verify:

```
INFO 62b770f1e1af  signature bound: key 64c30815ff26 claims actor agent@vendor-a
ERR  62b770f1e1af  bad signature by auditor@vendor-b        (exit 1)
```

A forged consent is caught; vendor A's real signature is unaffected. This is what
makes the record *settlement-grade*: two independent parties, one tamper-evident
proof, verifiable by a third who trusts neither.

Rebuild from scratch: `python3 build.py` (deterministic — same hashes every time).
Format: [`../../EVIDENCE-PACK.md`](../../EVIDENCE-PACK.md).
