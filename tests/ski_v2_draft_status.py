#!/usr/bin/env python3
"""The `ski@v2` draft is inert, and every case that says so is executed.

    python3 tests/ski_v2_draft_status.py
    WARRANT_GO=./impl-go/warrant-go python3 tests/ski_v2_draft_status.py   # + Go parity

WRT-013 stage S1 writes a DRAFT registration: SPEC §3.2 text, two schemas under
`schemas/drafts/`, and the vector document `examples/drafts/ski-v2-vectors.json`.
A draft that quietly changed what a verifier accepts would be the worst possible
outcome of writing one, so this suite asserts the opposite, by execution:

  - `ski@v2` is rejected in 0.1 and 0.2 bodies, and `"warrant": "0.3"` is
    rejected outright — the case no vector covered for any future version
    before now;
  - the IN-FORCE schemas reject both, while the DRAFT schemas accept them:
    the difference between the two files is the whole content of "not in force";
  - no draft artifact is reachable from any in-force loader (`schema_check`'s
    registry, the conformance pack, the examples the conformance command reads);
  - the reserved tag still has no evaluator and no fallback to another tag's;
  - `ski@v1` has not moved, pinned as the COMPLETE historical tuple rather than
    as a relation between two of them: the §8.2 specimen re-runs to its `expect`
    in exactly 20 ATP, and each M5 fingerprint is exactly
    `('ski@v1', term, expect, 'pass', expect)`. That equality between the two
    MUST SURVIVE admission unchanged — `ski@v2` does not change what a `ski@v1`
    reason fingerprints to; only v2's own tuple carries the exit distinction.
    An in-process mutation appending a member to every tuple is run here and
    must be rejected, because the earlier equality-only form passed it;
  - every `executable_today: true` case in the vector document is actually
    executed here, by id. A case list nobody runs is a wish list.

Go parity is checked when `WARRANT_GO` names a built binary; otherwise that part
is SKIPPED and said to be skipped. Writes only under a TemporaryDirectory.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "impl"))
os.environ.pop("SIGMA_GLYPH", None)                # exercise the BUNDLED engine
import warrant as W                                 # noqa: E402

VECTORS = REPO / "examples/drafts/ski-v2-vectors.json"
DRAFT_BODY_SCHEMA = REPO / "schemas/drafts/warrant-body-0.3.schema.json"
DRAFT_BLOB_SCHEMA = REPO / "schemas/drafts/ski-check-v2.schema.json"
IN_FORCE_BODY_SCHEMA = REPO / "schemas/warrant-body.schema.json"
GO = os.environ.get("WARRANT_GO", "")

_fail, _skipped, _covered = [], [], set()


def check(name, cond, detail="", covers=()):
    print(f"  {'ok ' if cond else 'BAD'}  {name}" + (f"  [{detail}]" if detail and not cond else ""))
    if not cond:
        _fail.append(name)
    _covered.update(covers)


def skip(what, why):
    _skipped.append(what)
    print(f"  SKIP {what} — {why}")


def body(version="0.2", runtime="ski@v2"):
    """A body that is schema-valid apart from the thing under test."""
    reasons = []
    if runtime is not None:
        reasons = [{"kind": "check", "check": "aa" * 32, "runtime": runtime,
                    "verdict": "pass"}]
    return {"warrant": version, "decision": "accept",
            "subject": {"hash": "11" * 32}, "under": ["22" * 32],
            "because": reasons, "evidence": [], "actor": {"id": "a@example"},
            "prior": [], "ts": 0}


print("ski@v2 is rejected everywhere it can appear")
for version, case in (("0.1", "A-01"), ("0.2", "A-02")):
    errs = W.validate_body(body(version))
    check(f"ski@v2 reason in a {version} body is invalid", bool(errs),
          f"validate_body returned {errs}", covers=(case,))

errs = W.validate_body(body("0.3", runtime="cmd@v1"))
check('a body declaring warrant: "0.3" is invalid', bool(errs),
      f"validate_body returned {errs}", covers=("A-03",))
check("...and the error names the version, not the reason",
      any("version" in e for e in errs), f"{errs}", covers=("A-03",))

errs = W.validate_body(body("0.2", runtime="ski@v3"))
check("an unregistered ski@v3 runtime is invalid", bool(errs),
      f"validate_body returned {errs}", covers=("A-05",))

print("\nthe in-force schemas reject what the draft schemas accept")
try:
    import jsonschema
except ImportError:                                  # pragma: no cover
    jsonschema = None
if jsonschema is None:
    skip("schema comparison", "jsonschema is not installed")
else:
    in_force = json.loads(IN_FORCE_BODY_SCHEMA.read_text())
    draft = json.loads(DRAFT_BODY_SCHEMA.read_text())
    blob_schema = json.loads(DRAFT_BLOB_SCHEMA.read_text())
    v2_body_02 = body("0.2")
    v2_body_03 = body("0.3")
    check("in-force schema rejects a ski@v2 reason (0.2 body)",
          not jsonschema.Draft202012Validator(in_force).is_valid(v2_body_02))
    check("in-force schema rejects a 0.3 body",
          not jsonschema.Draft202012Validator(in_force).is_valid(v2_body_03))
    check("draft schema accepts the 0.3 body it describes",
          jsonschema.Draft202012Validator(draft).is_valid(v2_body_03))
    check("draft schema still rejects a 0.2 body (it describes 0.3 only)",
          not jsonschema.Draft202012Validator(draft).is_valid(v2_body_02))
    good_blob = {"ski": 2, "term": "aa" * 32, "atp": 20, "expect": "bb" * 32,
                 "exit": "normal_form"}
    check("draft blob schema accepts the drafted shape",
          jsonschema.Draft202012Validator(blob_schema).is_valid(good_blob))
    for label, mutant in (
            ("ski: 1", dict(good_blob, ski=1)),
            ("missing exit", {k: v for k, v in good_blob.items() if k != "exit"}),
            ("unknown member", dict(good_blob, extra=1)),
            ("exit: dissonance", dict(good_blob, exit="dissonance")),
            ("atp 2**32", dict(good_blob, atp=2 ** 32))):
        check(f"draft blob schema rejects {label}",
              not jsonschema.Draft202012Validator(blob_schema).is_valid(mutant))

print("\nno draft artifact is reachable from an in-force path")
schema_check = (REPO / "tools/schema_check.py").read_text()
check("tools/schema_check.py does not load schemas/drafts/",
      "drafts/" not in schema_check)
pack = (REPO / "tools/build_conformance_pack.py").read_text()
check("the conformance pack builder does not read examples/drafts/",
      "drafts/" not in pack)
warrant_src = (REPO / "impl/warrant.py").read_text()
check("impl/warrant.py names no draft artifact",
      "drafts/" not in warrant_src and "ski@v2" not in W.RUNTIMES.get("0.2", ()))
check("RUNTIMES has no 0.3 row", "0.3" not in W.RUNTIMES,
      f"{sorted(W.RUNTIMES)}")
check("ACCEPTED body versions are unchanged", W.ACCEPTED == ("0.1", "0.2"),
      f"{W.ACCEPTED}")

print("\nthe reserved tag still has no evaluator")
# NOT C-15. C-15 is the one-byte evaluator mutation with a refusal BEFORE import;
# there is no ski@v2 evaluator to mutate, and the absence of a registered one
# demonstrates nothing about digest enforcement (Codex, S1 review R2). That case
# is marked non-executable until S2 ships the evaluator. What IS executed here is
# the reserved-tag rule, which is its own case.
check("load_sigma('ski@v2') is None", W.load_sigma("ski@v2") is None,
      covers=("C-00",))
check("load_bundled_sigma('ski@v2') is None", W.load_bundled_sigma("ski@v2") is None,
      covers=("C-00",))
check("an unregistered tag yields None, with no fallback to another tag's module",
      W.load_sigma("ski@v9") is None, covers=("C-00",))
check("no ski@v2 row in SKI_EVALUATORS", "ski@v2" not in W.SKI_EVALUATORS)
record = json.loads((REPO / "trust/ski-runtime-evaluators.json").read_text())
check("no ski@v2 row in trust/ski-runtime-evaluators.json",
      "ski@v2" not in record["tags"])
check("ski@v1 still loads its pinned module", W.load_sigma("ski@v1") is not None)

print("\nski@v1 has not moved")
with tempfile.TemporaryDirectory() as tmp:
    store = W.Store(Path(tmp) / "store")
    store.init()
    ski_dir = REPO / "examples/ski"
    for f in sorted(ski_dir.glob("*.bin")):
        store.put_blob(f.read_bytes())
    spec_blob = store.put_blob((ski_dir / "check.json").read_bytes())
    verdict, result, spent = W.run_ski_check(store, spec_blob)
    check("§8.2 specimen: pass, H(S), exactly 20 ATP",
          (verdict, spent) == ("pass", 20)
          and result == json.loads((ski_dir / "check.json").read_text())["expect"],
          f"{verdict} {result[:12]} {spent}", covers=("R-21",))

    # The M5 pair: one term, two budgets, one fingerprint — TODAY's behaviour.
    sg = W.load_sigma("ski@v1")
    dis = sg.ser(sg.DISSONANCE, sg.F_ATOM, atom=sg.sha(b"ATP Exhausted"))
    node = sg.node_hash(dis)
    store.put_blob(dis)
    for _ in range(2):
        b = sg.ser(sg.APPLY, sg.F_LEFT | sg.F_RIGHT, left=sg.I_H, right=node)
        node = sg.node_hash(b)
        store.put_blob(b)
    term, expect = node.hex(), sg.node_hash(dis).hex()
    fixture = json.loads(VECTORS.read_text())["m5_fixture"]
    check("the vector document's M5 term is the one built here",
          fixture["term"] == term and fixture["expect"] == expect,
          f"{term[:12]} vs {fixture['term'][:12]}")
    reasons = []
    for atp in (0, 9):
        blob = store.put_blob(W.canon({"ski": 1, "term": term, "atp": atp,
                                       "expect": expect}))
        reasons.append({"kind": "check", "check": blob, "runtime": "ski@v1",
                        "verdict": "pass"})
    # A ski@v2 check blob and a ski@v2 reason sit in the SAME store and the SAME
    # body as the v1 reasons. This is as close to R-20's "a store that also holds
    # ski@v2 records" as is constructible while the tag is rejected — a record
    # carrying that reason cannot be valid, which is asserted here rather than
    # assumed. The genuinely mixed store (valid v2 records beside v1 ones) is
    # R-20b and is NOT executable until admission.
    v2_blob = store.put_blob(W.canon({"ski": 2, "term": term, "atp": 9,
                                      "expect": expect, "exit": "normal_form"}))
    v2_reason = {"kind": "check", "check": v2_blob, "runtime": "ski@v2",
                 "verdict": "pass"}
    m5_body = dict(body("0.2", runtime=None), because=reasons + [v2_reason])
    check("a body mixing ski@v1 and ski@v2 reasons is still invalid",
          bool(W.validate_body(m5_body)), covers=("R-20",))
    check("the ski@v2 reason contributes NO fingerprint (unregistered runtime)",
          W.fingerprint(v2_reason, m5_body, store) is None, covers=("R-20",))

    fps = [W.fingerprint(r, m5_body, store) for r in reasons]
    # The COMPLETE historical tuple, written out. Equality of the two was the
    # earlier assertion and it was too weak: appending a member to both left it
    # green (Codex, S1 review R1). The pinned form fails on any change of shape,
    # order or value — including an added member, since the comparison is on the
    # whole tuple and the length is asserted beside it.
    HISTORIC = ("ski@v1", term, expect, "pass", expect)
    for atp, fp in zip((0, 9), fps):
        check(f"M5 atp={atp}: the ski@v1 fingerprint is exactly the historical "
              f"5-tuple", fp == HISTORIC and len(fp) == 5, f"{fp}",
              covers=("R-20",))
    check("M5 pair: the two ski@v1 fingerprints are equal — and MUST stay equal "
          "after v2 is admitted (only v2 tuples gain the exit distinction)",
          fps[0] == fps[1], f"{fps[0]}\n{fps[1]}", covers=("R-20",))
    check("M5 pair: the second is therefore inadmissible as re-litigation",
          W.fingerprint(reasons[1], m5_body, store) in set(fps[:1]))

    # The control for the control. A preservation test that cannot notice a
    # changed tuple is decoration, so the change is made here, in process, and
    # the assertion must reject it.
    original_fingerprint = W.fingerprint
    try:
        W.fingerprint = lambda r, b, s: (None if original_fingerprint(r, b, s) is None
                                         else original_fingerprint(r, b, s)
                                         + ("unexpected-v1-format-change",))
        drifted = [W.fingerprint(r, m5_body, store) for r in reasons]
        caught = all(fp != HISTORIC and len(fp) != 5 for fp in drifted)
        equal_still = drifted[0] == drifted[1]
        check("mutation control: an added tuple member is REJECTED by the pinned "
              "comparison (and would have passed a bare equality check)",
              caught and equal_still, f"{drifted[0]}")
    finally:
        W.fingerprint = original_fingerprint

print("\nGo agrees that ski@v2 and 0.3 are invalid")
go_bin = Path(GO) if GO else REPO / "impl-go/warrant-go"
if not go_bin.is_file():
    skip("Go parity", f"no binary at {go_bin} (build impl-go, or set WARRANT_GO)")
else:
    def go_validate(doc):
        """The conformance `validate` class over the probe protocol (CONTRACT.md)."""
        req = {"warrant_conformance": "1", "id": "ski-v2-draft",
               "class": "validate", "input": {"body": doc}}
        done = subprocess.run([str(go_bin), "probe"], input=json.dumps(req),
                              capture_output=True, text=True)
        if done.returncode != 0:
            return None, (done.stdout + done.stderr).strip()[:160]
        return json.loads(done.stdout), ""

    # A control first: the probe must call a GOOD body valid, or "rejects
    # everything" would pass this section for the wrong reason.
    good, why = go_validate(body("0.2", runtime="ski@v1"))
    check("Go's validate class answers valid for a ski@v1 0.2 body",
          good is not None and good.get("output", {}).get("valid") is True,
          f"{why or good}")
    for label, doc in (("ski@v2 in a 0.2 body", body("0.2")),
                       ("ski@v2 in a 0.1 body", body("0.1")),
                       ("a 0.3 body", body("0.3", runtime="cmd@v1")),
                       ("ski@v3 runtime", body("0.2", runtime="ski@v3"))):
        answer, why = go_validate(doc)
        output = (answer or {}).get("output", {})
        check(f"Go rejects {label}", output.get("valid") is False,
              f"{why or answer}")

print("\nthe vector document is complete and every executable case ran")
doc = json.loads(VECTORS.read_text())
ids = [c["id"] for c in doc["cases"]]
check("case ids are unique", len(ids) == len(set(ids)))
check("every case declares executable_today",
      all(isinstance(c.get("executable_today"), bool) for c in doc["cases"]))
check("the document says it is not in force", "NOT IN FORCE" in doc["status"])
expected_exec = {c["id"] for c in doc["cases"] if c["executable_today"]}
missing = sorted(expected_exec - _covered)
check("every executable_today case was executed above", not missing,
      f"not executed: {missing}")
extra = sorted(_covered - expected_exec)
check("no case claims coverage it does not have", not extra, f"{extra}")
print(f"        {len(expected_exec)} executable / {len(ids)} total; the rest need a "
      f"ski@v2 implementation and are NOT evidence yet")

print()
if _fail:
    print(f"SKI-V2-DRAFT-STATUS: FAILURES ({len(_fail)}): " + "; ".join(_fail))
    sys.exit(1)
print("SKI-V2-DRAFT-STATUS: ALL PASS"
      + (f" — SKIPPED: {', '.join(_skipped)}" if _skipped else "")
      + " — the draft changes nothing a verifier accepts")
sys.exit(0)
