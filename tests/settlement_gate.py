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


def ledger(family, subject, findings, at="2026-07-28T10:00:00Z", item="x",
           document="DOC.md"):
    return {"item": item, "family": family, "model": family, "host": "h",
            "produced_at": at, "subject_sha256": subject, "subject_label": "L",
            "document": document, "review": "r.md", "findings": findings}


def finding(fid, clause, reproduced, severity="P0", repro=None, transcript=None,
            closes="", outcome=None):
    return {"id": fid, "severity": severity, "clause": clause, "title": fid,
            "repro_sha256": repro or ("c" * 64), "exit": 0, "closes": closes,
            "outcome": outcome or ("violation" if reproduced else "refuted"),
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
PROBE = "qwen3-coder@local"

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

# 13. REGRESSION. The repro rules tell reviewers to write `clause=unstated` for a
#     property the document never states, so without special handling every
#     distinct unwritten-property defect shares one claim key by design. Then
#     refuting any one of them closes all the rest. Demonstrated 2026-07-28,
#     starting from a local reviewer's observation that clause keys merge:
#     one `unstated` defect reproduced on superseded text and never retested,
#     another refuted on current text, and the item read SETTLED.
unstated = ([ledger("kimi@moonshot", OLD, [finding("B", "unstated", True,
                                                   repro="1" * 64)],
                    at="2026-07-01T00:00:00Z")]
            + [ledger(f, NEW, [finding("A", "unstated", False, repro="2" * 64)])
               for f in three])
check("unstated findings are not one claim", run(unstated)["claims_total"], 4)
check("refuting one unstated defect cannot clear another",
      run(unstated)["state"], "UNRESOLVED")

# 13a. A real clause id still normalises: same clause, different spelling, one
#      claim. That is the behaviour worth keeping, and the fix must not cost it.
check("real clause ids still normalise",
      run([ledger(three[0], NEW, [finding("F1", "D.3", True),
                                  finding("F2", "d.3 ", True, repro="e" * 64)])
           ])["claims_total"], 1)

# 14. REGRESSION, and the mirror of 13. Keying unclassified findings per finding
#     kept distinct `unstated` defects apart -- and made every one immortal: a
#     re-test is new code, so new bytes, so it can never land on the same key.
#     Three families refuting a thing could not close it. Safety without liveness
#     is still a defect, and this is the shape gemini found in WRT-002.
UNSTATED_KEY = "unidentified:kimi@moonshot:F1:111111111111"
_old = [ledger("kimi@moonshot", OLD, [finding("F1", "unstated", True, repro="1" * 64)],
               at="2026-07-01T00:00:00Z")]

check("re-test without citation cannot close (still safe)",
      run(_old + [ledger(f, NEW, [finding("F1", "unstated", False, repro="2" * 64)])
                  for f in three])["state"], "UNRESOLVED")

check("explicit citation closes it (liveness)",
      run(_old + [ledger(f, NEW, [finding("R", "unstated", False, repro="2" * 64,
                                          closes=UNSTATED_KEY)])
                  for f in three])["state"], "SETTLED")

# 14a. Citing a claim does not close it -- refuting it does. A closure that still
#      reproduces is the defect standing, whatever the reviewer meant to say.
check("citation that still reproduces blocks",
      run(_old + [ledger(f, NEW, [finding("R", "unstated", True, repro="2" * 64,
                                          closes=UNSTATED_KEY)])
                  for f in three])["state"], "BLOCKED")

# 14b. A citation naming no known claim is a no-op that LOOKS like work done --
#      the most dangerous shape a mistake takes here, so it is named and blocks.
_ghost = run([ledger(f, NEW, [finding("R", "unstated", False, repro="9" * 64,
                                      closes="unidentified:GHOST:0")]) for f in three])
check("dangling citation blocks", _ghost["state"], "BLOCKED")
check("dangling citation is named", _ghost["dangling_closes"], ["unidentified:GHOST:0"])

# 15. REGRESSIONS from the Codex gate of 2026-07-28. Seven reproduced findings,
#     all against the shape of this file's own reasoning rather than its syntax.

# F1: a DIFFERENT probe on the same clause is not a re-test. "Probe B did not
#     fire" says nothing about probe A, which is the one that fired.
_a_old = [ledger("codex@openai", OLD, [finding("A", "D.3", True, repro="1" * 64)],
                 at="2026-07-01T00:00:00Z")]
check("different probe cannot close a stale defect",
      run(_a_old + [ledger(f, NEW, [finding("B", "D.3", False, repro="2" * 64)])
                    for f in three])["state"], "UNRESOLVED")
check("the same probe re-run does close it",
      run(_a_old + [ledger(f, NEW, [finding("A", "D.3", False, repro="1" * 64)])
                    for f in three])["state"], "SETTLED")

# F2: a repeated outcome is not novel, but it is still a record. Dropping it
#     discarded its severity, so a P0 sharing a fingerprint with an earlier
#     unlabelled entry vanished.
_dup = run([ledger(three[0], NEW, [finding("A", "D.3", True, severity="P?",
                                           repro="7" * 64),
                                   finding("A", "D.3", True, severity="P0",
                                           repro="7" * 64)])])
check("fingerprint dedupe does not erase severity",
      _dup["blocking"][0]["severity"] if _dup["blocking"] else None, "P0")

# F3: subject and repro are roles, not an unordered set. Sorting them together
#     let (subject=X, repro=Y) collide with (subject=Y, repro=X).
X, Y = "e" * 64, "f" * 64
check("subject and repro do not swap in the fingerprint",
      S.outcome_fingerprint(X, {"repro_sha256": Y, "reproduced": True,
                                "transcript_sha256": "d" * 64})
      != S.outcome_fingerprint(Y, {"repro_sha256": X, "reproduced": True,
                                   "transcript_sha256": "d" * 64}), True)

# F4: `D.3` identifies nothing without the document that numbers it.
check("same clause number in two documents is two claims",
      run([ledger("codex@openai", OLD, [finding("A", "D.3", True, repro="1" * 64)],
                  document="DocA.md", at="2026-07-01T00:00:00Z")]
          + [ledger(f, NEW, [finding("B", "D.3", False, repro="1" * 64)],
                    document="DocB.md") for f in three])["state"], "UNRESOLVED")

# F5: two families numbering a finding F1 and sharing a boilerplate driver are
#     not one defect.
check("unstated keys separate reviewers",
      S.claim_key({"clause": "unstated", "id": "F1", "repro_sha256": "9" * 64},
                  "DOC.md", "codex@openai")
      != S.claim_key({"clause": "unstated", "id": "F1", "repro_sha256": "9" * 64},
                     "DOC.md", "kimi@moonshot"), True)

# F6: three spellings of one reviewer are not three reviewers.
_alias = run([ledger(a, NEW, [finding("X", "D.9", False, repro="3" * 64)])
              for a in ["codex@openai", "codex@oai", "Codex@OpenAI"]])
check("aliases do not satisfy diversity", _alias["state"], "OPEN")
check("unrecognised families are named", _alias["unrecognised_families"],
      ["codex@oai"])

# F7: a rule set that forbids nothing is the absence of a policy, not a lenient
#     one, and must not be reachable by editing a file that still parses.
check("policy with no blocking severities is rejected",
      bool(S.policy_problems({**POLICY, "blocking_severities": []})), True)
check("policy that does not block P0 is rejected",
      bool(S.policy_problems({**POLICY, "blocking_severities": ["P1", "P2"]})), True)
check("policy with no gating roster is rejected",
      bool(S.policy_problems({**POLICY, "gating_families": []})), True)
check("a family cannot be both gating and probe",
      bool(S.policy_problems({**POLICY, "probe_families": ["codex@openai"]})), True)

# 17. Probes are read, and do not manufacture a quorum. Measured 2026-07-29:
#     across four runs the local models yielded one useful observation and one
#     forged violation, while every finding that survived verification came from
#     one paid family. Counting probes toward diversity would produce the
#     appearance of an independent gate out of noise.
_probes_only = run([ledger(PROBE, NEW, [finding("F1", "D.4", False, repro="8" * 64)]),
                    ledger("deepseek-coder@local", NEW, []),
                    ledger("gemma3@local", NEW, [])])
# UNGATED rather than OPEN since 2026-07-29: probes still fail to make a quorum,
# which is this case's point, and the state now also says WHY -- no gating family
# reviewed it, as opposed to not enough of them having done so yet.
check("three probes are not three families", _probes_only["state"], "UNGATED")
check("probes are named, not ignored", _probes_only["probes_on_current"],
      ["deepseek-coder@local", "gemma3@local", PROBE])
check("a probe's reproduced finding still blocks",
      run([ledger(PROBE, NEW, [finding("F1", "D.4", True, repro="8" * 64)])
           ])["state"], "BLOCKED")

# 16. REGRESSION. A crash is not a refutation. On 2026-07-29 seven stored
#     counter-vectors were re-run after the policy schema gained a required key;
#     every one died on KeyError before touching the subject. Read as two
#     outcomes -- reproduced or not -- that is seven live claims closing on the
#     strength of an exception, and the fixes would have been declared verified
#     by a test that never ran.
_crashed = ([ledger("codex@openai", OLD, [finding("A", "D.3", True, repro="1" * 64)],
                    at="2026-07-01T00:00:00Z")]
            + [ledger(f, NEW, [finding("A", "D.3", False, repro="1" * 64,
                                       outcome="unrunnable")]) for f in three])
check("a crashed re-test closes nothing", run(_crashed)["state"], "UNRESOLVED")

_ran = ([ledger("codex@openai", OLD, [finding("A", "D.3", True, repro="1" * 64)],
                at="2026-07-01T00:00:00Z")]
        + [ledger(f, NEW, [finding("A", "D.3", False, repro="1" * 64,
                                   outcome="refuted")]) for f in three])
check("a re-test that ran and held does close it", run(_ran)["state"], "SETTLED")

# 18. REGRESSIONS from the paid Kimi gate, 2026-07-29. Seven findings, every one
#     aimed at the reasoning. Six were real; the seventh exposed a defect in the
#     harness rather than in this file.

# F1: one retested attack closed a claim carrying two, and the never-retested one
#     vanished from the report instead of being carried as unresolved.
_two = [ledger("codex@openai", OLD, [finding("A", "D.3", True, repro="1" * 64),
                                     finding("B", "D.3", True, repro="2" * 64)],
               at="2026-07-01T00:00:00Z")]
check("retesting one of two attacks closes nothing",
      run(_two + [ledger(f, NEW, [finding("A", "D.3", False, repro="1" * 64,
                                          outcome="refuted")]) for f in three])["state"],
      "UNRESOLVED")
check("retesting both does close it",
      run(_two + [ledger(f, NEW, [finding("A", "D.3", False, repro="1" * 64,
                                          outcome="refuted"),
                                  finding("B", "D.3", False, repro="2" * 64,
                                          outcome="refuted")]) for f in three])["state"],
      "SETTLED")

# F2: a ledger with no `outcome` says only reproduced-or-not. Reading the negative
#     case as a refutation let an old crash close a live claim.
_noout = [{k: v for k, v in finding("A", "D.3", False, repro="1" * 64).items()
           if k != "outcome"}]
check("a missing outcome closes nothing",
      run([ledger("codex@openai", OLD, [finding("A", "D.3", True, repro="1" * 64)],
                  at="2026-07-01T00:00:00Z")]
          + [ledger(f, NEW, _noout) for f in three])["state"], "UNRESOLVED")

# F3: `unstated.` is one character off the mandated spelling and sailed past the
#     placeholder set as a real clause identifier.
check("punctuated placeholders are still placeholders",
      S.claim_key({"clause": "unstated.", "id": "F", "repro_sha256": "a" * 64},
                  "D.md", "codex@openai").startswith("unidentified:"), True)

# F5: validation lived only on the CLI path, so every caller passing a dict --
#     including every test here -- bypassed it.
check("settle() validates its own policy",
      S.settle("x", {**POLICY, "gating_families": []}, None, NEW)["state"], "BAD-POLICY")

# F6: a blank string in the roster is matched by a ledger with a blank family.
check("a blank gating family is rejected",
      bool(S.policy_problems({**POLICY, "gating_families": ["codex@openai", ""]})), True)

# F7: below the blocking bar is not the same as gone. The docstring promises
#     nothing is quietly dropped; a stale unretested P2 was disappearing.
_p2 = run([ledger("codex@openai", OLD, [finding("A", "D.3", True, severity="P2",
                                                repro="1" * 64)],
                  at="2026-07-01T00:00:00Z")]
          + [ledger(f, NEW, []) for f in three])
check("a stale sub-threshold claim is still reported",
      bool(_p2["noted_below_bar"]), True)
check("and it does not block", _p2["state"], "SETTLED")

# 19. UNGATED is not OPEN. From 2026-07-29 no gating family is affordable, so
#     min_families can never be met and every item would sit OPEN forever. A rule
#     that cannot be satisfied is not strict, it is routed around -- and the first
#     to route around it would be the maintainer. UNGATED says the true thing:
#     nothing is wrong, and nothing was independently checked.
check("probes alone report UNGATED, not OPEN",
      run([ledger("qwen3-coder@local", NEW, []),
           ledger("deepseek-coder@local", NEW, [])])["state"], "UNGATED")
check("one gating family is OPEN, not UNGATED",
      run([ledger("codex@openai", NEW, [])])["state"], "OPEN")
check("a probe's reproduced finding still blocks an ungated item",
      run([ledger("qwen3-coder@local", NEW,
                  [finding("F1", "D.4", True, repro="8" * 64)])])["state"], "BLOCKED")

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
