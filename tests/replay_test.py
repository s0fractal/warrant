#!/usr/bin/env python3
"""WRT-022 S2: crossings and replay receipts (impl/replay.py) as a basis of closure
in impl/loops.py.

    python3 tests/replay_test.py

Every computation is a real WPL compilation (impl/assessment.py). Every sigma-resume
receipt is produced by the vendored kernel in this process and verified by the
isolated worker; every ski@v1 receipt is re-run by warrant's pinned evaluator.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "impl"))
# REPLAY_IMPL lets tests/replay_mutants.py run this file against mutated copies.
if os.environ.get("REPLAY_IMPL"):
    sys.path.insert(0, os.environ["REPLAY_IMPL"])
    os.environ["LOOPS_IMPL"] = os.environ["REPLAY_IMPL"]
import loops_test as LT     # noqa: E402
import loops as L           # noqa: E402
import replay as RP         # noqa: E402
import assessment as A      # noqa: E402
import warrant as W         # noqa: E402

VENDOR = ROOT / "impl" / "sigma_resume_c864d3e"
sys.path.insert(1, str(VENDOR))
import sigma_resume as R    # noqa: E402  (the producer's kernel, in the test process)
import sigma_glyph as G     # noqa: E402

results = {}
PROG = A.program("refund", {"amount": "int"}, "amount <= 50000")
TRUE_H, FALSE_H = G.term_hash(G.KG).hex(), G.term_hash(("app", G.KG, G.IG)).hex()


def check(tid, ok, what, detail=""):
    results[tid] = "PASS" if ok else "FAIL"
    print(("ok    " if ok else "FAIL  ") + f"{tid} {what}" + ("" if ok else f" | {detail}"))


def computation(c, amount):
    """A real compiled refund check in c's store: (check blob, input term hex)."""
    facts = A.fact_set("refund", {"amount": A.observed(amount, "ab" * 32)})
    pl = A.plan(PROG, facts, put=c.S.put_blob)
    return pl["emitted"]["check"], pl["emitted"]["term"]


def crossing(c, replay=None, unknown=(), outcome="TRANSLATED", conflicts=(), trajectory="warrant/ski@v1"):
    d = {"schema": RP.CROSSING, "source": {"trajectory": trajectory, "artifact": None, "revision": None},
         "target_profile": "loops-test", "mapping": "identity",
         "report": {"preserved": ["the replayed answer"], "lost": [], "introduced": [], "approximated": [],
                    "unknown": list(unknown)},
         "outcome": outcome, "conflicts": list(conflicts), "transferred": []}
    if replay is not None:
        d["replay"] = replay
    return c.blob(d)


def ski_receipt(c, chk, **override):
    verdict, rh, _ = W.run_ski_check(c.S, chk)
    claimed = {"verdict": verdict, "result_node_hash": rh}
    claimed.update(override)
    return {"runtime": "ski@v1", "check": chk, "claimed": claimed}


class Delivered:
    def __init__(self, store):
        self.store = store

    def get(self, h):
        p = self.store.blobs / h.hex()
        return p.read_bytes() if p.is_file() else None


def sigma_receipt(c, term, max_actions=None, claim=None):
    """Run the computation with the vendored kernel, as a producer would; return the
    receipt and the environment manifest hash."""
    hashes = sorted(p.name for p in c.S.blobs.iterdir() if len(p.name) == 64)
    env_h = c.blob({"schema": RP.ENVIRONMENT, "hashes": hashes})
    env = R.Environment([bytes.fromhex(h) for h in hashes], Delivered(c.S))
    t = bytes.fromhex(term)
    rt = R.root(t, env)
    doc, cid, sb = R.start(rt[1], t)
    run = R.advance(doc, cid, sb, env, 1_000_000, max_actions=max_actions) if max_actions else \
        R.advance(doc, cid, sb, env, 1_000_000)
    ck = c.S.put_blob(R._canon(run.checkpoint))
    st = c.S.put_blob(run.state_bytes)
    result = G.term_hash(run.term()).hex() if run.outcome == "NORMAL_FORM" else FALSE_H
    rec = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "checkpoint": ck,
           "state": st, "claimed": {"outcome": "NORMAL_FORM", "result_term_hash": claim or result}}
    return rec, env_h, run.outcome


def replay_close(c, comp, cross, acceptance=()):
    d = c.open(admits=[["DISCHARGED", "REPLAYED"]], acceptance=list(acceptance), computation=comp)
    t = L.transition("REPLAYED", [cross], closes=[L.mapping(d, "DISCHARGED", [cross])], scope_subject=LT.SHA_NEW)
    tid = c.record("propose", c.blob(t), LT.CLAUDE, prior=[d])
    return d, tid


def verdict_of(rep, d):
    r = rep["duties"][d]
    return r["disposition"], [x["verdict"] for x in r["candidates"]], [x["why"] for x in r["candidates"]]


# The recipient's profile: it names the crossing targets it accepts (review S2-01).
ACCEPTS = {"schema": L.PROFILE, "uses": {"read": {"requires_declared_triggers": False}},
           "crossing_targets": ["loops-test"]}


def assess(c, profile=ACCEPTS):
    return L.assess(c.S.root, c.trust, LT.T_END, current={LT.SHA_NEW}, profile=profile)


def sigma_case():
    """A valid sigma-resume closure: (case, duty)."""
    c = LT.Case()
    _, term = computation(c, 12000)
    rec, env_h, _ = sigma_receipt(c, term)
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    return c, d


def with_verifier_copy(edit):
    """Run `edit(tmp)` on a private copy of the worker and kernel, point RP.WORKER at
    it, and return a context restorer."""
    tmp = Path(tempfile.mkdtemp(prefix="replay-copy-"))
    shutil.copytree(Path(RP.WORKER).parent / "sigma_resume_c864d3e", tmp / "sigma_resume_c864d3e")
    shutil.copy(RP.WORKER, tmp)
    edit(tmp)
    saved = RP.WORKER
    RP.WORKER = tmp / "replay_sigma_worker.py"
    return saved


def main():
    pin16 = W.SKI_EVALUATORS["ski@v1"][1][:16]

    # X01 a ski@v1 receipt the recipient re-runs: DISCHARGED on REPLAYED, view-local label
    c = LT.Case()
    chk, _ = computation(c, 12000)
    d, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H}, crossing(c, ski_receipt(c, chk)))
    rep = assess(c)
    check("X01", rep["duties"][d]["disposition"] == "DISCHARGED"
          and rep["duties"][d]["assessed_basis"] == [f"REPLAYED:ski@v1:{pin16}"],
          "a re-run ski@v1 receipt discharges on REPLAYED", verdict_of(rep, d))

    # X02 the receipt's claim differs from the recipient's own replay
    c = LT.Case()
    chk, _ = computation(c, 12000)
    d, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H},
                        crossing(c, ski_receipt(c, chk, result_node_hash="cd" * 32)))
    disp, v, why = verdict_of(assess(c), d)
    check("X02", disp == "OPEN" and v == ["UNVERIFIED_BASIS"] and "disagrees" in why[0],
          "a receipt the recipient's replay contradicts closes nothing", why)

    # X03 a receipt of another computation than the duty names (WRT-020's gap 1, at closure)
    c = LT.Case()
    chk, _ = computation(c, 12000)
    other, _ = computation(c, 13000)
    d, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H},
                        crossing(c, ski_receipt(c, other)))
    disp, v, why = verdict_of(assess(c), d)
    check("X03", disp == "OPEN" and "another computation" in why[0], "a replay of something else closes nothing", why)

    # X04 a duty that names no computation cannot be discharged by any replay
    c = LT.Case()
    chk, _ = computation(c, 12000)
    cross = crossing(c, ski_receipt(c, chk))
    d = c.open(admits=[["DISCHARGED", "REPLAYED"]], acceptance=[])
    t = L.transition("REPLAYED", [cross], closes=[L.mapping(d, "DISCHARGED", [cross])])
    c.record("propose", c.blob(t), LT.CLAUDE, prior=[d])
    disp, v, why = verdict_of(assess(c), d)
    check("X04", disp == "OPEN" and "names no computation" in why[0], "no named computation, no replay", why)

    # X05 an honest replay of the wrong answer: the compiled check pins FALSE, so its
    # verdict is `pass`; the duty requires TRUE (WRT-020 gap 2 -- the first draft of
    # S2 bound the verdict and discharged this refusal)
    c = LT.Case()
    chk, _ = computation(c, 65088)                 # over the limit: the policy answers FALSE
    d, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H}, crossing(c, ski_receipt(c, chk)))
    disp, v, why = verdict_of(assess(c), d)
    v05, _, _ = W.run_ski_check(c.S, chk)
    check("X05", v05 == "pass" and disp == "OPEN" and "not the one the duty requires" in why[0],
          "a faithful replay of the wrong answer does not discharge", why)

    # X06 a sigma-resume receipt, verified by the isolated pinned worker
    c = LT.Case()
    _, term = computation(c, 12000)
    rec, env_h, outcome = sigma_receipt(c, term)
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    rep = assess(c)
    check("X06", outcome == "NORMAL_FORM" and rep["duties"][d]["disposition"] == "DISCHARGED"
          and rep["duties"][d]["assessed_basis"] == [f"REPLAYED:sigma-resume:{RP.SIGMA_RESUME_PIN[:16]}"],
          "a re-verified sigma-resume normal form discharges on REPLAYED", verdict_of(rep, d))

    # X07 a verified PREFIX is reachable, and is not an answer
    c = LT.Case()
    _, term = computation(c, 12000)
    rec, env_h, outcome = sigma_receipt(c, term, max_actions=10, claim=TRUE_H)
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    disp, v, why = verdict_of(assess(c), d)
    check("X07", outcome == "INCOMPLETE" and disp == "OPEN" and "PREFIX is not an answer" in why[0],
          "an interrupted run is never an answer", why)

    # X08 the receipt claims a result the recipient's verification does not reach
    c = LT.Case()
    _, term = computation(c, 12000)
    rec, env_h, _ = sigma_receipt(c, term, claim=FALSE_H)
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": FALSE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    disp, v, why = verdict_of(assess(c), d)
    check("X08", disp == "OPEN" and "disagrees" in why[0], "a false claimed result closes nothing", why)

    # X09 a faithful sigma replay of an answer the duty does not require
    c = LT.Case()
    _, term = computation(c, 65088)
    rec, env_h, _ = sigma_receipt(c, term)
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    disp, v, why = verdict_of(assess(c), d)
    check("X09", disp == "OPEN" and "not the one the duty requires" in why[0], "the wrong answer, faithfully", why)

    # X10 the state bytes are another state's: not replayed
    c = LT.Case()
    _, term = computation(c, 12000)
    rec, env_h, _ = sigma_receipt(c, term)
    rec2, _, _ = sigma_receipt(c, term, max_actions=10, claim=TRUE_H)
    rec = dict(rec, state=rec2["state"])
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    disp, v, why = verdict_of(assess(c), d)
    check("X10", disp == "OPEN" and v == ["UNVERIFIED_BASIS"] and "not replayed" in why[0],
          "mismatched checkpoint and state are refused", why)

    # X11 the vendored verifier's bytes moved: refused before import
    tmp = Path(tempfile.mkdtemp(prefix="replay-pin-"))
    shutil.copytree(Path(RP.WORKER).parent / "sigma_resume_c864d3e", tmp / "sigma_resume_c864d3e")
    shutil.copy(RP.WORKER, tmp)
    with (tmp / "sigma_resume_c864d3e" / "sigma_resume.py").open("a") as f:
        f.write("\n# moved\n")
    p = subprocess.run([sys.executable, "-I", str(tmp / "replay_sigma_worker.py")], capture_output=True, text=True,
                       input=json.dumps({"store": "/nonexistent", "receipt": {}}), check=False)
    try:
        got11 = json.loads(p.stdout)
    except ValueError:        # the worker ran on: it did not refuse
        got11 = {"worker exited": p.returncode, "stderr": p.stderr[-200:]}
    check("X11", got11 == {"refused": "verifier not pinned: sigma_resume.py"},
          "a moved verifier is never executed", got11)

    # X12 a BORROWED crossing gets no credit even with a valid replay
    c = LT.Case()
    chk, _ = computation(c, 12000)
    d, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H},
                        crossing(c, ski_receipt(c, chk), unknown=["whether the fact issuer is admitted there"]))
    disp, v, why = verdict_of(assess(c), d)
    check("X12", disp == "OPEN" and "BORROWED" in why[0], "a borrowed name carries no credit", why)

    # X13 UNTRANSLATABLE is a valid outcome with its conflicts named; without them it is refused
    c = LT.Case()
    good = crossing(c, outcome="UNTRANSLATABLE", conflicts=["the source answers per request; the target per day"])
    bad = crossing(c, outcome="UNTRANSLATABLE")
    t = L.transition("ATTESTED", [good, bad])
    n = c.open()
    c.record("propose", c.blob(t), LT.CLAUDE, prior=[n])
    rep = assess(c)
    check("X13", rep["crossings"].get(good) == "UNTRANSLATABLE" and rep["crossings"].get(bad, "").startswith("REFUSED"),
          "untranslatable is first-class; an unnamed conflict is not", rep["crossings"])

    # X14 malformed receipts and crossings refuse their closure only; the view survives
    c = LT.Case()
    chk, _ = computation(c, 12000)
    ok_d, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H}, crossing(c, ski_receipt(c, chk)))
    bad_d = []
    for rp in ({"runtime": [], "check": chk, "claimed": {}}, {"runtime": "ski@v1", "check": chk, "claimed": {"verdict": {}, "result_node_hash": "ab" * 32}},
               {"runtime": "sigma-resume", "input_term_hash": "ab" * 32, "environment": "ab" * 32,
                "checkpoint": "ab" * 32, "state": "ab" * 32, "claimed": {"outcome": ["NORMAL_FORM"], "result_term_hash": TRUE_H}}):
        bd, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H}, crossing(c, rp))
        bad_d.append(bd)
    try:
        rep = assess(c)
        ok14 = rep["duties"][ok_d]["disposition"] == "DISCHARGED" and all(
            rep["duties"][b]["disposition"] == "OPEN" and "crossing:" in rep["duties"][b]["candidates"][0]["why"]
            for b in bad_d)
        det14 = [verdict_of(rep, b) for b in bad_d]
    except (TypeError, KeyError) as e:
        ok14, det14 = False, f"assessment aborted: {e}"
    check("X14", ok14, "malformed receipts are refused per closure", det14)

    # X15 a sigma environment manifest must be sorted, unique hex
    c = LT.Case()
    _, term = computation(c, 12000)
    rec, env_h, _ = sigma_receipt(c, term)
    hashes = json.loads((c.S.blobs / env_h).read_text())["hashes"]
    bad_env = c.blob({"schema": RP.ENVIRONMENT, "hashes": list(reversed(hashes))})
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": bad_env, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, dict(rec, environment=bad_env), trajectory="sigma-glyph/sigma-resume"))
    disp, v, why = verdict_of(assess(c), d)
    check("X15", disp == "OPEN" and "sorted unique" in why[0], "a non-canonical environment manifest is refused", why)

    # X16 exactly one crossing per REPLAYED mapping; acceptance policy still applies
    c = LT.Case()
    chk, _ = computation(c, 12000)
    a1, a2 = crossing(c, ski_receipt(c, chk)), crossing(c, ski_receipt(c, chk), trajectory="elsewhere")
    d = c.open(admits=[["DISCHARGED", "REPLAYED"]], acceptance=[], computation={"runtime": "ski@v1", "check": chk,
                                                                                 "expect": TRUE_H})
    t = L.transition("REPLAYED", [a1, a2], closes=[L.mapping(d, "DISCHARGED", [a1, a2])])
    c.record("propose", c.blob(t), LT.CLAUDE, prior=[d])
    d2, tid2 = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H}, crossing(c, ski_receipt(c, chk)),
                            acceptance=[LT.CODEX])
    rep = assess(c)
    pending = verdict_of(rep, d2)
    c.accept(LT.CODEX, d2, tid2, evidence=[crossing(c, ski_receipt(c, chk))])
    check("X16", "exactly one crossing" in verdict_of(rep, d)[2][0] and pending[1] == ["PENDING"]
          and assess(c)["duties"][d2]["disposition"] == "DISCHARGED",
          "one crossing per replayed mapping; required acceptors still required", (verdict_of(rep, d), pending))

    # X17 the second lock: a worker whose pins were edited together with the vendored
    # bytes still reports a digest the assessing side does not admit
    c = LT.Case()
    _, term = computation(c, 12000)
    rec, env_h, _ = sigma_receipt(c, term)
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    tmp = Path(tempfile.mkdtemp(prefix="replay-pin2-"))
    shutil.copytree(Path(RP.WORKER).parent / "sigma_resume_c864d3e", tmp / "sigma_resume_c864d3e")
    moved = tmp / "sigma_resume_c864d3e" / "sigma_resume.py"
    with moved.open("a") as f:
        f.write("\n# moved, and the worker's pin moved with it\n")
    import hashlib
    new_pin = hashlib.sha256(moved.read_bytes()).hexdigest()
    worker = Path(RP.WORKER).read_text().replace(RP.SIGMA_RESUME_PIN, new_pin)
    (tmp / "replay_sigma_worker.py").write_text(worker)
    saved = RP.WORKER
    RP.WORKER = tmp / "replay_sigma_worker.py"
    try:
        disp, v, why = verdict_of(assess(c), d)
    finally:
        RP.WORKER = saved
    check("X17", disp == "OPEN" and "verifier not pinned: sigma_resume_c864d3e/sigma_resume.py" in why[0],
          "a worker re-pinned to moved bytes is not admitted by the assessing side", why)

    # X18 (S2-01): credit only for a crossing into a target THIS recipient accepts
    c = LT.Case()
    chk, _ = computation(c, 12000)
    rcpt = ski_receipt(c, chk)
    foreign = c.blob(dict(json.loads((c.S.blobs / crossing(c, rcpt)).read_text()),
                          target_profile="unaccepted-other-recipient"))
    d_f, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H}, foreign)
    d_ok, _ = replay_close(c, {"runtime": "ski@v1", "check": chk, "expect": TRUE_H}, crossing(c, rcpt))
    rep = assess(c)
    no_profile = assess(c, profile=None)
    check("X18", verdict_of(rep, d_f)[0] == "OPEN" and "not accepted by this recipient" in verdict_of(rep, d_f)[2][0]
          and verdict_of(rep, d_ok)[0] == "DISCHARGED" and verdict_of(no_profile, d_ok)[0] == "OPEN",
          "a foreign or unaccepted target gives no credit; the accepted one does",
          (verdict_of(rep, d_f), verdict_of(no_profile, d_ok)))

    # X19 (S2-02): the glyph kernel is part of the pinned verifier, worker re-pin or not
    c, d = sigma_case()

    def drift_glyph(tmp):
        import hashlib
        g = tmp / "sigma_resume_c864d3e" / "sigma_glyph.py"
        before = hashlib.sha256(g.read_bytes()).hexdigest()
        with g.open("a") as f:
            f.write("\n# moved\n")
        w = (tmp / "replay_sigma_worker.py").read_text().replace(before, hashlib.sha256(g.read_bytes()).hexdigest())
        (tmp / "replay_sigma_worker.py").write_text(w)
    saved = with_verifier_copy(drift_glyph)
    try:
        disp, v, why = verdict_of(assess(c), d)
    finally:
        RP.WORKER = saved
    check("X19", disp == "OPEN" and "verifier not pinned: sigma_resume_c864d3e/sigma_glyph.py" in why[0],
          "a moved glyph kernel is refused even with the worker re-pinned", why)

    # X20 (S2-03): the assessment identity changes whenever the verifier observation does
    c, d = sigma_case()
    good1, good2 = assess(c), assess(c)
    saved = with_verifier_copy(lambda tmp: (tmp / "sigma_resume_c864d3e" / "sigma_resume.py").open("a").write("\n#\n"))
    try:
        drifted = assess(c)
    finally:
        RP.WORKER = saved
    saved = with_verifier_copy(lambda tmp: (tmp / "sigma_resume_c864d3e" / "sigma_resume.py").unlink())
    try:
        missing = assess(c)
    finally:
        RP.WORKER = saved
    ids = [x["view"]["assessment_id"] for x in (good1, good2, drifted, missing)]
    check("X20", ids[0] == ids[1] and len(set(ids[1:])) == 3
          and verdict_of(good1, d)[0] == "DISCHARGED" and verdict_of(drifted, d)[0] == "OPEN"
          and "verifier missing" in verdict_of(missing, d)[2][0],
          "same verifier, same id; drifted or missing verifier, different ids", ids)

    # X21 (S2-02): the worker itself is part of the verifier. A worker that prints a
    # well-formed success without verifying anything is refused by its digest.
    c, d = sigma_case()
    pins = json.loads((Path(RP.WORKER).parent / "sigma_resume_c864d3e" / "PIN.json").read_text())["files"]
    liar = ("import json\nprint(json.dumps({'basis': 'REPLAYED', 'code': 'NORMAL_FORM', "
            f"'result_term_hash': '{TRUE_H}', 'verifier': {pins!r}}}))\n")
    saved = with_verifier_copy(lambda tmp: (tmp / "replay_sigma_worker.py").write_text(liar))
    try:
        disp, v, why = verdict_of(assess(c), d)
    finally:
        RP.WORKER = saved
    check("X21", disp == "OPEN" and "replay_sigma_worker.py" in why[0],
          "a worker that does not verify is not admitted, whatever it prints", why)

    # X22 (S2-04): the verifier is replaced on disk AFTER its bytes are observed and
    # BEFORE it runs. The real computation answers FALSE; the receipt claims TRUE;
    # the duty requires TRUE. Only the replacement would say TRUE.
    c = LT.Case()
    _, term = computation(c, 65088)
    rec, env_h, _ = sigma_receipt(c, term, claim=TRUE_H)
    comp = {"runtime": "sigma-resume", "input_term_hash": term, "environment": env_h, "expect": TRUE_H}
    d, _ = replay_close(c, comp, crossing(c, rec, trajectory="sigma-glyph/sigma-resume"))
    pins = json.loads((Path(RP.WORKER).parent / "sigma_resume_c864d3e" / "PIN.json").read_text())["files"]
    liar = ("import json\nprint(json.dumps({'basis': 'REPLAYED', 'code': 'NORMAL_FORM', "
            f"'result_term_hash': '{TRUE_H}', 'verifier': {pins!r}}}))\n")
    saved = with_verifier_copy(lambda tmp: None)
    honest = assess(c)
    hook = "capture" if hasattr(RP, "capture") else "observe"   # the observation boundary
    real = getattr(RP, hook)

    def then_replace(*a, **kw):
        got = real(*a, **kw)
        Path(RP.WORKER).write_text(liar)       # the original path, after it was observed
        return got
    setattr(RP, hook, then_replace)
    try:
        raced = assess(c)
    finally:
        setattr(RP, hook, real)
        RP.WORKER = saved
    check("X22", verdict_of(honest, d)[0] == "OPEN" and verdict_of(raced, d)[0] == "OPEN"
          and "disagrees" in verdict_of(raced, d)[2][0]
          and raced["view"]["assessment_id"] == honest["view"]["assessment_id"],
          "the bytes observed are the bytes that run: a later replacement is never executed",
          (verdict_of(honest, d), verdict_of(raced, d)))

    failed = sorted(k for k, v in results.items() if v == "FAIL")
    print(f"REPLAY: {sum(v == 'PASS' for v in results.values())} PASS / {len(failed)} FAIL"
          + (f" ({', '.join(failed)})" if failed else ""))
    if os.environ.get("REPLAY_RESULTS"):
        Path(os.environ["REPLAY_RESULTS"]).write_text(json.dumps(results))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
