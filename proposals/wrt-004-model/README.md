# WRT-004 model — `input_manifest` / `input_root`

Design-only. Emits no `warrant.verify-report@v1`, registers no tag, changes
no behaviour in `impl/` or `impl-go/`.

```
python3 gate.py        # the WRT-004 §6 kill gate; exit status is the verdict
python3 gate.py --keep # leave the materialized stores for inspection
```

## What it covers, and what it does not

**Covers:** `input_manifest` and `input_root` — the part of the design whose
central claim is decidable today, that two independent implementations agree
on **bytes**.

**Does not cover:** the judgement half of `@v1`. That needs the closed
issue-code registry WRT-004 §7 leaves open, and shipping it with an
"extension point" there is precisely what sank WRT-003 — two valid reports
over identical inputs hashing differently. The gate says so in its own output
rather than letting a green line imply more than it checked.

## Why the Go is not a translation

`input_manifest.go` was written from the proposal text, not ported from
`input_manifest.py`. A port proves the porter agreed with themselves. Two
implementations from one specification is the only arrangement in which
disagreement is evidence about the *specification*.

It found one immediately: Go's `encoding/json` escapes `<`, `>` and `&`
unless told not to, so a store containing `blobs/a<b>c&d` produces different
manifest bytes in the two languages for the same files. That is in the corpus
because a corpus of well-behaved ASCII stores would have passed on day one
and proved nothing.

## Result

The gate passes. 9/9 mutations of the two implementations fail it:

| Mutation | |
|---|---|
| Go re-enables HTML escaping | caught |
| Go sorts by role instead of path | caught |
| Go drops the duplicate-path check | caught |
| Go omits the trust-config entry | caught |
| Python escapes non-ASCII | caught |
| Python drops the domain separator | caught |
| Python skips empty files | caught |
| Python drops the duplicate-path check | caught |
| Python misclassifies blobs as `other` | caught |

**Three findings were in the gate, not the implementations**, and are worth
recording because a harness that is wrong in the safe direction is the
failure mode this repository keeps meeting:

1. The root check compared `bytes` to a hexdigest `str` — vacuously false,
   so it "failed" against two implementations that were correct.
2. The mutation sequence compared each root against *every* previously seen
   root, and the sequence ends by removing the file it added — so returning
   to an earlier manifest read as a collision. It now compares against the
   state immediately before each mutation, which is the actual property.
3. One mutation edited the string `ensure_ascii=False` in a **docstring**
   rather than in the code, and passing proved nothing. Anchors now target
   the code path.

The duplicate-path rule (§3.1) is unreachable from store bytes — a
filesystem holds one file per path — so it is exercised through a trust
config whose basename collides with a store-relative path. Without that
case, one implementation could drop the check and the gate would not notice.

## Not covered by the corpus, stated rather than assumed

Symlinks and unreadable files are specified in §3.1 but are filesystem
states, not byte content, and a JSON fixture cannot carry them. They need a
separate materializing test.
