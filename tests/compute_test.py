#!/usr/bin/env python3
"""Computation as a closure condition (SPEC §7), through the one pinned provider.

    python3 tests/compute_test.py
"""
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from world import HOLDER, OWNER, E, P, R, World, check, finish, verdicts

PROV = P.Provider.capture()
TARGET = "warrant-test"
# 64-character strings that are not hex64 (SPEC §3: lowercase hex): a non-hex letter,
# uppercase hex, non-ASCII. Each has the right length, so a length-only check passes it.
NOT_HEX64 = {"non-hex letter": "g" * 64, "uppercase hex": "A" * 64, "non-ASCII": "\u00e9" * 64}
# Suffixes that make a genuine hex64 65 or 66 characters: `$` in an anchored pattern matches
# before a final "\n", so "<hex64>\n" passed `.match` before AMEND 2 of #164; "\r\n" is the control.
TRAILING = {"trailing newline": "\n", "trailing CRLF": "\r\n"}


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


def shape_of(predicate, doc):
    """What a shape predicate says of `doc`; a mutant may make it raise, which is a failure of the case."""
    try:
        return predicate(doc)
    except Exception as e:      # noqa: BLE001
        return f"raised {type(e).__name__}"


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
    try:
        rep = assess(w)
        got4 = (last(rep, d)["why"], last(rep, d2)["why"])
    except Exception as e:      # noqa: BLE001 (a mutant may make the replay raise: a failure of C4)
        got4 = (f"raised {type(e).__name__}: {e}", "")
    check("C4", "disagrees" in got4[0] and "PAUSED is not an answer" in got4[1],
          "the receipt's word is not the result; a pause is not an answer", got4)

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
    # C25 (pilot W3, SPEC §7): a cycle blob is exactly the members SPEC §7 lists; the
    # genuine M M cycle with one extra member is refused by name, never verified. Its
    # hash members are hex64 as SPEC §3 defines it: for each of input, environment and
    # witness a 64-character value that is not lowercase hex is refused by the shape
    # predicate as "cycle hashes" (the mirror of C23's finding; at 808c011 length only)
    full25 = {"cycle": "sigma-resume", "target": TARGET, "input": inp, "environment": env, "witness": wit, "lost": []}
    shapes25 = {"extra member": dict(full25, note="one member too many"), "short witness": dict(full25, witness=wit[:63])}
    for member in ("input", "environment", "witness"):
        for name, bad in NOT_HEX64.items():
            shapes25[f"{member} {name}"] = dict(full25, **{member: bad})
        for name, suffix in TRAILING.items():
            shapes25[f"{member} {name}"] = dict(full25, **{member: full25[member] + suffix})
    want25 = {k: "not a sigma-resume cycle" if k == "extra member" else "cycle hashes" for k in shapes25}
    direct25 = {k: shape_of(P.cycle_problem, doc) for k, doc in shapes25.items()}
    ds25 = {}
    for k, doc in shapes25.items():
        ds25[k] = compute_duty(w, inp, env, rt, "00" * 32)
        w.close(ds25[k], act="impossible", basis="REPLAYED", evidence=[w.blob(doc)])
    try:
        rep = assess(w)
        got25 = {k: last(rep, x)["why"] for k, x in ds25.items()}
        open25 = all(rep["duties"][x]["disposition"] == "OPEN" for x in ds25.values())
    except Exception as e:      # noqa: BLE001
        got25, open25 = f"raised {type(e).__name__}: {e}", False
    check("C25", direct25 == want25 and got25 == want25 and open25 and P.cycle_problem(full25) is None,
          "a cycle blob with other members, or a hash member that is not lowercase hex64, is refused by its shape",
          {k: (direct25.get(k), got25.get(k) if isinstance(got25, dict) else got25)
           for k in shapes25 if direct25.get(k) != want25[k] or not isinstance(got25, dict) or got25.get(k) != want25[k]})
    # C26 (pilot W3, SPEC §7): a cycle says nothing about other uses of the term: the
    # verified cycle of M M, filed as `impossible` for K I (M M), is refused there,
    # and K I (M M) is discharged by its own replay
    d26 = compute_duty(w, inp2, env2, rt, res2)
    w.close(d26, act="impossible", basis="REPLAYED", evidence=[cyc])
    w.close(d26, basis="REPLAYED", evidence=[receipt(w, inp2, env2, ck2, st2, res2)])
    rep = assess(w)
    imp = [c for c in rep["duties"][d26]["candidates"] if c["act"] == "impossible"]
    check("C26", rep["duties"][d26]["disposition"] == "DISCHARGED" and len(imp) == 1
          and imp[0]["why"] == "the cycle is for another computation than the condition names",
          "the cycle of M M does not make K I (M M) impossible", verdicts(rep, d26))

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
    # C27 (pilot W3, SPEC §7): outcomes about the host are UNVERIFIED, never an answer:
    # bytes the environment names but the view lacks, and a provider that runs out of
    # time (a real timeout of the separate interpreter)
    class Hurried(P.Provider):
        def call(self, op, args, blobs=None, timeout=600):
            return super().call(op, args, blobs, timeout=0.001)
    hurried = Hurried(dict(PROV.sources), PROV.where)
    rep_hurried = assess(w, provider=hurried)
    got27 = (last(rep_missing, d)["verdict"], last(rep_hurried, d)["verdict"], last(rep_hurried, d)["why"],
             rep_hurried["duties"][d]["disposition"])
    check("C27", got27 == ("UNVERIFIED", "UNVERIFIED", "provider timed out", "OPEN") and "EVIDENCE_UNAVAILABLE" in why_missing,
          "missing bytes and a provider timeout are UNVERIFIED", got27)
    # C28 (pilot W3, SPEC §7): a reference outside the environment is the kernel's
    # answer: a receipt for Y I under Book I is replayed and the replay ends in
    # BLOCKED_REFERENCE, which is not an answer; missing bytes are not replayed at all
    dY = compute_duty(w, inpY, envY, P.BOOK1, "00" * 32)
    w.close(dY, basis="REPLAYED", evidence=[receipt(w, inpY, envY, ckY, stY, "00" * 32)])
    try:
        rep = assess(w)
        got28 = (last(rep, dY)["verdict"], last(rep, dY)["why"], why_missing.startswith("not replayed:"))
    except Exception as e:      # noqa: BLE001
        got28 = f"raised {type(e).__name__}: {e}"
    check("C28", got28 == ("UNVERIFIED", "replayed, but BLOCKED_REFERENCE is not an answer", True),
          "BLOCKED_REFERENCE is a replayed kernel answer, distinct from bytes not delivered", got28)

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

    # C19-C24 (pilot W3): SPEC §7 sentences that had no case of their own before the claim records
    # C19: execution goes through the sigma_provider request protocol: a module whose
    # handle answers without the protocol marker is a ProviderError, never an answer
    loose = dict(PROV.sources)
    loose["sigma_provider"] = (b"def handle(req):\n    return {'ok': {'results': [{'basis': 'REPLAYED', "
                               b"'code': 'NORMAL_FORM', 'result': 'x'}]}}\n")
    try:
        got19 = P.Provider(loose, PROV.where).call("term", {"expr": "I"})
    except P.ProviderError as e:
        got19 = str(e)
    check("C19", got19 == "provider answered outside its protocol", "an answer outside the request protocol is refused", got19)

    # C20: the separate interpreter runs isolated (-I): a json.py planted in the working
    # directory is not what the boot code imports
    plant = Path(tempfile.mkdtemp())
    (plant / "json.py").write_text("raise SystemExit('a planted json.py was imported')\n")
    here = os.getcwd()
    os.chdir(plant)
    try:
        got20 = PROV.call("term", {"expr": "I"}).get("input")
    except P.ProviderError as e:
        got20 = str(e)[-120:]
    finally:
        os.chdir(here)
    check("C20", isinstance(got20, str) and len(got20) == 64, "a module planted in the working directory does not run",
          got20)

    # C22: a REPLAYED item cites exactly one receipt: two (one of them genuine) or none
    # are MISSING_EVIDENCE
    w = World()
    inp, env, rt = term(w, "S K K (K I)")
    _, ck, st, result = run(w, inp, env, rt, [100])
    d22 = compute_duty(w, inp, env, rt, result)
    w.close(d22, basis="REPLAYED", evidence=sorted([receipt(w, inp, env, ck, st, result),
                                                    receipt(w, inp, env, ck, st, result, target="elsewhere")]))
    d22b = compute_duty(w, inp, env, rt, result)
    w.close(d22b, basis="REPLAYED", evidence=[w.evidence("not a receipt")])
    rep = assess(w)
    got22 = [(last(rep, x)["verdict"], rep["duties"][x]["disposition"]) for x in (d22, d22b)]
    check("C22", got22 == [("MISSING_EVIDENCE", "OPEN")] * 2, "a REPLAYED item cites exactly one receipt", got22)

    # C23: a receipt is exactly the members SPEC §7 lists: a genuine one with an extra
    # member, without `lost`, or with a hash member that is not hex64 is refused by the
    # shape predicate itself, by name. hex64 is SPEC §3's lowercase hex of 64 characters:
    # for each of the five hash members a value of the right length made of a non-hex
    # letter, of uppercase hex, or of non-ASCII characters is refused as "receipt hashes"
    # (Codex AMEND on #164: at 808c011 the predicate checked the length only, and
    # those values passed it, to be refused later by the replay or a missing blob)
    full = {"receipt": "sigma-resume", "target": TARGET, "input": inp, "environment": env, "checkpoint": ck,
            "state": st, "claimed": result, "lost": []}
    shapes = {"extra member": dict(full, note="x"), "no lost": {k: v for k, v in full.items() if k != "lost"},
              "short claimed": dict(full, claimed=result[:63])}
    for member in ("input", "environment", "checkpoint", "state", "claimed"):
        for name, bad in NOT_HEX64.items():
            shapes[f"{member} {name}"] = dict(full, **{member: bad})
        for name, suffix in TRAILING.items():
            shapes[f"{member} {name}"] = dict(full, **{member: full[member] + suffix})
    want23 = {k: "not a sigma-resume receipt" if k in ("extra member", "no lost") else "receipt hashes" for k in shapes}
    direct = {k: shape_of(P.receipt_problem, doc) for k, doc in shapes.items()}
    ds23 = {}
    for k, doc in shapes.items():
        ds23[k] = compute_duty(w, inp, env, rt, result)
        w.close(ds23[k], basis="REPLAYED", evidence=[w.blob(doc)])
    try:
        rep = assess(w)
        got23 = {k: last(rep, x)["why"] for k, x in ds23.items()}
    except Exception as e:      # noqa: BLE001 (a mutant may make the replay raise)
        got23 = f"raised {type(e).__name__}: {e}"
    check("C23", direct == want23 and got23 == want23 and P.receipt_problem(full) is None,
          "a receipt with other members, or a hash member that is not lowercase hex64, is refused by its shape",
          {k: (direct.get(k) if isinstance(direct, dict) else direct, got23.get(k) if isinstance(got23, dict) else got23)
           for k in shapes if direct.get(k) != want23[k] or not isinstance(got23, dict) or got23.get(k) != want23[k]})

    # C24: the receipt's (input, environment) must be the condition's and its bytes in
    # the view. A genuine receipt of S K K (K I) filed for K I, whose duty expects the
    # same result hash, is refused; so is a receipt whose checkpoint is not in the view
    inp2, env2, _ = term(w, "K I")
    d24 = compute_duty(w, inp2, env2, rt, result)
    w.close(d24, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])
    d24b = compute_duty(w, inp, env, rt, result)
    w.close(d24b, basis="REPLAYED", evidence=[receipt(w, inp, env, "ab" * 32, st, result)])
    try:
        rep = assess(w)
        got24 = [(last(rep, x)["why"], rep["duties"][x]["disposition"]) for x in (d24, d24b)]
    except Exception as e:      # noqa: BLE001
        got24 = f"raised {type(e).__name__}: {e}"
    check("C24", got24 == [("the receipt is for another computation than the condition names", "OPEN"),
                           ("receipt bytes not in view", "OPEN")],
          "a receipt for another root, or one whose bytes are not in the view, gives no credit", got24)

    # C29 (§4.2 3, §7): only a normal form is an answer. A replay that reports PAUSED with a
    # result equal to `expect` (the counter against SPEC-4.2-7 of the Gemini deep review,
    # 2026-10-22: without the NORMAL_FORM check C4 only crashed, on a PAUSED replay that
    # carries no result) gives no credit; the same replay reported as NORMAL_FORM does.
    w = World()
    inp, env, rt = term(w, "S K K (K I)")
    _, ck, st, result = run(w, inp, env, rt, [100])
    d = compute_duty(w, inp, env, rt, result)
    w.close(d, basis="REPLAYED", evidence=[receipt(w, inp, env, ck, st, result)])

    class Paused(P.Provider):
        """The captured provider, whose verify replies say PAUSED, keeping the result."""
        def call(self, op, args, blobs=None, timeout=600):
            out = super().call(op, args, blobs, timeout)
            if op == "verify" and "results" in out:
                out = dict(out, results=[dict(r, code="PAUSED") for r in out["results"]])
            return out
    paused = Paused(dict(PROV.sources), PROV.where)
    try:
        rep_p, rep_n = assess(w, provider=paused), assess(w)
        got29 = (last(rep_p, d)["verdict"], rep_p["duties"][d]["disposition"],
                 last(rep_n, d)["verdict"], rep_n["duties"][d]["disposition"])
    except Exception as e:      # noqa: BLE001
        got29 = f"raised {type(e).__name__}: {e}"
    check("C29", got29 == ("UNVERIFIED", "OPEN", "ADMITTED", "DISCHARGED"),
          "a replay that is not a normal form is no answer, even with the expected result", got29)

    # C21 (last): the process boundary isolates module names: after every replay above,
    # this assessing process has imported none of the provider's modules
    got21 = sorted(set(P.MODULES) & set(sys.modules))
    check("C21", got21 == [], "the provider's modules never enter the assessing process", got21)
    return finish("COMPUTE")


if __name__ == "__main__":
    sys.exit(main())
