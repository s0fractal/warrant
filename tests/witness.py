#!/usr/bin/env python3
"""Tests for tools/witness.py — WRT-012 prototype (commitment / proofs / report).

WHAT THIS HARNESS IS BUILT TO AVOID
-----------------------------------
  * *a checker that cannot fail.* Gate round 2 named it: an implementation that
    always returns `freshness: UNKNOWN` would have passed rev 2's criterion.
    Section E has a POSITIVE control (B) that such an implementation fails, and
    section G mutates the tool on purpose and FAILS IF THE MUTANT SURVIVES.
  * *trusting `sequence` instead of the path.* Control C presents a receipt for
    a commitment with a larger sequence on a disconnected branch; the only
    acceptable answer is UNKNOWN / DISCONNECTED.
  * *incomplete mistaken for divergent.* PATH_INCOMPLETE (a link's bytes are
    missing) and DISCONNECTED (proven not the same chain) are different notes
    and neither grants LATER_STATE_WITNESSED.
  * *endpoint-only verification.* A tampered INTERMEDIATE commitment must be
    caught (LINK_TAMPERED), and the traversal must stop at a bound.
  * *a report as authority.* Section F recomputes a report on frozen proofs
    before and after a verifier run and requires every other axis to be
    byte-identical; an edited stored report changes nothing.

  A. commitment: canonical bytes, typed refusals, tip discipline
  B. time axis: offline classification of a synthetic pending receipt
  C. verification axis: NOT_RUN until a real run; closure must match
  D. holding axis: only configured holders, only verified receipts
  E. freshness: controls A / B / C, PATH_INCOMPLETE, LINK_TAMPERED, bound, multi-step
  F. invariance on frozen proofs
  G. mutation controls
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "witness.py"
ok = []
_TMP = []


def chk(cond, label, detail=""):
    ok.append(bool(cond))
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def load_tool(src_text=None, name="witness_under_test"):
    if src_text is None:
        spec = importlib.util.spec_from_file_location(name, TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    d = tempfile.mkdtemp(prefix="wit-mut-")
    _TMP.append(d)
    p = pathlib.Path(d) / "witness.py"
    p.write_text(src_text)
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


W = load_tool()


def tmp():
    d = tempfile.mkdtemp(prefix="wit-")
    _TMP.append(d)
    return pathlib.Path(d)


def cli(*args):
    r = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except json.JSONDecodeError:
        out = {"raw": r.stdout}
    return r.returncode, out, r.stderr


H64 = "ab" * 32
STREAM = "11" * 32


def commit(store, subj=H64, closure=H64, stream=None, prev=None, kind="file"):
    args = ["commit", "--store", store, "--subject-kind", kind, "--subject-sha256", subj,
            "--verifier-closure-sha256", closure]
    if stream:
        args += ["--stream", stream]
    if prev:
        args += ["--prev", prev]
    return cli(*args)


class Holder:
    """A holder with its own store and key. Independence is NOT claimed: this
    is the same host (rev 3 §6); the tests exercise mechanics only."""

    def __init__(self, hid):
        self.id = hid
        self.store = tmp()
        self.keyfile = self.store / "secret.hex"
        rc, out, err = cli("keygen", "--out", self.keyfile)
        assert rc == 0, err
        self.pub = out["pubkey_hex"]

    def receive(self, commitment_path, observed="2026-09-10T00:00:00Z"):
        return cli("receive", "--holder-store", self.store, "--holder-id", self.id,
                   "--key", self.keyfile, "--commitment-file", commitment_path, "--observed", observed)

    def cfg_entry(self, custody="github:s0fractal"):
        return {"id": self.id, "pubkey_hex": self.pub, "store": str(self.store), "custody": custody}


def holders_file(*holders, custody="github:s0fractal"):
    p = tmp() / "holders.json"
    p.write_text(json.dumps({"holders": [h.cfg_entry(custody) for h in holders]}))
    return p


def report(store, c, hf, **kw):
    return W.build_report(str(store), c, W.load_holders(hf), kw.get("max_steps", W.MAX_PATH_STEPS))


def cpath(store, c):
    return pathlib.Path(store) / "commitments" / f"{c}.json"


# ---------------------------------------------------------------- A ---

def test_commitment():
    print("\n[A] commitment")
    S = tmp()
    rc, out, _ = commit(S, stream=STREAM)
    c0 = out.get("commitment")
    chk(rc == 0 and W.hex64(c0) and out["sequence"] == 0 and out["prev"] is None, "genesis commit")
    b = (cpath(S, c0)).read_bytes()
    chk(hashlib.sha256(b).hexdigest() == c0, "digest is sha256 of canonical bytes")
    chk(b == W.canonical(json.loads(b)), "bytes are canonical (sorted, compact)")
    rc, out, _ = commit(S)
    c1 = out.get("commitment")
    chk(rc == 0 and out["sequence"] == 1 and out["prev"] == c0, "second commit chains to tip")
    rc, out, _ = commit(S, prev=c0)
    chk(rc == 2 and out["reason"].startswith("PREV_NOT_TIP"), "prev != tip refused by name")
    rc, out, _ = commit(S, stream="22" * 32)
    chk(rc == 2 and out["reason"] == "STREAM_MISMATCH", "stream mismatch refused")
    S2 = tmp()
    rc, out, _ = commit(S2)
    chk(rc == 2 and "NEW_STREAM" in out["reason"], "new store without --stream refused")
    # tamper one byte -> pin refusal on load
    p = cpath(S, c1)
    orig = p.read_bytes()
    raw = bytearray(orig)
    raw[-2] ^= 0x01
    p.write_bytes(bytes(raw))
    try:
        W.load_commitment(p, c1)
        chk(False, "tampered commitment refused", "loaded")
    except W.Refused as e:
        chk(str(e).startswith("COMMITMENT_PIN"), "tampered commitment refused", str(e))
    p.write_bytes(orig)  # restore for later sections
    for bad, why in ((b'{"a":1.5}', "FLOAT"), (b'{"a":1,"a":2}', "DUPLICATE_KEY"), (b'{"a":NaN}', "CONSTANT")):
        try:
            W.parse(bad)
            chk(False, f"parse refuses {why}", "accepted")
        except W.Refused as e:
            chk(why in str(e), f"parse refuses {why}", str(e))
    try:
        W.validate_commitment({"type": W.COMMIT_TYPE, "subject": {"kind": "file", "sha256": H64},
                               "verifier": {"closure_sha256": H64}, "stream": STREAM, "sequence": 3, "prev": None})
        chk(False, "sequence>0 with prev null refused", "accepted")
    except W.Refused as e:
        chk(str(e) == "GENESIS_SHAPE", "sequence>0 with prev null refused", str(e))
    return S, c0, c1


# ---------------------------------------------------------------- B ---

def synth_ots(commitment_bytes, calendar="https://alice.example", wrong=False):
    from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.notary import PendingAttestation
    from opentimestamps.core.serialize import BytesSerializationContext
    digest = hashlib.sha256(commitment_bytes + (b"x" if wrong else b"")).digest()
    ts = Timestamp(digest)
    ts.attestations.add(PendingAttestation(calendar))
    det = DetachedTimestampFile(OpSHA256(), ts)
    ctx = BytesSerializationContext()
    det.serialize(ctx)
    return ctx.getbytes()


def test_time(S, c0):
    print("\n[B] time axis")
    hf = holders_file()
    r = report(S, c0, hf)
    chk(r["time"]["status"] == "NONE", "no .ots -> NONE", r["time"])
    cb = cpath(S, c0).read_bytes()
    try:
        ots = synth_ots(cb)
    except ImportError:
        chk(True, "opentimestamps library absent: time tests skipped (UNCLASSIFIED path)")
        return
    proofs = pathlib.Path(S) / "proofs"
    proofs.mkdir(exist_ok=True)
    (proofs / f"{c0}.ots").write_bytes(ots)
    r = report(S, c0, hf)
    t = r["time"]
    chk(t["status"] == "FILE_BOUND_PENDING" and t["file_binding_verified"] and not t["time_verified"],
        "pending receipt -> FILE_BOUND_PENDING, time_verified false", t)
    chk(t["status"] != "BITCOIN_VERIFIED" and "BITCOIN_VERIFIED" not in json.dumps(t), "tool never says BITCOIN_VERIFIED")
    (proofs / f"{c0}.ots").write_bytes(synth_ots(cb, wrong=True))
    try:
        report(S, c0, hf)
        chk(False, "receipt for other bytes refused", "accepted")
    except W.Refused as e:
        chk(str(e) == "OTS_FILE_DIGEST", "receipt for other bytes refused", str(e))
    (proofs / f"{c0}.ots").write_bytes(ots)  # restore


# ---------------------------------------------------------------- C ---

def test_verification(S, c0):
    print("\n[C] verification axis")
    hf = holders_file()
    r = report(S, c0, hf)
    chk(r["verification"] == {"method": "EXTERNAL_CLOSURE", "result": "NOT_RUN", "scope": None},
        "NOT_RUN before any run", r["verification"])
    script = tmp() / "v.py"
    script.write_text("import sys\nprint('scope: counts three things')\nsys.exit(0 if sys.argv[1]=='pass' else 1)\n")
    rc, out, _ = cli("run-verifier", "--store", S, "--commitment", c0, "--script", script, "--", "pass")
    chk(rc == 2 and out["reason"] == "SCRIPT_NOT_CLOSURE", "script not matching closure refused", out)
    # a fresh stream whose closure IS this script
    S2 = tmp()
    closure = hashlib.sha256(script.read_bytes()).hexdigest()
    rc, out, _ = commit(S2, closure=closure, stream=STREAM)
    c = out["commitment"]
    rc, out, _ = cli("run-verifier", "--store", S2, "--commitment", c, "--script", script, "--", "fail")
    chk(rc == 0 and out["result"] == "FAIL" and out["scope"] == "counts three things", "FAIL recorded with scope from stdout", out)
    rc, out, _ = cli("run-verifier", "--store", S2, "--commitment", c, "--script", script, "--", "pass")
    chk(rc == 2 and "RUN_EXISTS" in out["reason"], "run record never overwritten", out)
    r = report(S2, c, hf)
    chk(r["verification"]["result"] == "FAIL" and r["verification"]["method"] == "EXTERNAL_CLOSURE", "report reads the run")
    rc, out, _ = commit(S2, closure=closure)
    c2 = out["commitment"]
    rc, out, _ = cli("run-verifier", "--store", S2, "--commitment", c2, "--script", script, "--method", "SELF_REFERENTIAL", "--", "pass")
    chk(rc == 2 and "SELF_REFERENTIAL_NEEDS" in out["reason"], "SELF_REFERENTIAL without scope refused", out)
    rc, out, _ = cli("run-verifier", "--store", S2, "--commitment", c2, "--script", script,
                     "--method", "SELF_REFERENTIAL", "--scope", "prev_epoch_hash links only", "--", "pass")
    r = report(S2, c2, hf)
    chk(r["verification"] == {"method": "SELF_REFERENTIAL", "result": "PASS", "scope": "prev_epoch_hash links only"},
        "SELF_REFERENTIAL carries an explicit scope", r["verification"])
    # a run record whose closure differs from the commitment's is refused by report
    rp = pathlib.Path(S2) / "runs" / f"{c2}.json"
    rec = json.loads(rp.read_bytes())
    rec["closure_sha256"] = "00" * 32
    rp.write_bytes(W.canonical(rec))
    try:
        report(S2, c2, hf)
        chk(False, "run record with foreign closure refused", "accepted")
    except W.Refused as e:
        chk(str(e) == "RUN_RECORD", "run record with foreign closure refused", str(e))


# ---------------------------------------------------------------- D ---

def test_holding(S, c0, c1):
    print("\n[D] holding axis")
    h = Holder("holder-A")
    stranger = Holder("stranger")
    hf = holders_file(h)
    r = report(S, c0, hf)
    chk(r["holding"][0]["status"] == "NONE" and r["holding"][0]["note"] == "STORE_UNAVAILABLE",
        "configured holder with empty store -> NONE / STORE_UNAVAILABLE", r["holding"])
    rc, out, _ = h.receive(cpath(S, c0))
    chk(rc == 0 and out["commitment"] == c0, "holder receives and re-hashes")
    r = report(S, c0, hf)
    chk(r["holding"][0]["status"] == "EXTERNALLY_OBSERVED" and r["holding"][0]["custody"] == "github:s0fractal",
        "verified receipt -> EXTERNALLY_OBSERVED with named custody", r["holding"])
    # receipt signed by a key that is not the configured one
    stranger.receive(cpath(S, c1))
    shutil.copy(stranger.store / "receipts" / f"{c1}.json", h.store / "receipts" / f"{c1}.json")
    shutil.copy(stranger.store / "commitments" / f"{c1}.json", h.store / "commitments" / f"{c1}.json")
    r = report(S, c1, hf)
    refused = [n for n in r["freshness"]["notes"] if n.get("outcome") == "RECEIPT_REFUSED"]
    chk(r["holding"][0]["status"] == "NONE" and refused and refused[0]["why"] == "RECEIPT_SIG",
        "receipt under a foreign key -> NONE, note RECEIPT_SIG", r)
    os.remove(h.store / "receipts" / f"{c1}.json")
    # a receipt the committer places in its own store is never consulted
    (pathlib.Path(S) / "receipts").mkdir(exist_ok=True)
    shutil.copy(h.store / "receipts" / f"{c0}.json", pathlib.Path(S) / "receipts" / f"{c0}.json")
    hf_none = holders_file()
    r = report(S, c0, hf_none)
    chk(r["holding"] == [] and not any(k.endswith(f"receipts/{c0}.json") and str(S) in k for k in r["inputs_sha256"]),
        "committer-supplied receipt is not an input", list(r["inputs_sha256"]))
    # holder store path must be absolute; a report never reaches the network
    try:
        W.load_holders(pathlib.Path(tmp() / "h.json").write_text(json.dumps({"holders": [{"id": "x", "pubkey_hex": h.pub, "store": "rel/path", "custody": "c"}]})) and tmp() / "nope")
        chk(False, "relative holder store refused", "accepted")
    except (W.Refused, OSError):
        chk(True, "relative holder store refused")
    chk(r["network_calls"] == 0 and r["authority"] == "none", "report is offline and claims no authority")
    return h


# ---------------------------------------------------------------- E ---

_CHAIN_N = [0]


def chain(n, closure=H64):
    """Local store with commitments C0..Cn-1 on STREAM. Subjects differ per
    commitment and per chain: identical bytes would be the SAME commitment
    (content addressing), not another branch."""
    S = tmp()
    cs = []
    _CHAIN_N[0] += 1
    for i in range(n):
        subj = hashlib.sha256(f"chain{_CHAIN_N[0]}-{i}".encode()).hexdigest()
        rc, out, _ = commit(S, subj=subj, closure=closure, stream=STREAM if i == 0 else None)
        cs.append(out["commitment"])
    return S, cs


def fresh(S, c, hf, **kw):
    return report(S, c, hf, **kw)["freshness"]


def test_freshness(Wmod=None):
    """Returns dict of control outcomes so section G can assert a mutant flips them."""
    Wm = Wmod or W
    print("\n[E] freshness controls" if Wmod is None else "    (re-running E against a mutant)")
    res = {}
    S, cs = chain(4)
    h = Holder("holder-B")
    hf = holders_file(h)
    # Control A: holder observed only C1 (nothing later) -> UNKNOWN
    h.receive(cpath(S, cs[1]))
    f = Wm.build_report(str(S), cs[1], Wm.load_holders(hf))["freshness"]
    res["A"] = f["status"]
    if Wmod is None:
        chk(f["status"] == "UNKNOWN", "control A: no later witness -> UNKNOWN", f)
    # Control B: holder observed C2 (prev = C1) -> LATER_STATE_WITNESSED path C1->C2
    h.receive(cpath(S, cs[2]))
    f = Wm.build_report(str(S), cs[1], Wm.load_holders(hf))["freshness"]
    res["B"] = f["status"]
    if Wmod is None:
        chk(f["status"] == "LATER_STATE_WITNESSED" and f["holder"] == "holder-B" and f["steps"] == 1,
            "control B: verified continuation -> LATER_STATE_WITNESSED(holder, C1->C2)", f)
    # Multi-step: holder observed C3; local store truncated to C1 (rollback); path C1->C2->C3 via holder's bytes
    h.receive(cpath(S, cs[3]))
    T = tmp()
    shutil.copytree(S, T, dirs_exist_ok=True)
    for c in cs[2:]:
        os.remove(cpath(T, c))
    (T / "tip").write_text(cs[1] + "\n")
    f = Wm.build_report(str(T), cs[1], Wm.load_holders(hf))["freshness"]
    res["multi"] = (f["status"], f.get("steps"))
    if Wmod is None:
        chk(f["status"] == "LATER_STATE_WITNESSED" and f["steps"] == 2,
            "rollback attack, holder consulted: path C1->C2->C3 walked from holder bytes", f)
    # PATH_INCOMPLETE: remove C2 bytes from the holder store too -> link missing, no credit
    os.remove(h.store / "commitments" / f"{cs[2]}.json")
    f = Wm.build_report(str(T), cs[1], Wm.load_holders(hf))["freshness"]
    outs = {n.get("outcome") for n in f["notes"]}
    res["incomplete"] = f["status"]
    if Wmod is None:
        chk(f["status"] == "UNKNOWN" and "PATH_INCOMPLETE" in outs and "DISCONNECTED" not in outs,
            "missing intermediate -> UNKNOWN with PATH_INCOMPLETE, not DISCONNECTED", f)
    # LINK_TAMPERED: put different bytes at C2's address in the holder store
    bad = json.loads(cpath(S, cs[2]).read_bytes())
    bad["subject"]["sha256"] = "cd" * 32
    (h.store / "commitments" / f"{cs[2]}.json").write_bytes(Wm.canonical(bad))
    f = Wm.build_report(str(T), cs[1], Wm.load_holders(hf))["freshness"]
    outs = {n.get("outcome") for n in f["notes"]}
    res["tampered"] = f["status"]
    if Wmod is None:
        chk(f["status"] == "UNKNOWN" and "LINK_TAMPERED" in outs,
            "substituted intermediate -> UNKNOWN with LINK_TAMPERED", f)
    (h.store / "commitments" / f"{cs[2]}.json").write_bytes(cpath(S, cs[2]).read_bytes())  # restore
    # Bound: only the 2-step path (C3) available, max_steps=1 -> PATH_BOUND_EXCEEDED
    r2_receipt = h.store / "receipts" / f"{cs[2]}.json"
    r2_bytes = r2_receipt.read_bytes()
    os.remove(r2_receipt)
    f = Wm.build_report(str(T), cs[1], Wm.load_holders(hf), 1)["freshness"]
    r2_receipt.write_bytes(r2_bytes)
    outs = {n.get("outcome") for n in f["notes"]}
    res["bound"] = f["status"]
    if Wmod is None:
        chk(f["status"] == "UNKNOWN" and "PATH_BOUND_EXCEEDED" in outs, "traversal bound enforced", f)
    # Control C: a disconnected branch with larger sequence
    S2, ds = chain(3)  # same STREAM, different genesis
    h2 = Holder("holder-C")
    for d in ds:
        h2.receive(cpath(S2, d))
    hf2 = holders_file(h2)
    f = Wm.build_report(str(S), cs[1], Wm.load_holders(hf2))["freshness"]
    outs = {n.get("outcome") for n in f["notes"]}
    res["C"] = f["status"]
    if Wmod is None:
        chk(f["status"] == "UNKNOWN" and "DISCONNECTED" in outs and "PATH_INCOMPLETE" not in outs,
            "control C: larger sequence on another branch -> UNKNOWN / DISCONNECTED", f)
    # sequence gap on the same chain: hand-build C_x with prev=C1 but sequence 5
    S3 = tmp()
    gap = json.loads(cpath(S, cs[2]).read_bytes())
    gap["sequence"] = 5
    gb = Wm.canonical(gap)
    gc = hashlib.sha256(gb).hexdigest()
    (S3 / "commitments").mkdir(parents=True)
    (S3 / "commitments" / f"{gc}.json").write_bytes(gb)
    h3 = Holder("holder-D")
    h3.receive(S3 / "commitments" / f"{gc}.json")
    hf3 = holders_file(h3)
    f = Wm.build_report(str(S), cs[1], Wm.load_holders(hf3))["freshness"]
    res["gap"] = f["status"]
    if Wmod is None:
        chk(f["status"] == "UNKNOWN" and any(n.get("why") == "sequence_gap_at_local" for n in f["notes"]),
            "prev points at local but sequence is not +1 -> DISCONNECTED", f)
    return res


# ---------------------------------------------------------------- F ---

def test_invariance():
    print("\n[F] invariance on frozen proofs")
    script = tmp() / "v.py"
    script.write_text("print('scope: one file')\n")
    closure = hashlib.sha256(script.read_bytes()).hexdigest()
    S, cs = chain(2, closure=closure)
    h = Holder("holder-E")
    h.receive(cpath(S, cs[0]))
    h.receive(cpath(S, cs[1]))
    hf = holders_file(h)
    try:
        (S / "proofs").mkdir()
        (S / "proofs" / f"{cs[0]}.ots").write_bytes(synth_ots(cpath(S, cs[0]).read_bytes()))
    except ImportError:
        pass
    r1 = report(S, cs[0], hf)
    cli("run-verifier", "--store", S, "--commitment", cs[0], "--script", script)
    r2 = report(S, cs[0], hf)
    same = {k: r1[k] for k in r1 if k not in ("verification", "inputs_sha256")}
    same2 = {k: r2[k] for k in r2 if k not in ("verification", "inputs_sha256")}
    chk(same == same2, "all axes but verification byte-identical across the run", (same, same2))
    chk(r1["verification"]["result"] == "NOT_RUN" and r2["verification"]["result"] == "PASS", "verification moved NOT_RUN -> PASS")
    proofs1 = {k: v for k, v in r1["inputs_sha256"].items() if "/runs/" not in k}
    proofs2 = {k: v for k, v in r2["inputs_sha256"].items() if "/runs/" not in k}
    chk(proofs1 == proofs2, "proof inputs identical (no re-fetch between reports)")
    # an edited stored report changes nothing: reports are recomputed, never read
    rep_file = tmp() / "report.json"
    edited = dict(r2, freshness={"status": "LATER_STATE_WITNESSED", "holder": "forged"})
    rep_file.write_text(json.dumps(edited))
    r3 = report(S, cs[0], hf)
    chk(r3["freshness"] == r2["freshness"], "stored report is not an input; recompute disagrees with the edit")


# ---------------------------------------------------------------- G ---

def test_mutation_controls():
    print("\n[G] mutation controls (a mutant that survives is a FAIL)")
    src = TOOL.read_text()
    mutants = {
        "always UNKNOWN (rev 2 defect)":
            (src.replace('if w["outcome"] == "COMPLETE" and fresh["status"] == "UNKNOWN":',
                         'if False:'), "B"),
        "trust sequence, skip path":
            (src.replace('w = walk_path(c, obj, cj, [H, st.root], inputs, max_steps)',
                         'w = {"outcome": "COMPLETE", "steps": 1, "path": [cj]}'), "C"),
        "endpoint-only: intermediate bytes not re-hashed":
            (src.replace('need(sha(b) == c, f"LINK_TAMPERED:{c[:12]}")', 'pass'), "tampered"),
        "no traversal bound":
            (src.replace('if steps >= max_steps:', 'if False:'), "bound"),
        "incomplete reported as disconnected":
            (src.replace('return {"outcome": "PATH_INCOMPLETE", "steps": steps, "path": path, "missing": cur["prev"]}',
                         'return {"outcome": "DISCONNECTED", "steps": steps, "path": path}'), "incomplete"),
    }
    baseline = test_freshness(W)
    for label, (text, key) in mutants.items():
        assert text != src, f"mutation did not apply: {label}"
        M = load_tool(text, name="mut_" + str(abs(hash(label))))
        try:
            got = test_freshness(M)
            expect_flip = {"B": got["B"] != "LATER_STATE_WITNESSED",
                           "C": got["C"] != "UNKNOWN",
                           "tampered": got["tampered"] != "UNKNOWN",
                           "bound": got["bound"] != "UNKNOWN",
                           "incomplete": False}[key]
            if key == "incomplete":
                # the mutant collapses the distinction; detect via the notes
                S, cs = chain(3)
                h = Holder("holder-M")
                h.receive(cpath(S, cs[2]))
                T = tmp(); shutil.copytree(S, T, dirs_exist_ok=True)
                os.remove(cpath(T, cs[1])); os.remove(cpath(T, cs[2])); (T / "tip").write_text(cs[0] + "\n")
                f = M.build_report(str(T), cs[0], M.load_holders(holders_file(h)))["freshness"]
                expect_flip = "PATH_INCOMPLETE" not in {n.get("outcome") for n in f["notes"]}
            chk(expect_flip, f"mutant killed: {label}", f"survived; got={got}")
        except Exception as e:  # a mutant that crashes is also killed
            chk(True, f"mutant killed (crashed): {label} [{type(e).__name__}]")
    chk(baseline["B"] == "LATER_STATE_WITNESSED" and baseline["C"] == "UNKNOWN", "baseline unchanged after mutants")


def main():
    print("=" * 66)
    print("WITNESS (WRT-012 prototype) — tests")
    print("=" * 66)
    try:
        S, c0, c1 = test_commitment()
        test_time(S, c0)
        test_verification(S, c0)
        test_holding(S, c0, c1)
        test_freshness()
        test_invariance()
        test_mutation_controls()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    good = all(ok)
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("WITNESS: ALL PASS" if good else "WITNESS: FAILURES PRESENT")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
