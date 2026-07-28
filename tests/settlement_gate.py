#!/usr/bin/env python3
"""Negative-first tests for tools/settle.py.

The interesting cases are all the ways settlement could WRONGLY say SETTLED --
that is the only failure that matters here, because a false SETTLED merges an
unclosed defect while claiming a gate covered it. Every test below is written to
catch that direction first; the happy path gets one case at the end.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
# Runs from the repo AND from a flat staging directory (the adversarial gate
# copies the reviewed files into one). A suite that only runs in its home layout
# cannot be handed to a reviewer, and a gate that cannot run the suite is a gate
# reviewing prose.
sys.path[:0] = [str(ROOT / "tools"), str(HERE)]
import settle as S                                          # noqa: E402

_pol = next(p for p in (ROOT / "policies" / "gate-settlement.json",
                        HERE / "gate-settlement.json") if p.exists())
POLICY = json.loads(_pol.read_text())
OLD, NEW = "a" * 64, "b" * 64
FAILED = 0


def check(name, got, want):
    global FAILED
    ok = got == want
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (want {want})"))
    if not ok:
        FAILED += 1


def ledger(family, subject, findings, at="2026-07-28T10:00:00Z", item="x"):
    return {"item": item, "family": family, "model": family, "host": "h",
            "produced_at": at, "subject_sha256": subject, "subject_label": "L",
            "review": "r.md", "findings": findings}


def finding(fid, clause, reproduced, severity="P0", repro=None, transcript=None):
    return {"id": fid, "severity": severity, "clause": clause, "title": fid,
            "repro_sha256": repro or ("c" * 64), "exit": 0,
            "transcript_sha256": transcript or ("d" * 64), "reproduced": reproduced}


def run(ledgers, current=NEW):
    """`current` is always passed explicitly: settle() never infers it.

    Inferring it from ledger timestamps was a P0 (Codex, 2026-07-28) -- see the
    regression at the end of this file.
    """
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        for i, led in enumerate(ledgers):
            (d / f"{i:02d}.json").write_text(json.dumps(led))
        return S.settle("x", POLICY, d, current)


three = ["codex@openai", "kimi@moonshot", "gemini@google"]

# 1. A reproduced P0 on the current subject blocks, no matter how many families
#    say nothing about it. Silence from others is not acquittal.
check("reproduced P0 blocks",
      run([ledger(f, NEW, [finding("F1", "D.3", True)] if f == three[0] else [])
           for f in three])["state"], "BLOCKED")

# 2. THE FAILURE THIS TOOL EXISTS TO PREVENT. A defect reproduced against rev N,
#    never re-run against rev N+1, must NOT settle by ageing out of the tunnel.
check("stale finding does not age out",
      run([ledger(three[0], OLD, [finding("F1", "D.3", True)], at="2026-07-01T00:00:00Z")]
          + [ledger(f, NEW, [], at="2026-07-28T10:00:00Z") for f in three])["state"],
      "UNRESOLVED")

# 3. Re-run against the current subject and now refuted -> the claim is closed by
#    evidence, which is the only way a claim is allowed to close.
check("refuted on current subject clears",
      run([ledger(three[0], OLD, [finding("F1", "D.3", True)], at="2026-07-01T00:00:00Z")]
          + [ledger(f, NEW, [finding("F1", "D.3", False)], at="2026-07-28T10:00:00Z")
             for f in three])["state"], "SETTLED")

# 4. One family is never enough, however thorough. Six Codex rounds found no P0;
#    the first three-family round found six.
check("one family cannot settle",
      run([ledger(three[0], NEW, [finding("F1", "D.3", False)])])["state"], "OPEN")

# 5. Assertions have no blocking power. A finding that did not reproduce is a
#    Question -- this is what keeps a tireless reviewer from stopping the queue.
check("non-reproducing finding never blocks",
      run([ledger(f, NEW, [finding(f"F{i}", f"D.{i}", False)])
           for i, f in enumerate(three)])["state"], "SETTLED")

# 6. Same clause, different repro bytes and a different transcript: a restatement,
#    not a second defect. Without this a reviewer perturbs the code forever.
rest = run([ledger(three[0], NEW, [finding("F1", "D.3", True, repro="e" * 64)]),
            ledger(three[1], NEW, [finding("F9", "D.3", True, repro="f" * 64,
                                           transcript="9" * 64)]),
            ledger(three[2], NEW, [])])
check("same clause restated is one claim", rest["claims_total"], 1)
check("restatement is recorded, not silent", len(rest["restatements"]), 1)

# 7. Different clauses are different defects even from one family.
check("distinct clauses are distinct claims",
      run([ledger(three[0], NEW, [finding("F1", "D.3", True),
                                  finding("F2", "D.4", True)])])["claims_total"], 2)

# 8. A finding that names no clause must not merge into another claim. Unnamed
#    means unmatchable, and unmatchable must err toward blocking.
unc = run([ledger(three[0], NEW, [finding("F1", "", True)]),
           ledger(three[1], NEW, [finding("F2", "", True)]),
           ledger(three[2], NEW, [])])
check("unclassified findings stay separate", unc["claims_total"], 2)
check("unclassified findings block", unc["state"], "BLOCKED")

# 9. P2 is below the policy's blocking bar and must not hold the queue.
check("P2 does not block",
      run([ledger(f, NEW, [finding("F1", "D.9", True, severity="P2")])
           for f in three])["state"], "SETTLED")

# 9a. REGRESSION, P0 found on this file's own gate. Severity was `max()` over
#     strings; in ASCII '?' > '1' > '0', so the least severe label won and an
#     unparsed `P?` beat a real P0. One unlabelled finding sharing a clause with
#     a reproduced P0 disabled the whole claim and the item read SETTLED.
mixed = run([ledger(three[0], NEW, [finding("F1", "D.3", True, severity="P0")]),
             ledger(three[1], NEW, [finding("F2", "D.3", True, severity="P?",
                                            repro="e" * 64)]),
             ledger(three[2], NEW, [])])
check("unlabelled sibling cannot mask a P0", mixed["state"], "BLOCKED")
check("most severe label wins, not the lexical max",
      mixed["blocking"][0]["severity"] if mixed["blocking"] else None, "P0")

# 9b. A reproduced finding whose severity the harness could not read blocks on
#     its own. Unknown is not harmless -- it means nobody knows how bad it is.
check("unparsable severity blocks by itself",
      run([ledger(f, NEW, [finding("F1", "D.7", True, severity="P?")])
           for f in three])["state"], "BLOCKED")

# 9c. And the ranking is by severity, not by string order, in the other
#     direction too: P0 must win over P1, which lexical max got backwards.
check("P0 outranks P1",
      run([ledger(three[0], NEW, [finding("F1", "D.5", True, severity="P1"),
                                  finding("F2", "D.5", True, severity="P0",
                                          repro="a" * 64)])])["blocking"][0]["severity"],
      "P0")

# 10. The policy is pinned by hash in the report: a decision taken under other
#     rules must not be mistakable for one taken under these.
_cli = next(p for p in (ROOT / "tools" / "settle.py", HERE / "settle.py") if p.exists())
r = subprocess.run([sys.executable, str(_cli), "--item", "nope", "--json",
                    "--subject", NEW, "--policy", str(_pol)],
                   capture_output=True, text=True)
check("report pins the policy hash",
      len(json.loads(r.stdout)["policy_sha256"]), 64)

# 11. REGRESSION, P0 found by Codex on 2026-07-28. The current revision used to be
#     inferred as max(produced_at) across ledgers. Re-gating an OLDER revision
#     LATER therefore made the old text "current": the live defect fell outside
#     the current subject, its non-reproduction on the superseded text counted as
#     the standing result, and the item reported SETTLED with the P0 still open.
#     `produced_at` is a string the harness writes -- metadata about an artifact
#     must never decide what the artifact is.
stale_regate = (
    [ledger(f, NEW, [finding("F1", "D.3", True)] if f == three[0] else [],
            at="2026-07-28T10:00:00Z") for f in three]
    + [ledger(f, OLD, [finding("F1", "D.3", False, repro="e" * 64)],
              at="2026-07-29T09:00:00Z") for f in three])
check("later re-gate of old text cannot settle current text",
      run(stale_regate, current=NEW)["state"], "BLOCKED")

# 12. A ledger whose evidence does not hash to its own digests is unreadable,
#     not merely weak: settling under it would restate an unverifiable claim.
tampered = ledger(three[0], NEW, [dict(finding("F1", "D.3", True),
                                       repro="print(1)", repro_sha256="0" * 64)])
check("preimage mismatch fails closed", run([tampered])["state"], "CORRUPT")

# 12a. Consistent preimages pass through untouched, and a finding that carries
#      none is still read -- older ledgers predate the field, and discarding real
#      recorded evidence over its age is its own kind of loss.
good_code = "print('VIOLATION: x')"
consistent = ledger(three[0], NEW, [dict(
    finding("F1", "D.3", True), repro=good_code,
    repro_sha256=S.sha256_hex(good_code),
    transcript={"stdout": "VIOLATION: x\n", "stderr": "", "exit": 0},
    transcript_sha256=S.sha256_hex("VIOLATION: x\n" + "" + "0"))])
check("consistent preimages are accepted", run([consistent])["state"], "BLOCKED")

# 11a. And the subject is never guessed. A caller that does not say which bytes
#      are on the branch gets a refusal, not a default.
check("missing subject fails closed",
      S.settle("x", POLICY, None, None)["state"], "NO-SUBJECT")

print("\nSETTLE-GATE: " + ("ALL PASS" if not FAILED else f"{FAILED} FAILED"))
sys.exit(1 if FAILED else 0)
