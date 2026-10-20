#!/usr/bin/env python3
"""Computation as a closure condition (SPEC §7), through the one pinned provider.

    python3 tests/compute_test.py
"""
import base64
import json
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
    return out["input"], w.blob(P.environment_doc(nodes)), runtime


def run(w, inp, env, runtime, credits, hashes=None):
    """Producer: start, then advance once per credit. Returns the final (outcome, ckpt, state, result)."""
    snap = w.store.snapshot()
    hs = hashes if hashes is not None else snap.json_blob(env)["hashes"]
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


def assess(w, targets=(TARGET,), provider=PROV, providers=None):
    accepted = [PROV.id] if providers is None else providers
    return w.assess(prof=E.profile(targets=targets, providers=accepted), provider=provider)


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
    hs = snap.json_blob(env)["hashes"]
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
    hs = snap.json_blob(env)["hashes"]
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
    inner = [h for h in snap.json_blob(env)["hashes"] if h != inp]
    d = compute_duty(w, inp, env, rt, result)
    w.close(d, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    part = Path(tempfile.mkdtemp()) / "store"
    shutil.copytree(w.store.root, part)
    for h in inner:
        (part / "blobs" / h).unlink()
    from warrant.store import Snapshot
    rep_missing = E.assess(Snapshot.read(part), w.trust, 10_000, E.profile(targets=[TARGET], providers=[PROV.id]),
                           provider=PROV)
    inpY, envY, _ = term(w, "Y I")          # Y is not a Book I primitive: a reference outside this environment
    outcomes, ckY, stY, _ = run(w, inpY, envY, P.BOOK1, [100])
    why_missing = last(rep_missing, d)["why"]
    check("C9", outcomes == ["BLOCKED_REFERENCE"] and "EVIDENCE_UNAVAILABLE" in why_missing
          and rep_missing["duties"][d]["disposition"] == "OPEN",
          "missing allowed bytes are a local UNVERIFIED; a reference outside the environment is the kernel's answer",
          (outcomes, why_missing))

    # C10: the bytes whose identity was computed are the bytes that run. A copy of
    # the installed provider is captured, then its files on disk are replaced (the
    # kernel by one that exits, the provider by one that prints success): the
    # captured provider still replays genuinely. A drifted copy has another identity.
    tmp = Path(tempfile.mkdtemp()) / "provider"
    tmp.mkdir()
    for n in P.MODULES:
        (tmp / f"{n}.py").write_bytes(PROV.sources[n])
    cap = P.Provider.capture(tmp)
    (tmp / "sigma_resume.py").write_bytes(b"raise SystemExit('swapped after the capture')\n")
    (tmp / "sigma_provider.py").write_bytes(b"def handle(req):\n    return {'sigma_provider': 1, 'ok': {'results': [{'basis': 'REPLAYED', 'code': 'NORMAL_FORM', 'result': 'x'}]}}\n")
    drifted = P.Provider.capture(tmp)
    w, inp, env, rt, ck, st, result = ok_case
    snap = w.store.snapshot()
    hs = snap.json_blob(env)["hashes"]
    try:
        out = cap.call("verify", {"runtime": rt, "input": inp, "hashes": hs,
                                  "chain": [[base64.b64encode(snap.blobs[ck]).decode(), base64.b64encode(snap.blobs[st]).decode()]]},
                       {h: snap.blobs[h] for h in hs})
    except P.ProviderError as e:
        out = {"results": [{"error": str(e)[:120]}]}
    check("C10", cap.id == PROV.id and drifted.id != PROV.id and out.get("results", [{}])[0].get("result") == result,
          "captured bytes run; bytes swapped later neither run nor keep the identity", (out, drifted.id[:12]))

    # C11: the recipient accepts providers by identity; an unaccepted one, or the
    # drifted copy above, is UNVERIFIED, never admitted
    d11 = compute_duty(w, inp, env, rt, result)
    w.close(d11, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    not_accepted = assess(w, providers=[])
    forged = assess(w, provider=drifted)
    check("C11", "not one this recipient accepts" in last(not_accepted, d11)["why"]
          and "not one this recipient accepts" in last(forged, d11)["why"]
          and not_accepted["duties"][d11]["disposition"] == forged["duties"][d11]["disposition"] == "OPEN",
          "a provider the recipient did not accept, or a changed one, closes nothing",
          (last(not_accepted, d11)["why"], last(forged, d11)["why"]))

    # C12: no provider installed is a refusal, and the provider's identity is part
    # of the assessment's identity
    empty = Path(tempfile.mkdtemp())
    try:
        P.Provider.capture(empty)
        missing = False
    except P.ProviderError:
        missing = True
    a_id, b_id = assess(w)["assessment_id"], assess(w, provider=drifted)["assessment_id"]
    check("C12", missing and a_id != b_id, "a missing provider refuses; another provider is another assessment",
          (missing, a_id[:12], b_id[:12]))

    # C14 (W140-01, Codex review of 117a869): the provider owns its bytes. The dict a
    # caller passed in is changed after construction to a handle that prints a
    # NORMAL_FORM without replaying; the provider still replays genuinely, its
    # source view refuses assignment, and a provider made from the changed bytes
    # has another identity, which the old profile does not accept.
    fake = b"def handle(req):\n    return {'sigma_provider': 1, 'ok': {'results': [{'basis': 'REPLAYED', 'code': 'NORMAL_FORM', 'result': 'x'}], 'verifier': 'v'}}\n"
    mine = dict(PROV.sources)
    owned = P.Provider(mine, PROV.where)
    mine["sigma_provider"] = fake
    w, inp, env, rt, ck, st, result = ok_case
    d14 = compute_duty(w, inp, env, rt, result)
    w.close(d14, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, term(w, "K")[0])])
    rep14 = assess(w, provider=owned)
    try:
        owned.sources["sigma_provider"] = fake
        writable = True
    except TypeError:
        writable = False
    changed = P.Provider(mine, PROV.where)
    check("C14", owned.id == PROV.id and not writable and rep14["duties"][d14]["disposition"] == "OPEN"
          and "disagrees" in last(rep14, d14)["why"] and changed.id != PROV.id
          and "not one this recipient accepts" in last(assess(w, provider=changed), d14)["why"],
          "a caller's alias cannot change what runs under an accepted provider id",
          (writable, last(rep14, d14)["why"], changed.id[:12]))

    # C13: Warrant computes the identity with Sigma's own formula
    import subprocess
    code = ("import json,sigma_provider as p,sys; from pathlib import Path;"
            "d=Path(p.__file__).parent; print(p.identity_of({n: (d/n).read_bytes() for n in p.FILES}))")
    theirs = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=tempfile.gettempdir()).stdout.strip()
    check("C13", theirs == PROV.id, "the provider identity agrees with sigma_provider.identity_of", (theirs, PROV.id))

    # C15: an environment's blob address is Sigma's own environment_id for the same hash set
    w15 = World()
    _, env15, _ = term(w15, "S K K (K I)")
    hs15 = P.environment_hashes(w15.store.snapshot().json_blob(env15))
    code = ("import json,sys,sigma_resume as r;"
            "print(r.Environment([bytes.fromhex(h) for h in json.load(sys.stdin)], {}).environment_id)")
    sigma_env = subprocess.run([sys.executable, "-c", code], input=json.dumps(hs15), capture_output=True, text=True,
                               cwd=tempfile.gettempdir()).stdout.strip()
    check("C15", sigma_env == env15, "an environment blob is addressed by sigma_resume's environment_id", (sigma_env, env15))
    # C16-C18: a receiver-local cache of verified replays (SPEC §7) changes cost, never the answer
    class Counting(P.Provider):
        """The pinned provider, counting its verify calls; `drift` appends a comment to
        one module so the identity differs while the provider still works."""
        def __init__(self, drift=b""):
            src = dict(PROV.sources)
            src["sigma_provider"] = src["sigma_provider"] + drift
            super().__init__(src, PROV.where)
            self.calls = 0

        def call(self, op, args, blobs=None, timeout=600):
            self.calls += op == "verify"
            return super().call(op, args, blobs, timeout)

    w = World()
    inp, env, rt = term(w, "S K K (K I)")
    _, ck, st, result = run(w, inp, env, rt, [100])
    d = compute_duty(w, inp, env, rt, result)
    w.close(d, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    cache = str(Path(tempfile.mkdtemp()) / "replay-cache")
    prov = Counting()
    prof = E.profile(targets=[TARGET], providers=[prov.id])
    cold = E.assess(w.store.snapshot(), w.trust, 10_000, prof, provider=prov, replay_cache=cache)
    n_cold = prov.calls
    warm = E.assess(w.store.snapshot(), w.trust, 10_000, prof, provider=prov, replay_cache=cache)
    check("C16", n_cold == 1 and prov.calls == 1 and cold["assessment_id"] == warm["assessment_id"]
          and cold["duties"][d]["disposition"] == warm["duties"][d]["disposition"] == "DISCHARGED"
          and verdicts(cold, d) == verdicts(warm, d),
          "the second assessment replays nothing and reports the same verdicts under the same identity",
          (n_cold, prov.calls, verdicts(warm, d)))
    part = Path(tempfile.mkdtemp()) / "store"
    shutil.copytree(w.store.root, part)
    for h in [h for h in w.store.snapshot().json_blob(env)["hashes"] if h != inp]:
        (part / "blobs" / h).unlink()
    from warrant.store import Snapshot
    lacking = E.assess(Snapshot.read(part), w.trust, 10_000, prof, provider=prov, replay_cache=cache)
    check("C17", lacking["duties"][d]["disposition"] == "OPEN" and "EVIDENCE_UNAVAILABLE" in last(lacking, d)["why"]
          and prov.calls == 2,
          "a cached replay never stands in for bytes the view lacks: the provider is asked, and says what it would say",
          (verdicts(lacking, d), prov.calls))
    other = Counting(drift=b"\n# a drifted copy\n")
    prof2 = E.profile(targets=[TARGET], providers=[other.id])
    rep2 = E.assess(w.store.snapshot(), w.trust, 10_000, prof2, provider=other, replay_cache=cache)
    check("C18", other.id != prov.id and other.calls == 1 and rep2["duties"][d]["disposition"] == "DISCHARGED",
          "the cache is keyed by the provider identity: another provider replays for itself", (other.calls, verdicts(rep2, d)))
    return finish("COMPUTE")


if __name__ == "__main__":
    sys.exit(main())
