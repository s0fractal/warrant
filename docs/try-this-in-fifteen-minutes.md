# Try this in fifteen minutes

Someone wants to know whether this tool works for anybody but its authors. That
is the whole request. Nothing is watched, measured, or sent anywhere. The network is needed in two
stages — installing the package from PyPI, which also fetches its dependencies,
and downloading one evidence pack — and everything else runs locally, including
the part that re-executes somebody else's reasoning.

There are two parts. **Part B is the one that matters** — it is the part where
your computer re-executes somebody else's reasoning and gets the same answer.
Part A takes four minutes and shows you the shape of the record first.

## The claim being tested

> A stranger can take a portable record of a machine-mediated decision, see which
> exact inputs, policy bytes, checks and signatures it names, re-execute at least
> one bounded reason on their own machine, detect tampering, and state what the
> record does not establish.

Note what is *not* claimed: not that the decision was correct, not that the
policy was wise, not that anyone was authorised in any legal sense.

## Set up, once, for both parts

Everything below happens inside one throwaway directory, so nothing can land in a
directory of yours by accident:

```sh
cd "$(mktemp -d)" && pwd
python3 -m venv .venv
. .venv/bin/activate
python -m pip install warrant-verify==0.9.0
```

Confirm what you got:

```sh
python -m pip show warrant-verify | head -2
ls "$(dirname "$(command -v warrant)")" | grep '^warrant'
```

Expect version `0.9.0` and four commands: `warrant`, `warrant-anchor`,
`warrant-mcp`, `warrant-mcp-server`. No clone and no build; the Σ-GLYPH check
engine ships inside the wheel, which is what makes Part B work offline.

If you prefer `pipx install warrant-verify==0.9.0`, that works too — but then
check the version with `pipx list` rather than `python -m pip show`, which looks
in the wrong environment. Everything below assumes the venv above.

---

## Part A — the shape of a record (about four minutes)

You are already in the throwaway directory from the setup step.

```sh
git init -q .

warrant init
warrant keygen --out me.key
printf 'demo diff\n' > diff.patch
printf 'clause 1: no coverage drop\n' > policy.txt
printf '#!/bin/sh\nexit 1\n' > check.sh && chmod +x check.sh

POL=$(warrant policy add policy.txt)
P=$(warrant propose --subject diff.patch --under $POL \
      --reason "utility fns needed" --actor me@host --key me.key)
R=$(warrant reject $P --check check.sh --verdict fail \
      --reason "clause 1: coverage drop" --actor me@host --key me.key)
printf '#!/bin/sh\nexit 0\n' > check.sh
A=$(warrant accept $R --check check.sh --verdict pass \
      --actor me@host --key me.key)

warrant why $A
warrant verify
```

`warrant verify` ends with `3 records, 0 errors, 3 warnings`. The warnings say
`binding unverified (no keyring)`: nothing here vouches that this key belongs to
`me@host`, so the tool reports the signature instead of believing it. That is the
intended answer.

**Then break it:**

```sh
python3 - <<'PY'
import json, pathlib
p = sorted(pathlib.Path(".warrants/records").glob("*.json"))[0]
d = json.loads(p.read_text())
d["body"]["actor"]["id"] = "someone-else@host"
p.write_text(json.dumps(d))
print("rewrote the deciding actor in", p.name[:12])
PY

warrant verify
```

Verification must now report `WarrantID mismatch` and at least one **error**, not
a warning. If it still says `0 errors`, stop reading and tell us — that is the
most valuable thing this page could produce.

Nothing needs cleaning up: everything lives under the temporary directory printed
by the setup step, and your shell has not left it. Note that `git checkout` would
not have undone the tamper — `.warrants/` was never committed.

### What Part A establishes, exactly

- the record chain is intact and each record's identity is its own content hash;
- rewriting any field is detected;
- the policy bytes in force are pinned by hash, not by name;
- a signature is present and is *not* believed without a keyring.

### What Part A does not establish

- **it does not re-run the `cmd@v1` check.** `verify` does not execute shell
  checks — their trust model is the container that ran them, not your machine.
  The verdict `pass` in the record is a claim by whoever filed it;
- it does not evaluate the policy: `policy.txt` is bytes, not a rule the tool
  interprets;
- it does not establish authority — nothing here says `me@host` was allowed to
  decide anything;
- it therefore does not show that an action *was allowed*. It shows what was
  recorded, and that the record has not moved since.

---

## Part B — re-execute somebody else's reason (about six minutes)

This is the part that distinguishes the tool from a signed log. You will run a
check that someone else authored, on your machine, offline, and get a
bit-identical result — or find out that you do not.

Still in the same directory:

```sh
curl -LO https://github.com/s0fractal/warrant/releases/download/v0.8.0/air-canada-pack.zip
shasum -a 256 air-canada-pack.zip
```

Expect exactly:

```
74b36f1d5c7777ea9a3ee240e32f992483a3cd2c0dda0c7d065229c49f1a8249  air-canada-pack.zip
```

If the digest differs, stop: you did not get the file this page describes.

```sh
unzip -q air-canada-pack.zip

warrant --store air-canada-pack/.warrants verify
warrant --store air-canada-pack/.warrants verify --settlement \
        --trust-config air-canada-pack/trust.json
warrant --store air-canada-pack/.warrants why \
        9084cd23f205cdd6e013deb6c6e2a84e4a5f4f469fb8f77ba443dfed44716f5a
warrant --store air-canada-pack/.warrants check \
        b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
```

Expected, in order:

1. `verify: 2 records, 0 errors, 2 warnings` — the two warnings are the unbound
   keys again, because you have not told it whose keys those are;
2. with the pack's own keyring and `--settlement`: `2 records, 0 errors, 0
   warnings`, and two `signature bound` lines naming `chatbot@aircanada` and
   `policy-guard@aircanada`;
3. `why` prints the chain: a REJECT resting on a `ski@v1` check and a policy
   hash, standing on the earlier PROPOSE;
4. and the line this whole page exists for:

```
pass  result=65cd957fee7ec9fb310bc9d9712cec1726c78f8026fda679ac8f237938a32098  atp_spent=17
```

That is your machine re-running the reason someone else recorded, reaching the
same normal form, and spending exactly 17 units of a budget fixed in advance.
Not a claim you are asked to believe — an answer you computed.

**The negative control**, and it must be able to fail the claim:

```sh
cp -r air-canada-pack tampered
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("tampered/.warrants/blobs/"
                 "b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f")
d = json.loads(p.read_bytes()); d["expect"] = "f" * 64
p.write_bytes(json.dumps(d, sort_keys=True, separators=(",", ":")).encode())
print("rewrote what the check expects")
PY

warrant --store tampered/.warrants check \
        b423b6a82c3451bfbd75563b39e6391093a64db57941d9247a61a6c620bd997f
warrant --store tampered/.warrants verify
```

`check` must now print `fail` and exit non-zero, and `verify` must report both
`content does not match its address` and `ski@v1 verdict mismatch: claimed pass,
re-run gives fail`. If a tampered check still reports `pass`, the central claim
of this tool is false and we want to know today.

### What Part B establishes, exactly

- a bounded reason authored elsewhere re-executes on your machine, offline, to a
  bit-identical result and an exact cost;
- a rewritten check is detected, and a false verdict claim is reported as a
  dispute rather than silently accepted;
- with a keyring you supply, signatures bind to named actors.

### What Part B does not establish

- **the keyring came inside the same zip.** Binding is relative to trusting that
  file; a real deployment gets its trust config out of band, and until it does,
  "bound" means "consistent with the keyring you were handed";
- the pack is a **reconstruction** of the record an airline *would* have had in
  *Moffatt v. Air Canada* (2024 BCCRT 149). It was authored by this project as a
  demonstration. Air Canada produced no such record; nothing here is evidence
  about that company's actual systems;
- one re-executed reason is one reason. Nothing says the policy was right, that
  the refusal was fair, or that a court would care.

---

## What to send back

Whatever you found — none of this is a test of you.

```
1. How long did it take, from the install command to the `check` line?
2. Where did you stop, re-read, or guess? Quote the exact line.
3. Did Part A's tamper report an error, and did Part B's tampered check say fail?
4. What did you expect a tool like this to do that it did not?
5. Would you use it for anything of your own?   no / maybe, for: ___
6. Anything that read as dishonest or overclaimed?
```

**"I would not use this" is a complete and useful answer**, and question 6 is
worth more than the other five together. This is being evaluated, not sold.

## Provenance of this page

Every command above was run on 2026-08-23 in a fresh `mktemp -d` directory and an
empty virtualenv, against `warrant-verify==0.9.0` from PyPI, with no checkout of
this repository. The blocks on this page were extracted and executed unmodified to produce
[`handoff-transcript-2026-08-23.md`](handoff-transcript-2026-08-23.md), which
records each command, its output and its exit status, and states exactly what the
capture mechanism does to the display.

Nobody outside this project has adopted, reviewed, or endorsed it. That absence
is the reason you are being asked.
