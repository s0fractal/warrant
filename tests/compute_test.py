#!/usr/bin/env python3
"""Computation as a closure condition (SPEC §7), through the one pinned provider.

    python3 tests/compute_test.py
"""
import base64
import shutil
import sys
import tempfile
from pathlib import Path

from world import HOLDER, OWNER, E, P, R, World, check, finish, verdicts

PROV = P.Provider.capture()
TARGET = "warrant-test"


def term(w, expr, runtime=P.BOOK1):
    out = PROV.call("term", {"expr": expr})
    nodes = [w.store.put_blob(base64.b64decode(b)) for b in out["nodes"].values()]
    return out["term"], w.blob(P.environment_doc(nodes)), runtime


def run(w, inp, env, runtime, credits, hashes=None):
    """Producer: start, then advance once per credit. Returns the final (outcome, ckpt, state, result)."""
    snap = w.store.snapshot()
    hs = hashes if hashes is not None else snap.json_blob(env)["sigma-environment"]
    blobs = {h: snap.blobs[h] for h in hs if h in snap.blobs}
    base = {"runtime": runtime, "input": inp, "hashes": hs}
    out = PROV.call("start", base, blobs)
    outcomes = []
    for c in credits:
        out = PROV.call("advance", dict(base, checkpoint=out["checkpoint"], state=out["state"], credit=c), blobs)
        outcomes.append(out["outcome"])
    ck = w.store.put_blob(base64.b64decode(out["checkpoint"]))
    st = w.store.put_blob(base64.b64decode(out["state"]))
    return outcomes, ck, st, out.get("result")


def receipt(w, inp, env, ck, st, claimed, target=TARGET, lost=()):
    return w.blob({"receipt": "sigma-resume", "target": target, "input": inp, "environment": env, "checkpoint": ck,
                   "state": st, "claimed": claimed, "lost": list(lost)})


def compute_duty(w, inp, env, runtime, expect):
    return w.duty({"compute": {"runtime": runtime, "input": inp, "environment": env, "expect": expect}}, accept_by=())


def assess(w, targets=(TARGET,), provider=PROV):
    return w.assess(prof=E.profile(targets=targets), provider=provider)


def last(rep, d):
    return rep["duties"][d]["candidates"][-1]


def main():
    # C1: pause -> resume -> result, replayed by the recipient
    w = World()
    inp, env, rt = term(w, "S K K (K I)")
    outcomes, ck, st, result = run(w, inp, env, rt, [2, 100])
    d = compute_duty(w, inp, env, rt, result)
    w.close(d, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    rep = assess(w)
    check("C1", outcomes == ["PAUSED", "NORMAL_FORM"] and rep["duties"][d]["disposition"] == "DISCHARGED"
          and rep["duties"][d]["assessed_basis"][0].startswith("REPLAYED:sigma-resume:"),
          "a paused and resumed computation closes its condition by the recipient's replay", (outcomes, verdicts(rep, d)))
    ok_case = (w, inp, env, rt, ck, st, result)

    # C2: a correct computation whose result is not the condition's
    w = World()
    inp, env, rt = term(w, "S K K (K I)")
    _, ck, st, result = run(w, inp, env, rt, [100])
    other = term(w, "K")[0]
    d = compute_duty(w, inp, env, rt, other)
    w.close(d, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    rep = assess(w)
    check("C2", rep["duties"][d]["disposition"] == "OPEN" and "not the one the condition requires" in last(rep, d)["why"],
          "a correct replay of another answer establishes nothing here", verdicts(rep, d))

    # C3: the recipient did not accept this translation target; something was lost
    w, inp, env, rt, ck, st, result = ok_case
    d2 = compute_duty(w, inp, env, rt, result)
    w.close(d2, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result, target="elsewhere")])
    d3 = compute_duty(w, inp, env, rt, result)
    w.close(d3, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result, lost=["cost model"])])
    rep = assess(w)
    check("C3", "not accepted by this recipient" in last(rep, d2)["why"] and "lost" in last(rep, d3)["why"]
          and rep["duties"][d2]["disposition"] == rep["duties"][d3]["disposition"] == "OPEN",
          "a replay into a target the recipient does not accept, or with a loss, gives no credit",
          (last(rep, d2)["why"], last(rep, d3)["why"]))

    # C4: a receipt that claims what the replay does not reproduce; a paused state is not an answer
    w = World()
    inp, env, rt = term(w, "S K K (K I)")
    _, ck, st, result = run(w, inp, env, rt, [100])
    d = compute_duty(w, inp, env, rt, result)
    w.close(d, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, term(w, "K")[0])])
    _, pck, pst, _ = run(w, inp, env, rt, [2])
    d2 = compute_duty(w, inp, env, rt, result)
    w.close(d2, basis="REPLAYED", evidence=[receipt(w, inp, env, pck, pst, result)])
    rep = assess(w)
    check("C4", "disagrees" in last(rep, d)["why"] and "PAUSED is not an answer" in last(rep, d2)["why"],
          "the receipt's word is not the result; a pause is not an answer", (last(rep, d)["why"], last(rep, d2)["why"]))

    # C5: a REPLAYED basis is not an attestation: without a provider it is UNVERIFIED, never admitted
    w, inp, env, rt, ck, st, result = ok_case
    rep = assess(w, provider=None)
    vs = {c["verdict"] for c in rep["duties"][d]["candidates"]} if False else None
    d4 = compute_duty(w, inp, env, rt, result)
    w.close(d4, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    w.close(d4, basis="ATTESTED")
    rep = assess(w, provider=None)
    check("C5", [c["verdict"] for c in rep["duties"][d4]["candidates"]] == ["UNVERIFIED", "OVERCLAIMED"]
          and rep["duties"][d4]["disposition"] == "OPEN",
          "no provider: UNVERIFIED; the filer's word for a computation: OVERCLAIMED", verdicts(rep, d4))
    del vs

    # C6: a verified-replay cache changes cost, not the answer or the task
    snap = w.store.snapshot()
    hs = snap.json_blob(env)["sigma-environment"]
    blobs = {h: snap.blobs[h] for h in hs}
    _, pck, pst, _ = run(w, inp, env, rt, [2])
    chain = [[base64.b64encode(snap.blobs[x] if x in snap.blobs else w.store.snapshot().blobs[x]).decode()
              for x in pair] for pair in ((pck, pst), (ck, st))]
    args = {"runtime": rt, "input": inp, "hashes": hs, "chain": chain}
    cold, warm = PROV.call("verify", args, blobs), PROV.call("verify", dict(args, cache=True), blobs)
    check("C6", cold["results"] == warm["results"] and cold["results"][1].get("result") == result,
          "the same answers with and without the cache", (cold, warm))

    # C7: a verified cycle makes THIS computation impossible, and nothing else
    w = World()
    inp, env, rt = term(w, "M M", P.RICH)
    snap = w.store.snapshot()
    hs = snap.json_blob(env)["sigma-environment"]
    found = PROV.call("find_cycle", {"runtime": rt, "input": inp, "hashes": hs, "max_steps": 50},
                      {h: snap.blobs[h] for h in hs})
    wit = w.store.put_blob(base64.b64decode(found["witness"]))
    cyc = w.blob({"cycle": "sigma-resume", "target": TARGET, "input": inp, "environment": env, "witness": wit, "lost": []})
    d = compute_duty(w, inp, env, rt, "00" * 32)
    w.close(d, act="impossible", basis="REPLAYED", evidence=[cyc])
    inp2, env2, _ = term(w, "K I (M M)", P.RICH)
    _, ck2, st2, res2 = run(w, inp2, env2, rt, [1000])
    d2 = compute_duty(w, inp2, env2, rt, res2)
    w.close(d2, basis="REPLAYED", evidence=[receipt(w, inp2, env2, ck2, st2, res2)])
    rep = assess(w)
    check("C7", rep["duties"][d]["disposition"] == "IMPOSSIBLE" and rep["duties"][d2]["disposition"] == "DISCHARGED",
          "M M has no normal form; K I (M M) still has one", (verdicts(rep, d), verdicts(rep, d2)))
    # C8: a forged cycle (the witness of another computation) is refused
    d3 = compute_duty(w, inp2, env2, rt, res2)
    cyc2 = w.blob({"cycle": "sigma-resume", "target": TARGET, "input": inp2, "environment": env2, "witness": wit, "lost": []})
    w.close(d3, act="impossible", basis="REPLAYED", evidence=[cyc2])
    rep = assess(w)
    check("C8", rep["duties"][d3]["disposition"] == "OPEN" and "cycle not proven" in last(rep, d3)["why"],
          "a witness for another root proves nothing here", last(rep, d3)["why"])

    # C9: bytes the environment names but nobody delivered, vs a reference outside the environment
    w = World()
    inp, env, rt = term(w, "S K K (K I)")
    _, ck, st, result = run(w, inp, env, rt, [100])
    snap = w.store.snapshot()
    inner = [h for h in snap.json_blob(env)["sigma-environment"] if h != inp]
    d = compute_duty(w, inp, env, rt, result)
    w.close(d, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    part = Path(tempfile.mkdtemp()) / "store"
    shutil.copytree(w.store.root, part)
    for h in inner:
        (part / "blobs" / h).unlink()
    from warrant.store import Snapshot
    rep_missing = E.assess(Snapshot.read(part), w.trust, 10_000, E.profile(targets=[TARGET]), provider=PROV)
    inpY, envY, _ = term(w, "Y I")          # Y is not a Book I primitive: a reference outside this environment
    outcomes, ckY, stY, _ = run(w, inpY, envY, P.BOOK1, [100])
    why_missing = last(rep_missing, d)["why"]
    check("C9", outcomes == ["BLOCKED_REFERENCE"] and "EVIDENCE_UNAVAILABLE" in why_missing
          and rep_missing["duties"][d]["disposition"] == "OPEN",
          "missing allowed bytes are a local UNVERIFIED; a reference outside the environment is the kernel's answer",
          (outcomes, why_missing))

    # C10: the provider runs the bytes it checked
    tmp = Path(tempfile.mkdtemp()) / "provider"
    shutil.copytree(P.HERE, tmp)
    (tmp / "sigma_resume.py").write_bytes((tmp / "sigma_resume.py").read_bytes() + b"\n# drift\n")
    try:
        P.Provider.capture(tmp)
        refused = False
    except P.ProviderError:
        refused = True
    shutil.copytree(P.HERE, tmp, dirs_exist_ok=True)
    cap = P.Provider.capture(tmp)
    (tmp / "sigma_resume.py").write_bytes(b"raise SystemExit('swapped after the check')\n")
    (tmp / "worker.py").write_bytes(b"def main(req):\n    return {'results': [{'basis': 'REPLAYED', 'code': 'NORMAL_FORM', 'result': 'x'}]}\n")
    w, inp, env, rt, ck, st, result = ok_case
    out = cap.call("verify", {"runtime": rt, "input": inp, "hashes": w.store.snapshot().json_blob(env)["sigma-environment"],
                              "chain": [[base64.b64encode(w.store.snapshot().blobs[ck]).decode(),
                                         base64.b64encode(w.store.snapshot().blobs[st]).decode()]]},
                   {h: w.store.snapshot().blobs[h] for h in w.store.snapshot().json_blob(env)["sigma-environment"]})
    check("C10", refused and out["results"][0].get("result") == result,
          "drifted kernel bytes are refused; bytes swapped after capture are not what runs", (refused, out))
    return finish("COMPUTE")


if __name__ == "__main__":
    sys.exit(main())
