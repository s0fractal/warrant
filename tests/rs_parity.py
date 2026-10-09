#!/usr/bin/env python3
"""Is the Rust implementation the reference, byte for byte?

WHAT IS COMPARED
----------------
Not counts. `tests/verify_three_way.py` already holds three implementations to
the same (records, errors, warnings); this holds the Rust implementation to the
reference's exact OUTPUT — every report line, every exit status, every byte it
writes into a store — because "the same verdict for a different reason" is a
divergence too, and a count cannot see it.

Two sources of cases:

  1. SHADOW. Every existing harness below is run with tests/rs_shadow on
     PYTHONPATH, which re-runs each `python3 impl/warrant.py ...` call it makes
     as `warrant-rs ...` with the same arguments (writers against a private copy
     of the store) and logs the comparison. The harnesses were written to break
     the reference in ways people found; reusing them means every one of those
     findings is also asked of the Rust implementation.

  2. FUZZ. Random settlement-grade stores: genesis roots, threshold policies
     (valid, invalid, non-canonical), key rotations (authorized, forged,
     conflicting), re-litigations citing cmd@v1 and ski@v1 checks, legacy and
     junk signatures, and hostile JSON (floats, duplicate names, deep nesting,
     byte order marks, UTF-16 blobs, lone surrogates). Each store is asked
     `verify` (text and --json, both grades), `why` for every record, `settle`
     for random pairs, and `check` for every check blob.

THE NEGATIVE CONTROL
--------------------
A comparison that cannot fail is not a comparison. Before anything else the
shadow hook is pointed at a deliberately wrong "implementation" (the Rust binary
behind a proxy that changes one byte of output) and must report a mismatch.

USAGE
    python3 tests/rs_parity.py                 # shadow + 150 fuzzed stores
    python3 tests/rs_parity.py --stores 1000   # a longer hunt
    python3 tests/rs_parity.py --seed 7 --no-shadow
Exit 0 only if every comparison matched and every expected kind of comparison
actually happened (a run that compared nothing is a failure, not a pass).
"""
import argparse
import hashlib
import importlib.util
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RS = Path(os.environ.get("WARRANT_RS", ROOT / "impl-rs" / "target" / "release" / "warrant-rs"))
PY = [sys.executable, str(ROOT / "impl" / "warrant.py")]
SHADOW_DIR = ROOT / "tests" / "rs_shadow"

spec = importlib.util.spec_from_file_location("warrant_ref", ROOT / "impl" / "warrant.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

ENV = {k: v for k, v in os.environ.items()
       if k not in ("SIGMA_GLYPH", "WARRANT_SIGMA_DIFFERENTIAL", "WARRANT_SKI_MAX_ATP")}

# Harnesses whose reference-CLI calls are shadowed, with their arguments.
HARNESSES = [
    ["settlement.py"], ["negative.py"], ["pedantic_edges.py"], ["verify_report.py"],
    ["domain_separation.py"], ["why_signature_predicate.py"], ["hostile.py"],
    ["evidence_pack.py"], ["differential.py"], ["sigma_cas_identity.py"],
    ["fuzz_differential.py", "--iters", "120", "--seed", "11"],
]

I_H = "2f33694d09810641fa5b8c47a7c0dc42e1b99eb8c9784a00aaee9a66330f4162"
K_H = "bc0c2fe26e44e2aed8ce500a74963bc270fd4a49ec0c2e4837ce7a64bb0a486c"
S_H = "887045bc22935aec5cba2dc11400d4e4357bc34d06681a6e92f06e7795b1f8a6"


# ------------------------------------------------------------------ shadow ----

def run_shadowed(argv, log, rs=RS):
    env = dict(ENV, PYTHONPATH=str(SHADOW_DIR), WARRANT_RS_SHADOW=str(rs),
               WARRANT_RS_SHADOW_LOG=str(log))
    return subprocess.run([sys.executable] + argv, cwd=ROOT, env=env,
                          capture_output=True, text=True)


def read_log(log):
    if not Path(log).exists():
        return []
    return [json.loads(l) for l in Path(log).read_text().splitlines() if l.strip()]


def bad(rec):
    return not (rec["same_code"] and rec["same_out"] and rec.get("same_disk", True))


def negative_control(tmp):
    """The shadow must SEE a one-byte output difference."""
    proxy = Path(tmp, "wrong-rs")
    proxy.write_text("#!/bin/sh\n\"%s\" \"$@\" | sed 's/errors/errorz/'\n" % RS)
    proxy.chmod(0o755)
    log = Path(tmp, "control.jsonl")
    store = Path(tmp, "control-store")
    shutil.copytree(ROOT / ".warrants", store)
    script = Path(tmp, "control.py")
    script.write_text("import subprocess, sys\n"
                      f"subprocess.run({PY!r} + ['--store', {str(store)!r}, 'verify'], "
                      "capture_output=True)\n")
    run_shadowed([str(script)], log, rs=proxy)
    rows = read_log(log)
    return len(rows) == 1 and bad(rows[0])


# -------------------------------------------------------------------- fuzz ----

class Store:
    def __init__(self, root, rng):
        self.root = Path(root)
        self.st = W.Store(root)
        self.st.init()
        self.rng = rng
        self.keys = {}
        self.wids = []
        self.blobs = []

    def key(self, name):
        if name not in self.keys:
            p = self.root.parent / f"{name}.key"
            p.write_text(hashlib.sha256(name.encode()).hexdigest() + "\n")
            self.keys[name] = str(p)
        return self.keys[name]

    def pub(self, name):
        return W.pubkey_hex(W.load_key(self.key(name)))

    def blob(self, data):
        h = self.st.put_blob(data)
        self.blobs.append(h)
        return h

    def jblob(self, doc):
        return self.blob(W.canon(doc))

    def write(self, env, wid=None):
        if wid is None:
            try:
                wid = W.warrant_id(env["body"])
            except Exception:
                wid = hashlib.sha256(os.urandom(8)).hexdigest()
        (self.st.records / f"{wid}.json").write_text(
            json.dumps(env, indent=2, sort_keys=True) + "\n")
        self.wids.append(wid)
        return wid

    def record(self, body, signers):
        sigs = [W.sign_envelope(body, actor, self.key(k)) for actor, k in signers]
        return self.write({"body": body, "sigs": sigs})


ACTORS = ["a@x", "b@x", "c@x"]


def ski_check(s, rng):
    """A ski@v1 check blob over a small term; the claimed expect is right or wrong."""
    A = lambda l, r: s.blob(bytes([2, 6]) + bytes.fromhex(l) + bytes.fromhex(r))
    term = rng.choice([
        lambda: A(I_H, K_H),                         # I K -> K
        lambda: A(A(A(S_H, K_H), K_H), I_H),         # S K K I -> I
        lambda: A(A(S_H, I_H), I_H),                 # S I I (normal form)
        lambda: A(I_H, hashlib.sha256(b"ghost").hexdigest()),
    ])()
    expect = rng.choice([K_H, I_H, S_H, term])
    atp = rng.choice([0, 3, 12, 50, 1000])
    doc = {"ski": 1, "term": term, "atp": atp, "expect": expect}
    if rng.random() < 0.1:
        return s.blob(json.dumps(doc).encode())     # not canonical
    if rng.random() < 0.05:
        doc["ski"] = True
    if rng.random() < 0.05:
        doc["atp"] = 1.5
        return s.blob(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode())
    return s.jblob(doc)


def reason(s, rng):
    r = rng.random()
    if r < 0.45:
        return {"kind": "prose", "text": rng.choice(["ok", "because", "no", "é "])}
    if r < 0.75:
        rec = {"kind": "check", "check": s.blob(b"#!/bin/sh\ntrue\n"), "runtime": "cmd@v1",
               "verdict": rng.choice(["pass", "fail"])}
        if rng.random() < 0.6:
            rec["transcript"] = s.blob(rng.choice([b"ok\n", b"FAIL\n"]))
        return rec
    return {"kind": "check", "check": ski_check(s, rng), "runtime": "ski@v1",
            "verdict": rng.choice(["pass", "fail"])}


def policy(s, rng):
    r = rng.random()
    if r < 0.35:
        return s.blob(rng.choice([b"policy one\n", b"policy two\n"]))
    actors = rng.sample(ACTORS, rng.randint(1, 3))
    doc = {"warrant_policy": "0.3", "threshold": {"min_sigs": rng.randint(1, len(actors)),
                                                  "actors": actors}}
    if r < 0.85:
        return s.jblob(doc)
    bad = rng.choice(["zero", "dup", "noncanon", "extra", "float"])
    if bad == "zero":
        doc["threshold"]["min_sigs"] = 0
    elif bad == "dup":
        doc["threshold"]["actors"] = [actors[0], actors[0]]
    elif bad == "extra":
        doc["x"] = 1
    elif bad == "float":
        return s.blob(b'{"threshold":{"actors":["a@x"],"min_sigs":1.0},"warrant_policy":"0.3"}')
    else:
        return s.blob(json.dumps(doc).encode())
    return s.jblob(doc)


def body(s, rng, decision, subject, prior, ts):
    b = {"warrant": "0.2", "decision": decision, "subject": {"hash": subject},
         "under": [policy(s, rng) for _ in range(rng.randint(1, 2))],
         "because": [reason(s, rng) for _ in range(rng.randint(0, 2))],
         "evidence": [s.blob(os.urandom(4)) if rng.random() < 0.5
                      else rng.choice(s.blobs or [s.blob(b"e")])
                      for _ in range(rng.randint(0, 2))],
         "actor": {"id": rng.choice(ACTORS)}, "prior": list(prior), "ts": ts}
    if decision in ("reject", "supersede") and not b["because"]:
        b["because"].append({"kind": "prose", "text": "required"})
    if rng.random() < 0.15:
        b["subject"]["note"] = rng.choice(["n", "x" * 201, "ünïcode"])
    return b


def signers_for(s, rng, b):
    actor = b["actor"]["id"]
    out = [(actor, rng.choice([actor, actor, actor, "rot-" + actor]))]
    for a in ACTORS:
        if a != actor and rng.random() < 0.5:
            out.append((a, a))
    return out


def hostile(s, rng):
    """A record file the reference must survive."""
    choice = rng.choice(["float", "dup", "deep", "bom", "notobj", "nobody", "listactor",
                         "legacy", "junksig", "surrogate", "trailing", "under-int",
                         "ski-nocheck", "prior-int", "hexnl", "bigint", "nonlist-sigs"])
    sub = s.blob(b"hostile subject")
    pol = s.blob(b"policy one\n")
    b = {"warrant": "0.2", "decision": "propose", "subject": {"hash": sub}, "under": [pol],
         "because": [], "evidence": [], "actor": {"id": "a@x"}, "prior": [], "ts": 5}
    rid = hashlib.sha256(choice.encode() + os.urandom(4)).hexdigest()
    rec = s.st.records / f"{rid}.json"
    if choice == "float":
        b["ts"] = 1.5
        rec.write_text(json.dumps({"body": b, "sigs": []}))
    elif choice == "dup":
        rec.write_text('{"body": %s, "body": {}, "sigs": []}' % json.dumps(b))
    elif choice == "deep":
        n = rng.choice([510, 511, 512, 513, 600])
        rec.write_text('{"body":{"a":' + "[" * n + "]" * n + '},"sigs":[]}')
    elif choice == "bom":
        rec.write_bytes(b"\xef\xbb\xbf" + json.dumps({"body": b, "sigs": []}).encode())
    elif choice == "notobj":
        rec.write_text("[1, 2]")
    elif choice == "nobody":
        rec.write_text('{"sigs": []}')
    elif choice == "surrogate":
        rec.write_text('{"body": {"a": "\\ud800"}, "sigs": []}')
    elif choice == "trailing":
        rec.write_text(json.dumps({"body": b, "sigs": []}) + " x")
    elif choice == "hexnl":
        b["subject"]["hash"] = sub + "\n"
        return s.record(b, [("a@x", "a@x")])
    elif choice == "bigint":
        b["ts"] = 10 ** 40
        return s.record(b, [("a@x", "a@x")])
    elif choice == "under-int":
        b["under"] = [5]
        rec.write_text(json.dumps({"body": b, "sigs": []}))
    elif choice == "prior-int":
        b["prior"] = 5
        rec.write_text(json.dumps({"body": b, "sigs": []}))
    elif choice == "ski-nocheck":
        b["because"] = [{"kind": "check", "runtime": "ski@v1", "verdict": "pass"}]
        return s.record(b, [("a@x", "a@x")])
    elif choice == "nonlist-sigs":
        rec.write_text(json.dumps({"body": b, "sigs": {"a": 1}}))
    else:
        wid = W.warrant_id(b)
        good = W.sign_envelope(b, "a@x", s.key("a@x"))
        if choice == "listactor":
            sigs = [good, dict(good, actor=["a@x"])]
        elif choice == "legacy":
            sk = W.load_key(s.key("a@x"))
            sigs = [{"actor": "a@x", "key": good["key"], "sig": sk.sign(bytes.fromhex(wid)).hex()}]
        else:
            sigs = [good, "junk", {"actor": "b@x", "key": good["key"], "sig": "00" * 64}]
        return s.write({"body": b, "sigs": sigs})
    s.wids.append(rid)
    return rid


def odd_blobs(s, rng):
    """Blobs only a lenient reader parses: UTF-16, BOM'd, duplicate names."""
    doc = {"warrant_policy": "0.3", "threshold": {"min_sigs": 1, "actors": ["a@x"]}}
    text = json.dumps(doc, separators=(",", ":"), sort_keys=True)
    return [s.blob(b"\xff\xfe" + text.encode("utf-16-le")),
            s.blob(b"\xef\xbb\xbf" + text.encode()),
            s.blob(text.replace('"min_sigs":1', '"min_sigs":1,"min_sigs":1').encode())]


def build(root, rng):
    s = Store(root, rng)
    ts = rng.randint(1, 100)
    roots = []
    for _ in range(rng.randint(1, 3)):
        b = body(s, rng, rng.choice(["propose", "accept"]), s.blob(os.urandom(6)), [], ts)
        roots.append(s.record(b, signers_for(s, rng, b)))
        ts += rng.randint(-1, 3)
    live = list(roots)
    weird = odd_blobs(s, rng)
    for _ in range(rng.randint(2, 9)):
        r = rng.random()
        prior = rng.sample(live, min(len(live), rng.randint(1, 2)))
        ts += rng.randint(-2, 4)
        if r < 0.12:      # adopt another root under a threshold
            target = rng.choice(roots)
            b = body(s, rng, "accept", target, prior, ts)
            if rng.random() < 0.3:
                b["under"].append(rng.choice(weird))
        elif r < 0.25:    # key rotation: accept of an {actor, key} blob
            actor = rng.choice(ACTORS)
            new = rng.choice(["rot-" + actor, actor + "-fork"])
            kb = s.jblob({"actor": actor, "key": s.pub(new)})
            b = body(s, rng, "accept", kb, prior, ts)
            b["actor"]["id"] = actor
            sig = [(actor, actor), (actor, new)] + [(a, a) for a in ACTORS if a != actor and rng.random() < 0.6]
            live.append(s.record(b, sig))
            continue
        elif r < 0.45:    # re-litigate: same subject as an earlier decision
            try:
                pb = json.loads((s.st.records / f"{prior[0]}.json").read_text())["body"]
                subj, ev, bc = pb["subject"]["hash"], list(pb["evidence"]), list(pb["because"])
            except Exception:          # a hostile prior: nothing to re-litigate
                subj, ev, bc = s.blob(os.urandom(5)), [], []
            b = body(s, rng, rng.choice(["accept", "reject"]), subj, prior, ts)
            if rng.random() < 0.5:
                b["evidence"] = ev
                b["because"] = bc or [{"kind": "prose", "text": "again"}]
        elif r < 0.55:    # supersede
            b = body(s, rng, "supersede", rng.choice(live), prior, ts)
        elif r < 0.65:
            live.append(hostile(s, rng))
            continue
        else:
            b = body(s, rng, rng.choice(["propose", "accept", "reject"]), s.blob(os.urandom(5)), prior, ts)
        live.append(s.record(b, signers_for(s, rng, b)))
    if rng.random() < 0.3:
        doc = json.dumps({"roots": rng.sample(s.wids, min(2, len(s.wids)))}).encode()
        (s.root / "genesis.json").write_bytes(doc)
        gh = hashlib.sha256(doc).hexdigest() if rng.random() < 0.7 else "0" * 64
    else:
        gh = None
    trust = {}
    if rng.random() < 0.9:
        trust["genesis_roots"] = rng.sample(roots, rng.randint(0, len(roots)))
    if rng.random() < 0.9:
        trust["actors"] = {a: [s.pub(a)] for a in ACTORS if rng.random() < 0.8}
    if gh:
        trust["genesis_json_sha256"] = gh
    tpath = s.root.parent / "trust.json"
    tpath.write_text(json.dumps(trust) if rng.random() > 0.04 else rng.choice(
        ['{"genesis_roots": null}', '{"x": 1}', '[]', '{"actors": {"": []}}', 'nope']))
    if rng.random() < 0.15:     # a blob that lies about its address
        victim = s.st.blobs / rng.choice(s.blobs)
        victim.write_bytes(b"swapped bytes")
    return s, str(tpath)


# Report lines the fuzzed stores MUST reach for a green run to mean anything: a
# parity claim over branches no case entered is the label outrunning the test.
COVERAGE = [
    "unadopted root", "signature bound", "signature unbound", "key-state conflict",
    "re-litigation cites nothing new", "invalid threshold policy",
    "ski@v1 verdict mismatch", "ski@v1 unverified", "genesis.json unverified",
    "settlement trust config unavailable", "unloadable record",
    "LEGACY pre-v1 signature", "nesting too deep", "content does not match its address",
    "admissible: (a) new evidence", "admissible: (b) new outcome fingerprint",
    "inadmissible: cites nothing new", "invalid candidate", "[VERIFY FAILED]",
    "UNVERIFIABLE", "supersede subject MUST", "ts decreases along prior edge",
    "WarrantID mismatch", "WarrantID uncomputable", "binding unverified", "pass  result=",
    "fail  result=", "signature entry is not an object", "is outside the §2 domain",
]
SEEN = Counter()


def compare(label, args, tally, mism, inp=None):
    py = subprocess.run(PY + args, capture_output=True, env=ENV, input=inp)
    rs = subprocess.run([str(RS)] + args, capture_output=True, env=ENV, input=inp)
    tally[label] += 1
    text = py.stdout.decode("utf-8", "replace") + py.stderr.decode("utf-8", "replace")
    for needle in COVERAGE:
        if needle in text:
            SEEN[needle] += 1
    if py.stdout != rs.stdout or py.returncode != rs.returncode:
        mism.append({"label": label, "args": args, "py_code": py.returncode,
                     "rs_code": rs.returncode,
                     "py": py.stdout.decode("utf-8", "replace")[-3000:],
                     "rs": rs.stdout.decode("utf-8", "replace")[-3000:],
                     "py_err": py.stderr.decode("utf-8", "replace")[-1500:],
                     "rs_err": rs.stderr.decode("utf-8", "replace")[-1500:]})


def fuzz(n, seed, tally, mism, keep):
    rng = random.Random(seed)
    for i in range(n):
        tmp = tempfile.mkdtemp(prefix="rs-parity-")
        try:
            s, trust = build(Path(tmp, "s"), rng)
            st = str(s.root)
            for extra in ([], ["--settlement", "--trust-config", trust]):
                compare("verify", ["--store", st, "verify"] + extra, tally, mism)
                compare("verify --json", ["--store", st, "verify", "--json"] + extra, tally, mism)
            g = rng.sample(s.wids, min(1, len(s.wids)))
            compare("verify --genesis", ["--store", st, "verify", "--settlement"]
                    + sum((["--genesis", x] for x in g), []), tally, mism)
            for wid in s.wids + ["f" * 64]:
                compare("why", ["--store", st, "why", wid], tally, mism)
            for _ in range(3):
                settling = rng.choice(s.wids)
                cand = rng.choice(s.wids)
                p = Path(tmp, "cand.json")
                try:
                    p.write_text(json.dumps(json.loads(
                        (s.st.records / f"{cand}.json").read_text())["body"]))
                except Exception:
                    p.write_text("{}")
                compare("settle", ["--store", st, "settle", settling, str(p)], tally, mism)
            for h in sorted(set(s.blobs)):
                raw = (s.st.blobs / h).read_bytes()
                if raw.startswith(b"{") and b'"ski"' in raw:
                    compare("check", ["--store", st, "check", h], tally, mism)
        finally:
            if keep and mism:
                print(f"kept failing store: {tmp}")
            else:
                shutil.rmtree(tmp, ignore_errors=True)
        if keep and mism:
            return


def writers(tally, mism):
    """Filing and re-signing, on twin stores: the bytes written must match."""
    tmp = tempfile.mkdtemp(prefix="rs-parity-w-")
    try:
        k = Path(tmp, "k.key")
        k.write_text("11" * 32 + "\n")
        pol = Path(tmp, "policy.txt")
        pol.write_text("POLICY\n")
        subj = Path(tmp, "subject.txt")
        subj.write_text("SUBJECT\n")
        trees = {}
        for who, cmd in (("py", PY), ("rs", [str(RS)])):
            st = str(Path(tmp, who))
            outs = []

            def go(*a):
                r = subprocess.run(cmd + ["--store", st] + list(a), capture_output=True, env=ENV)
                outs.append((r.returncode, r.stdout.replace(st.encode(), b"<store>")))
                return r.stdout.decode().strip()
            go("init")
            go("blob", "add", str(pol))
            w1 = go("propose", "--subject", str(subj), "--under", str(pol), "--reason", "r",
                    "--note", "first", "--actor", "a@x", "--key", str(k), "--ts", "100")
            w2 = go("accept", w1, "--reason", "fine", "--actor", "a@x", "--key", str(k),
                    "--ts", "101", "--check", str(pol), "--transcript", str(subj))
            w3 = go("reject", w2, "--reason", "no", "--actor", "b@x", "--key", str(k), "--ts", "99")
            go("supersede", w3, "--reason", "replaced", "--actor", "a@x", "--key", str(k), "--ts", "102")
            go("accept", "--subject", str(subj), "--under", str(pol), "--actor", "a@x",
               "--key", str(k), "--ts", "103", "--relitigates", w2)
            go("propose", "--subject", "nope-not-a-file", "--under", str(pol), "--actor", "a@x",
               "--key", str(k))
            go("verify")
            go("why", w3)
            # A legacy (pre-v1) record, then the migration.
            body = {"warrant": "0.2", "decision": "propose", "subject": {"hash": "a" * 64},
                    "under": ["b" * 64], "because": [], "evidence": [], "actor": {"id": "a@x"},
                    "prior": [], "ts": 7}
            wid = W.warrant_id(body)
            sk = W.load_key(str(k))
            env = {"body": body, "sigs": [{"actor": "a@x", "key": W.pubkey_hex(sk),
                                           "sig": sk.sign(bytes.fromhex(wid)).hex()}]}
            Path(st, "records", f"{wid}.json").write_text(json.dumps(env, indent=2, sort_keys=True) + "\n")
            go("resign", "--key", str(k), "--dry-run")
            go("resign", "--key", str(k))
            go("verify", "--json")
            trees[who] = ({str(p.relative_to(st)): p.read_bytes()
                           for p in sorted(Path(st).rglob("*")) if p.is_file()}, outs)
        tally["writers"] += 1
        (pt, po), (rt, ro) = trees["py"], trees["rs"]
        if pt != rt or po != ro:
            diff = sorted(x for x in set(pt) | set(rt) if pt.get(x) != rt.get(x))
            mism.append({"label": "writers", "files": diff,
                         "outs": [(a[0], a[1].decode("utf-8", "replace"), b[0], b[1].decode("utf-8", "replace")) for a, b in zip(po, ro) if a != b][:3]})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def probes(tally, mism):
    """Every conformance-pack request, asked of both: identical response bytes
    (the `capabilities` answer names the implementation, so it alone differs)."""
    sys.path.insert(0, str(ROOT / "conformance"))
    import run as pack_runner
    pack = ROOT / "conformance"
    with tempfile.TemporaryDirectory() as tmp:
        for doc in pack_runner.load_vectors(pack)[1]:
            for v in doc["vectors"]:
                req = {"warrant_conformance": "1", "id": v["id"], "class": doc["class"],
                       "input": pack_runner.materialize(v, Path(tmp), pack)}
                raw = json.dumps(req).encode()
                compare("probe", ["probe"], tally, mism, inp=raw)
                for d in Path(tmp).iterdir():
                    shutil.rmtree(d, ignore_errors=True)
        for raw in (b'{"warrant_conformance":"1","id":7,"class":"nope","input":{}}',
                    b'{"warrant_conformance":"1","id":null,"class":"parse",'
                    b'"input":{"bytes_base64":"' + __import__("base64").b64encode(
                        b"[" * 513 + b"]" * 513) + b'"}}',
                    b'{"warrant_conformance":"1","id":"u","class":"canon",'
                    b'"input":{"body":{"a":"\\ud800","b":1.5}}}'):
            compare("probe", ["probe"], tally, mism, inp=raw)


SEEDS = [b'{"a":[1,2,{"b":null}],"c":"x\\u00e9\\ud83d\\ude00","d":-0,"e":1.5e3}',
         b'[true,false,null,"\\"\\\\\\/\\b\\f\\n\\r\\t",0,-1,10]',
         b'{"warrant":"0.2","decision":"propose","ts":1}', b'"\\ud800\\udc00"',
         "{\"k\u00e9\":\"\u2028\"}".encode(), b'  [ ] ', b'{"a":{"a":{}}}',
         b'{"k\\ud800":[1.5,"\\udc00"],"\\udbff":{"x":"\\ud800\\ud801"}}']
ALPHABET = list(b'{}[]",:\\ -0123456789.eEtrufalsnNI\n\t\rx') + [0x00, 0x1f, 0x7f, 0xc3, 0xa9,
                                                                      0xed, 0xa0, 0x80, 0xff, 0xef, 0xbb, 0xbf]


def mutate(rng, b):
    b = bytearray(b)
    for _ in range(rng.randint(1, 4)):
        op = rng.random()
        pos = rng.randint(0, len(b))
        if op < 0.35 and b:
            del b[min(pos, len(b) - 1)]
        elif op < 0.7:
            b.insert(pos, rng.choice(ALPHABET))
        elif op < 0.85 and b:
            b[min(pos, len(b) - 1)] = rng.choice(ALPHABET)
        else:
            frag = rng.choice([b'\\u', b'\\ud800', b'\\udc00', b'NaN', b'-Infinity', b',', b'"a":1,',
                               b'1' * rng.choice([5, 4300, 4301]), b'[' * 513, b'"', b'\\'])
            b[pos:pos] = frag
    return bytes(b)


def parse_fuzz(n, seed, tally, mism):
    """Random near-JSON through the probe's I-JSON parser, and random bodies
    through canon and validate: identical answers, error texts included."""
    import base64
    rng = random.Random(seed ^ 0x5eed)
    for _ in range(n):
        raw = mutate(rng, rng.choice(SEEDS))
        req = {"warrant_conformance": "1", "id": "f", "class": "parse",
               "input": {"bytes_base64": base64.b64encode(raw).decode()}}
        compare("parse-fuzz", ["probe"], tally, mism, inp=json.dumps(req).encode())
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        for cls in ("canon", "validate"):
            body = doc if cls == "canon" or rng.random() < 0.5 else {
                "warrant": "0.2", "decision": "propose", "subject": {"hash": "a" * 64},
                "under": ["b" * 64], "because": [doc] if rng.random() < 0.5 else [],
                "evidence": [], "actor": {"id": doc if rng.random() < 0.3 else "x"},
                "prior": [], "ts": doc if rng.random() < 0.3 else 1}
            try:
                payload = json.dumps({"warrant_conformance": "1", "id": "f", "class": cls,
                                      "input": {"body": body}}).encode()
            except Exception:
                continue
            compare(f"{cls}-fuzz", ["probe"], tally, mism, inp=payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stores", type=int, default=150)
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--no-shadow", action="store_true")
    ap.add_argument("--keep", action="store_true", help="stop at, and keep, the first failing store")
    ap.add_argument("--parse", type=int, default=None,
                    help="near-JSON cases through the probe (default: 4 per store, at least 200)")
    args = ap.parse_args()
    if not RS.is_file():
        print(f"FAIL  warrant-rs not built at {RS} (cd impl-rs && cargo build --release)")
        return 1
    if sys.version_info < (3, 13):
        # The reference's parse-error TEXT is its interpreter's: 3.13 changed
        # "Expecting value" to "Illegal trailing comma ..." for `[1,]`, and the
        # Rust implementation reproduces the current wording. Comparing against
        # an older interpreter would report its wording as a Rust divergence.
        print(f"UNRUN rs-parity needs Python >= 3.13 (this is {sys.version.split()[0]})")
        return 2
    ok = True
    # The crate's own copies of the SPEC §8 vectors (so `cargo test` runs from
    # the published package) must be the vectors, byte for byte.
    vec_dir = ROOT / "impl-rs" / "tests" / "vectors"
    copies = sorted(p.relative_to(vec_dir) for p in vec_dir.rglob("*") if p.is_file())
    for rel in copies:
        if (vec_dir / rel).read_bytes() != (ROOT / "examples" / rel).read_bytes():
            ok = False
            print(f"FAIL  impl-rs/tests/vectors/{rel} differs from examples/{rel}")
    if len(copies) < 10:
        ok = False
        print(f"FAIL  impl-rs/tests/vectors holds {len(copies)} files; expected the 10 §8 vectors")
    tally, mism = Counter(), []
    with tempfile.TemporaryDirectory() as tmp:
        if not args.no_shadow:
            if not negative_control(tmp):
                print("FAIL  negative control: the shadow did not see a deliberate output change")
                return 1
            print("OK    negative control: a one-byte output change is reported")
            log = Path(tmp, "shadow.jsonl")
            for h in HARNESSES:
                r = run_shadowed([str(ROOT / "tests" / h[0])] + h[1:], log)
                if r.returncode != 0:
                    ok = False
                    print(f"FAIL  harness {h[0]} itself failed under the shadow (exit {r.returncode})")
            rows = read_log(log)
            for r in rows:
                tally[f"shadow:{r['cmd']}"] += 1
                if bad(r):
                    mism.append({"label": f"shadow:{r['cmd']}", **r})
    writers(tally, mism)
    probes(tally, mism)
    parse_fuzz(args.parse if args.parse is not None else max(200, args.stores * 4),
               args.seed, tally, mism)
    fuzz(args.stores, args.seed, tally, mism, args.keep)

    for m in mism[:8]:
        print("MISMATCH", json.dumps(m, ensure_ascii=False)[:3000])
    need = ["verify", "verify --json", "why", "settle", "check", "writers", "probe",
            "parse-fuzz", "canon-fuzz", "validate-fuzz"]
    if not args.no_shadow:
        need += ["shadow:verify", "shadow:canon", "shadow:why", "shadow:settle", "shadow:resign",
                 "shadow:accept", "shadow:supersede", "shadow:init", "shadow:blob"]
    for k in need:
        if tally[k] == 0:
            ok = False
            print(f"FAIL  no '{k}' comparison happened: the run cannot vouch for it")
    missing = [n for n in COVERAGE if not SEEN[n]]
    print("coverage:", ", ".join(f"{n!r}={SEEN[n]}" for n in COVERAGE))
    if missing and args.stores >= 100:
        ok = False
        print(f"FAIL  fuzzed stores never reached: {missing}")
    total = sum(tally.values())
    print("compared:", ", ".join(f"{k}={v}" for k, v in sorted(tally.items())))
    ok = ok and not mism
    print(f"\nRS-PARITY: {'ALL IDENTICAL' if ok else 'DIVERGENCE'} "
          f"({total - len(mism)}/{total} byte-identical)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
