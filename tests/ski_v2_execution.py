#!/usr/bin/env python3
"""The DRAFT `ski@v2` execution path: verdicts, refusals, and what it is not.

    python3 tests/ski_v2_execution.py

WRT-013 stage S2 builds the machinery a future admission would register:
`validate_ski_v2_blob`, `load_draft_sigma`, `run_ski_v2_check`. **Nothing here
is admitted.** No record can carry a `ski@v2` reason, so no verification, filing,
fingerprint or settlement path reaches any of it; `tests/ski_v2_draft_status.py`
is what proves that, and this suite proves the machinery itself behaves as §3.2's
draft says — before anyone can rely on it.

Expected values are written out, not recomputed from the code under test:

  term   3dbd87017589d8e6636e076795e2f226b15752fe989088de1614fa3ee5ddf634
         = APPLY(I, APPLY(I, DISSONANCE("ATP Exhausted")))
  expect 8bb0006f4c0a51a645877c10db80b7360b0d34f6f826e5737d0847f8b1493176

At atp 0 that term exits `atp_exhausted`; at atp 9 it exits `normal_form`; both
answer the SAME result hash. The verdict matrix over those two runs is the whole
argument for the tag, so it is checked in all four combinations of claimed exit.

Every local refusal is asserted to be a REFUSAL — a RuntimeError with a bounded
reason — and never a `pass`/`fail` verdict. Writes only under a
TemporaryDirectory; the repository tree is not modified.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "impl"))
os.environ.pop("SIGMA_GLYPH", None)
import warrant as W                                  # noqa: E402

TERM = "3dbd87017589d8e6636e076795e2f226b15752fe989088de1614fa3ee5ddf634"
EXPECT = "8bb0006f4c0a51a645877c10db80b7360b0d34f6f826e5737d0847f8b1493176"
V06_SHA = "f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4"

_fail, _covered = [], set()


def check(name, cond, detail="", covers=()):
    print(f"  {'ok ' if cond else 'BAD'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        _fail.append(name)
    _covered.update(covers)


def refuses(fn, expected_fragment, name, covers=()):
    """`fn` must raise RuntimeError whose reason contains `expected_fragment`.

    A refusal is not a verdict: returning ANY result here is a failure, which is
    why the success path is asserted explicitly rather than only the message.
    """
    try:
        got = fn()
    except RuntimeError as ex:
        check(name, expected_fragment in str(ex), f"reason was {str(ex)!r}", covers)
        return
    check(name, False, f"returned {got!r} instead of refusing", covers)


def build_store(tmp):
    """The M5 term's nodes, in a Warrant blob store (which IS the Σ-GLYPH CAS)."""
    store = W.Store(Path(tmp) / "store")
    store.init()
    sg = W.load_draft_sigma("ski@v2")
    dis = sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.sha(b"ATP Exhausted"))
    store.put_blob(dis)
    node = sg.node_hash(dis)
    for _ in range(2):
        b = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=sg.I_H, right=node)
        node = sg.node_hash(b)
        store.put_blob(b)
    assert node.hex() == TERM, f"fixture drift: {node.hex()}"
    assert sg.node_hash(dis).hex() == EXPECT
    return store, sg


def put_v2(store, **over):
    doc = {"ski": 2, "term": TERM, "atp": 9, "expect": EXPECT, "exit": "normal_form"}
    doc.update(over)
    return store.put_blob(W.canon(doc))


print("the evaluator is pinned, and the pin is enforced before import")
path = W.draft_sigma_path("ski@v2")
check("DRAFT_SKI_EVALUATORS holds exactly ski@v2",
      list(W.DRAFT_SKI_EVALUATORS) == ["ski@v2"], f"{list(W.DRAFT_SKI_EVALUATORS)}")
check("the vendored module hashes to its pin",
      path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == V06_SHA)
check("the pin is the published sigma-glyph 0.7.0 module digest",
      W.DRAFT_SKI_EVALUATORS["ski@v2"][1] == V06_SHA)
check("it is NOT in the in-force per-tag table", "ski@v2" not in W.SKI_EVALUATORS)
check("and NOT in pyproject's py-modules (reserved candidates do not ship)",
      "sigma_glyph_v06" not in (REPO / "pyproject.toml").read_text())
check("load_draft_sigma('ski@v2') loads the pinned module",
      getattr(W.load_draft_sigma("ski@v2"), "eval_receipt", None) is not None)
check("an unregistered draft tag yields None (no fallback)",
      W.load_draft_sigma("ski@v9") is None)
check("the admitted loader does NOT serve the reserved tag",
      W.load_sigma("ski@v2") is None)

# C-15, for real this time: a wrong pin must refuse BEFORE a line runs.
with tempfile.TemporaryDirectory(prefix="ski-v2-drift-") as td:
    marker = Path(td) / "executed.marker"
    evil = Path(td) / "sigma_glyph_evil.py"
    evil.write_text(f"open({str(marker)!r}, 'w').write('ran')\n"
                    f"raise RuntimeError('should never import')\n")
    saved, orig_path = dict(W.DRAFT_SKI_EVALUATORS), W.draft_sigma_path
    try:
        W.DRAFT_SKI_EVALUATORS["ski@v2"] = (evil.name, V06_SHA)   # real pin, other bytes
        W.draft_sigma_path = lambda tag=W.DRAFT_SKI_TAG: evil if tag == "ski@v2" else orig_path(tag)
        check("a module whose bytes do not match the pin is refused",
              W.load_draft_sigma("ski@v2") is None, covers=("C-15",))
        check("...and was NOT executed (no side-effect marker)", not marker.exists(),
              covers=("C-15",))
        with tempfile.TemporaryDirectory() as tmp2:
            s = W.Store(Path(tmp2) / "s")
            s.init()
            blob = s.put_blob(W.canon({"ski": 2, "term": TERM, "atp": 9,
                                       "expect": EXPECT, "exit": "normal_form"}))
            refuses(lambda: W.run_ski_v2_check(s, blob), "runtime unavailable",
                    "a check under a drifted evaluator is UNVERIFIED, not failed",
                    covers=("C-15",))
        check("still no side-effect marker after the check attempt", not marker.exists(),
              covers=("C-15",))
    finally:
        W.DRAFT_SKI_EVALUATORS.clear()
        W.DRAFT_SKI_EVALUATORS.update(saved)
        W.draft_sigma_path = orig_path

with tempfile.TemporaryDirectory(prefix="ski-v2-exec-") as tmp:
    store, sg = build_store(tmp)

    print("\nthe verdict is the exit AND the result, over one term at two budgets")
    matrix = ((0, "atp_exhausted", "pass", "atp_exhausted", 0),
              (0, "normal_form", "fail", "atp_exhausted", 0),
              (9, "normal_form", "pass", "normal_form", 9),
              (9, "atp_exhausted", "fail", "normal_form", 9))
    seen = []
    for atp, claimed, want_verdict, want_exit, want_spent in matrix:
        r = W.run_ski_v2_check(store, put_v2(store, atp=atp, exit=claimed))
        seen.append(r)
        check(f"atp={atp} claiming {claimed} -> {want_verdict}",
              tuple(r) == (want_verdict, EXPECT, want_spent, want_exit), f"{tuple(r)}",
              covers=("C-12",) if (atp, claimed) == (0, "normal_form") else ())
    # The point of the tag, stated as a measurement over what the runs RETURNED:
    # every row answered one result hash, the exits split them, and so do the
    # verdicts. (This was a tautology in the first draft of this file — it
    # compared a constant with itself.)
    check("every row returned the same result hash",
          {r.result_hash for r in seen} == {EXPECT}, f"{[r.result_hash[:8] for r in seen]}")
    check("...while the exits, and therefore the verdicts, differ",
          {r.exit for r in seen} == {"atp_exhausted", "normal_form"}
          and {r.verdict for r in seen} == {"pass", "fail"},
          f"{[(r.exit, r.verdict) for r in seen]}")

    print("\nthe same claim under ski@v1 still passes: one term, two tags, two verdicts")
    v1_blob = store.put_blob(W.canon({"ski": 1, "term": TERM, "atp": 0,
                                      "expect": EXPECT}))
    v1 = W.run_ski_check(store, v1_blob)
    check("ski@v1 says pass where ski@v2 says fail (claimed exit normal_form)",
          v1 == ("pass", EXPECT, 0), f"{v1}", covers=("C-12",))

    print("\na blob of the wrong version is refused under either tag")
    refuses(lambda: W.run_ski_v2_check(store, v1_blob),
            "ski@v2 check blob must be exactly",
            "a ski:1 blob under ski@v2 is invalid, not a fail", covers=("B-06",))
    refuses(lambda: W.run_ski_check(store, put_v2(store)),
            "ski check blob must be exactly",
            "a ski:2 blob under ski@v1 is invalid, not a fail", covers=("B-06",))

    print("\nblob shape: every member is required and the set is closed")
    base = {"ski": 2, "term": TERM, "atp": 9, "expect": EXPECT, "exit": "normal_form"}
    for label, mutant, fragment in (
            ("missing exit", {k: v for k, v in base.items() if k != "exit"},
             "must be exactly"),
            ("unknown member", dict(base, extra=1), "must be exactly"),
            ("exit: dissonance", dict(base, exit="dissonance"), "exit must be one of"),
            ("exit: null", dict(base, exit=None), "exit must be one of"),
            ("ski: 3", dict(base, ski=3), "ski field must be 2"),
            ("atp 2**32", dict(base, atp=2 ** 32), "atp must be a uint32"),
            ("atp -1", dict(base, atp=-1), "atp must be a uint32"),
            ("atp true", dict(base, atp=True), "atp must be a uint32"),
            ("term not hex64", dict(base, term="zz" * 32), "hex64")):
        blob = store.put_blob(W.canon(mutant))
        refuses(lambda b=blob: W.run_ski_v2_check(store, b), fragment,
                f"{label} is refused", covers=("B-07", "B-09"))

    # atp 1.0 cannot go through canon() (floats are not I-JSON), so the validator
    # is exercised directly — the refusal still has to be the same class.
    check("atp 1.0 is refused by the validator",
          "atp must be a uint32" in (W.validate_ski_v2_blob(dict(base, atp=1.0)) or ""),
          covers=("B-09",))

    print("\nbytes that are not at their address are refused, at both boundaries")
    bad_name = "cc" * 32
    (store.blobs / bad_name).write_bytes(W.canon(base))
    refuses(lambda: W.run_ski_v2_check(store, bad_name), W.REASON_CAS_MISMATCH,
            "a check blob under a foreign name is refused", covers=("B-10",))
    # A term thunk under a foreign key: the adapter and the engine each refuse.
    foreign = "dd" * 32
    (store.blobs / foreign).write_bytes(b"\x00\x01" + b"\x00" * 32)
    refuses(lambda: W.run_ski_v2_check(store, put_v2(store, term=foreign)),
            W.REASON_CAS_MISMATCH,
            "a term thunk under a foreign key is refused", covers=("C-13",))
    engine_refused = False
    try:
        sg.eval_receipt(bytes.fromhex(foreign), 10,
                        type("Liar", (), {"get": staticmethod(
                            lambda h: b"\x00\x01" + b"\x00" * 32)})())
    except Exception as ex:                       # ResourceFault from Book I 0.6.0
        engine_refused = "CAS key mismatch" in str(ex)
    check("the engine refuses the same bytes independently of the adapter",
          engine_refused, covers=("C-13",))

    print("\nunresolved references are an exit, not a fault")
    absent = "ee" * 32
    r = W.run_ski_v2_check(store, put_v2(store, term=absent,
                                         exit="unresolved_reference"))
    check("a demanded object that is absent exits unresolved_reference",
          r.exit == "unresolved_reference", f"{tuple(r)}", covers=("C-11",))
    check("...and claiming normal_form for it is a fail, not a pass",
          W.run_ski_v2_check(store, put_v2(store, term=absent, exit="normal_form",
                                           expect=r.result_hash)).verdict == "fail",
          covers=("C-11",))
    check("...while claiming unresolved_reference with its result hash passes",
          W.run_ski_v2_check(store, put_v2(store, term=absent,
                                           exit="unresolved_reference",
                                           expect=r.result_hash)).verdict == "pass",
          covers=("C-11",))

    print("\nthe budget is Warrant's, and over it is a refusal")
    over = W.SKI_REEXEC_MAX_ATP + 1
    refuses(lambda: W.run_ski_v2_check(store, put_v2(store, atp=over)),
            "atp exceeds re-execution budget",
            "atp above the local budget is refused before the evaluator runs",
            covers=("C-14",))
    check("Book I's own VERIFIER_LIMITS is smaller than Warrant's budget — and is "
          "not the one used", sg.VERIFIER_LIMITS["max_atp"] < W.SKI_REEXEC_MAX_ATP,
          f"{sg.VERIFIER_LIMITS['max_atp']} vs {W.SKI_REEXEC_MAX_ATP}")
    # An admission refusal from the engine is a refusal too, never a verdict.
    saved_budget = W.SKI_REEXEC_MAX_ATP
    try:
        W.SKI_REEXEC_MAX_ATP = 10 ** 9            # let the blob through Warrant's gate
        blob = put_v2(store, atp=10 ** 8)
        sg_low = W.load_draft_sigma("ski@v2")
        refuses(lambda: W.run_ski_v2_check(
            store, blob,
            sg=type("Capped", (), {
                "eval_receipt": staticmethod(
                    lambda h, atp, env, limits=None: sg_low.eval_receipt(
                        h, atp, env, dict(sg_low.DEFAULT_LIMITS, max_atp=10))),
                "AdmissionRefused": sg_low.AdmissionRefused,
                "ResourceFault": sg_low.ResourceFault,
                "DEFAULT_LIMITS": sg_low.DEFAULT_LIMITS})()),
            "admission refused",
            "an engine admission refusal is UNVERIFIED, not a verdict")
    finally:
        W.SKI_REEXEC_MAX_ATP = saved_budget

    print("\nmissing and malformed blobs")
    refuses(lambda: W.run_ski_v2_check(store, "ab" * 32), "check blob missing",
            "an absent check blob is refused")
    raw = b'{"ski":2,"term":"' + TERM.encode() + b'"}   '
    name = hashlib.sha256(raw).hexdigest()
    (store.blobs / name).write_bytes(raw)
    refuses(lambda: W.run_ski_v2_check(store, name), "not JCS-canonical",
            "a non-canonical blob is refused", covers=("B-08",))

    print("\nski@v1 is untouched by all of the above")
    ski_dir = REPO / "examples/ski"
    for f in sorted(ski_dir.glob("*.bin")):
        store.put_blob(f.read_bytes())
    spec_blob = store.put_blob((ski_dir / "check.json").read_bytes())
    spec = json.loads((ski_dir / "check.json").read_text())
    check("§8.2 specimen: pass, its expect, exactly 20 ATP",
          W.run_ski_check(store, spec_blob) == ("pass", spec["expect"], 20))
    check("validate_ski_blob still refuses a five-member document",
          W.validate_ski_blob(base) is not None)

print("\nthe vector document and this suite agree on who executes what")
doc = json.loads((REPO / "examples/drafts/ski-v2-vectors.json").read_text())
mine = {c["id"] for c in doc["cases"]
        if c.get("executed_by") == "tests/ski_v2_execution.py"}
declared = {c["id"] for c in doc["cases"] if c["executable_today"]}
check("every case this suite executes is marked executable_today",
      not sorted(_covered - declared), f"{sorted(_covered - declared)}")
check("every case assigned to this suite was executed above",
      not sorted(mine - _covered), f"not executed: {sorted(mine - _covered)}")
check("and this suite claims no case assigned elsewhere",
      not sorted(_covered - mine), f"{sorted(_covered - mine)}")

print()
if _fail:
    print(f"SKI-V2-EXECUTION: FAILURES ({len(_fail)}): " + "; ".join(_fail))
    sys.exit(1)
print(f"SKI-V2-EXECUTION: ALL PASS — the draft machinery behaves as §3.2 says, "
      f"and no record can reach it")
sys.exit(0)
