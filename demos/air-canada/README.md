# Verify what an AI agent decided — in 15 minutes, on your own machine

You are a skeptic. A company tells you their AI agent refused a customer request
*for a good reason, under the policy in force*. Normally you have to take their
word for it — the log lives on their server, in their format, editable by them.

This pack lets you check the claim yourself. **Offline. Trusting nothing but the
source code of one small tool.** No account, no server, no vendor dashboard.

The story is real: **Moffatt v. Air Canada (2024 BCCRT 149)**. An airline
chatbot told a passenger a bereavement fare could be claimed retroactively. It
could not. The tribunal held Air Canada liable — in part because the airline
could not produce a trustworthy record of what its own policy was and whether
the action was authorized against it. This pack is the record they *would* have
had if the agent were sealed.

---

## The 30-second version — two commands, no demo script

```bash
cp -r demos/air-canada/pack/.warrants /tmp/w && \
python3 impl/warrant.py --store /tmp/w verify --json; echo "exit $?"

# change one byte in the policy the records name in `under`
python3 - <<'PY'
p="/tmp/w/blobs/c8d453b05c7dd21027767419cfe77c3fc264b638fc8fd3fa760f2b6c7d684d72"
b=open(p,"rb").read(); i=next(i for i,c in enumerate(b) if chr(c).isdigit())
open(p,"wb").write(b[:i]+b"7"+b[i+1:]); print("changed byte %d" % i)
PY

python3 impl/warrant.py --store /tmp/w verify --json; echo "exit $?"
```

Before: `"ok":true`, **exit 0**. After: `"ok":false`, **exit 1**, and two
findings reading `blob c8d453b05c7d content does not match its address`.

The decision records are untouched. The verifier is the same binary. One
byte moved in the file those records name by hash, and the exit status
changed. Read the two JSON reports yourself — that is the whole claim, and
nothing between you and it is interpreting anything.

> ### Why there is no demo script here any more
>
> There was one, `tamper.py`, and it is **closed**. It still runs and now
> exits non-zero, because its oracle produced a false PASS: it required an
> error message to *contain the tampered digest*, which is not the same as
> the report asserting a content-address mismatch. Rewriting both errors to
> `blob c8d453b05c7d could not be read: permission denied` — right digest,
> right subjects, wrong claim — printed five PASS lines and declared the
> tamper detected.
>
> An earlier version of the same script tampered with the passenger's
> **request** blob while calling it the policy. Both times the mechanism was
> fine and the wrapper around it was the defect.
>
> The result worth keeping: this claim does not need a clever demo. Two raw
> verifier runs and a visible one-byte diff say it completely, and every
> interpretive layer added more false-PASS surface than value. What follows
> below is the same thing at human speed, with the pack, the trust config
> and the signatures explained — prose you can check against the commands
> above rather than a program that checks itself.

---

## 0. Install the verifier (~2 min)

One line (Python 3.9+):

```bash
pipx install warrant-verify    # or: pip install warrant-verify
```

The tool is ~1200 lines of Python you can read in an afternoon (`impl/warrant.py`).
The only dependency is `cryptography` (for Ed25519). The Σ-GLYPH check engine is
bundled, so **nothing below needs a network connection.**

Then grab this pack and step into it:

```bash
git clone https://github.com/s0fractal/warrant
cd warrant/demos/air-canada/pack        # the evidence pack lives here
```

---

## 1. Check integrity — every hash, signature and link (~2 min)

```bash
warrant --store .warrants verify
```

```
WARN 7d8f2e7db315  binding unverified (no keyring): key bc7cbcb56363 claims actor chatbot@aircanada
WARN 9084cd23f205  binding unverified (no keyring): key 55154f42065e claims actor policy-guard@aircanada

verify: 2 records, 0 errors, 2 warnings
```

**0 errors.** Every record's ID equals the hash of its own content, every
signature checks out, every policy and evidence reference resolves, and the
`prior` links form an intact chain.

The two warnings are the tool being honest, not a failure: it will not *assume*
which public key belongs to `policy-guard@aircanada` — you haven't told it who
to trust yet. We fix that in step 4. (Exit code is 0.)

---

## 2. Re-execute the agent's reason yourself (~3 min) — the point

The refusal cites a check. Don't trust its verdict — **re-run it:**

```bash
warrant --store .warrants check b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
```

```
pass  result=65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  atp_spent=17
```

You just evaluated, on your own machine, the deterministic policy rule the agent
pinned — `permit = within_window AND NOT retroactive`, over the facts of this
request (`retroactive = true`). It reduces to **Church-FALSE** (`65cd957f…` — the
Σ-GLYPH NodeHash of "false") in **17 units of metered work**. "Not permitted." You
did not trust Air Canada's servers, or ours, to tell you the answer — you
*computed* it from the policy and the facts.

This is the property no log and no dashboard can give you: *it is safe to re-run
a stranger's `ski@v1` reason on your own machine*. The computation is total,
integer, and budget-bounded — it cannot loop, cannot run away, cannot touch your
disk. The same bytes give the same hash on any of the three independent Σ-GLYPH
implementations (Python, Go, Rust).

The rule itself is readable. It is written in WPL — `policy.wpl` beside this
file — and compiled to the term you just ran:

```
fact within_window: bool = true
fact retroactive:   bool = true

check within_window && !retroactive
```

Recompile it yourself and you get the same check hash, the same result and the
same 17 ATP; the source is in the pack (`policies/check-source.*.wpl`) and in
the store, so the term this record cites can be traced back to a rule you can
read. See [`../../docs/authoring-checks.md`](../../docs/authoring-checks.md) to
write your own.

> **Honest scope.** This does *not* re-run the chatbot's neural reasoning — that
> is not reproducible, and we don't pretend it is. It reproduces the
> **deterministic policy rule around the decision**: what the policy said, and
> that the action was measured against it. That is exactly what a regulator or a
> court needs, and exactly what Air Canada could not produce.

---

## 3. Read the whole decision as a chain (~2 min)

```bash
warrant --store .warrants why 9084cd23f205cdd6e013deb6c6e2a84e4a5f4f469fb8f77ba443dfed44716f5a
```

```
REJECT 9084cd23f205cdd6 by policy-guard@aircanada  subject=494ad3316bfa retroactive bereavement refund request
  - prose: policy clause 2: bereavement discount cannot be claimed retroactively
  - check b423b6a82c34 [ski@v1] -> pass
  under policy c8d453b05c7d
  PROPOSE 7d8f2e7db31500ba by chatbot@aircanada  subject=494ad3316bfa retroactive bereavement refund request
    - prose: passenger requested a refund
    under policy c8d453b05c7d
```

The chatbot **proposed** the refund; the policy guard **rejected** it, citing the
re-runnable check and the exact policy clause. `under c8d453b05c7d` pins the
*bytes* of the policy that was in force — read them in `policies/`. Nobody can
later claim a different policy applied.

---

## 4. Now tell it who to trust — clean green (~1 min)

The pack ships a `trust.json` binding each actor to its public key. Supply it:

```bash
warrant --store .warrants verify --settlement --trust-config trust.json
```

```
INFO 7d8f2e7db315  signature bound: key bc7cbcb56363 claims actor chatbot@aircanada
INFO 9084cd23f205  signature bound: key 55154f42065e claims actor policy-guard@aircanada

verify: 2 records, 0 errors, 0 warnings
```

**0 errors, 0 warnings.** The keyring is *yours* — you decide who
`policy-guard@aircanada` is. The tool never ships you a root of trust you're
forced to accept.

---

## 5. Try to cheat (~3 min) — watch it break

Copy the pack and quietly edit one field of the refusal — say, soften the note:

```bash
cp -r . /tmp/tampered && cd /tmp/tampered
# edit .warrants/records/9084...json — change subject.note to anything
warrant --store .warrants verify
```

```
ERR  9084cd23f205  WarrantID mismatch: recomputed a different id

verify: 2 records, 1 errors, 1 warnings   (exit code 1)
```

One byte changed → the record's own ID no longer matches its content → **error,
exit 1.** There is no quiet edit. This is why the record can settle a dispute:
its integrity does not depend on who is storing it.

---

## What you just proved without trusting anyone

In fifteen minutes, with a tool you can read and no network, you confirmed:

1. **What** was decided (a refusal), **by whom** (a keyed actor *you* chose to trust),
2. **Under which policy** — pinned to exact bytes, not "the policy" from memory,
3. **Why** — a reason you re-executed yourself and got the same answer,
4. That **nothing was edited after the fact.**

That is *settlement-grade action provenance*: a record whose credibility does not
depend on the party that produced it. Air Canada lost because they had a chatbot
and no such record. This is the record.

→ Format details: [`../../EVIDENCE-PACK.md`](../../EVIDENCE-PACK.md) ·
Rebuild this pack from scratch: `python3 ../build.py`
