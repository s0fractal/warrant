#!/usr/bin/env python3
"""Eleven defects of the reference implementation, found by porting it.

Bringing impl-rs to byte parity with impl/warrant.py meant reading every branch
of the reference closely enough to reproduce it — including the branches that
crash. Each case below is a hostile but writable store (anyone with store write
access can produce it) on which the reference, before 2026-10-09, either:

  * raised an uncaught exception, taking the whole verifier down with one
    record (F2–F4, F6–F11): an availability defect, and an observable split
    from Go, which reported; or
  * reached a different VALIDITY verdict from Go (F1, F5): the consensus split
    this project ranks highest.

WHAT IS ASSERTED, PER CASE
  1. No implementation prints a traceback.
  2. Python and Rust give byte-identical stdout and the same exit status.
  3. Where Go has the command (verify), all three agree on (records, errors,
     warnings) — at the grade the case is about.
  4. The case still exercises its defect: each names the report line it must
     produce, so a refactor that stops reaching the branch fails here instead of
     passing vacuously.

The fixes are in impl/warrant.py (and an explicit nesting bound in impl-go);
the Rust implementation was written to the fixed semantics. See CHANGELOG.
"""
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = [sys.executable, str(ROOT / "impl" / "warrant.py")]
GO = ROOT / "impl-go" / "warrant-go"
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"
ENV = {k: v for k, v in os.environ.items()
       if k not in ("SIGMA_GLYPH", "WARRANT_SIGMA_DIFFERENTIAL", "WARRANT_SKI_MAX_ATP")}
I_H = "2f33694d09810641fa5b8c47a7c0dc42e1b99eb8c9784a00aaee9a66330f4162"

spec = importlib.util.spec_from_file_location("warrant_ref", ROOT / "impl" / "warrant.py")
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)

SUMMARY = re.compile(r"verify: (\d+) records, (\d+) errors, (\d+) warnings")


def key(tmp, b):
    p = Path(tmp, f"k{b}.key")
    p.write_text((bytes([b]) * 32).hex())
    return str(p)


def body(dec, subj, under, actor="a@x", prior=(), because=(), ts=1):
    return {"warrant": "0.2", "decision": dec, "subject": {"hash": subj},
            "under": list(under), "because": list(because), "evidence": [],
            "actor": {"id": actor}, "prior": list(prior), "ts": ts}


def rec(st, b, k, actor="a@x"):
    return W.Store(st).put_record({"body": b, "sigs": [W.sign_envelope(b, actor, k)]})


def raw_rec(st, name, env):
    Path(st, "records", name + ".json").write_text(json.dumps(env))


def trust(tmp, doc):
    p = Path(tmp, "trust.json")
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return str(p)


# Each builder returns (rs_args, go_args or None, needle): the reference CLI
# arguments, Go's equivalent for a three-way count check, and a line the
# reference's output must contain.

def f1(tmp, st):
    pol = W.Store(st).put_blob(b"p")
    rec(st, body("propose", "a" * 64 + "\n", [pol]), key(tmp, 1))
    return ["--store", st, "verify"], ["verify", st], "subject.hash must be hex64"


def f2(tmp, st):
    s = W.Store(st)
    ch = s.put_blob(b'{"atp":1.5,"expect":"' + b"a" * 64 + b'","ski":1,"term":"' + b"b" * 64 + b'"}')
    pol = s.put_blob(b"p")
    rec(st, body("propose", pol, [pol], because=[{"kind": "check", "check": ch,
                                                  "runtime": "ski@v1", "verdict": "pass"}]), key(tmp, 1))
    return ["--store", st, "verify"], None, "ski@v1 unverified: malformed check blob (not JCS-canonical)"


def f2b(tmp, st):
    s = W.Store(st)
    pol = s.put_blob(b'{"threshold":{"actors":["a@x"],"min_sigs":1.0},"warrant_policy":"0.3"}')
    rec(st, body("propose", pol, [pol]), key(tmp, 1))
    t = trust(tmp, {})
    return (["--store", st, "verify", "--settlement", "--trust-config", t],
            ["verify", "--settlement", "--trust-config", t, st], "invalid threshold policy")


def f3(tmp, st):
    n = 600
    Path(st, "records", "x.json").write_text('{"body":{"a":' + "[" * n + "]" * n + '},"sigs":[]}')
    return (["--store", st, "verify"], ["verify", st],
            "unloadable record: malformed JSON (nesting too deep)")


def f4(tmp, st):
    t = trust(tmp, '{"genesis_roots": null}')
    return (["--store", st, "verify", "--settlement", "--trust-config", t],
            ["verify", "--settlement", "--trust-config", t, st], "settlement trust config unavailable")


def f5(tmp, st):
    ch = W.Store(st).put_blob(W.canon({"ski": True, "term": I_H, "atp": 5, "expect": I_H}))
    return ["--store", st, "check", ch], None, None


def f6(tmp, st):
    s = W.Store(st)
    ghost = hashlib.sha256(b"ghost").digest()
    term = s.put_blob(bytes([2, 6]) + bytes.fromhex(I_H) + ghost)
    os.mkdir(Path(st, "blobs", ghost.hex()))
    ch = s.put_blob(W.canon({"ski": 1, "term": term, "atp": 50, "expect": I_H}))
    return ["--store", st, "check", ch], None, "fail  result="


def f7(tmp, st):
    k = key(tmp, 1)
    s = W.Store(st)
    pol, subj = s.put_blob(b"p"), s.put_blob(b"subject")
    r = rec(st, body("propose", subj, [pol], ts=1), k)
    # A malformed record under a valid name, cited as a prior by an ACTIVE
    # accept: the re-litigation check walks its tunnel, through the bad body.
    raw_rec(st, "e" * 64, {"body": {"prior": 5, "decision": "accept"}, "sigs": []})
    a1 = rec(st, body("accept", subj, [pol], prior=[r, "e" * 64],
                      because=[{"kind": "prose", "text": "x"}], ts=2), k)
    rec(st, body("accept", subj, [pol], prior=[a1], because=[{"kind": "prose", "text": "x"}], ts=3), k)
    t = trust(tmp, {"genesis_roots": [r]})
    return (["--store", st, "verify", "--settlement", "--trust-config", t],
            ["verify", "--settlement", "--trust-config", t, st], "re-litigation cites nothing new")


def f8(tmp, st):
    k = key(tmp, 1)
    pol = W.Store(st).put_blob(b"p")
    b = body("propose", pol, [pol])
    sig = W.sign_envelope(b, "a@x", k)
    W.Store(st).put_record({"body": b, "sigs": [sig, dict(sig, actor=["a@x"])]})
    t = trust(tmp, {})
    return (["--store", st, "verify", "--settlement", "--trust-config", t],
            ["verify", "--settlement", "--trust-config", t, st], "claims actor ['a@x']")


def f9(tmp, st):
    pol = W.Store(st).put_blob(b"p")
    rec(st, body("propose", pol, [pol], because=[{"kind": "check", "runtime": "ski@v1",
                                                  "verdict": "pass"}]), key(tmp, 1))
    return ["--store", st, "verify"], None, "ski@v1 unverified: check blob missing"


def f10(tmp, st):
    b = body("propose", "a" * 64, ["b" * 64])
    b["ts"] = 1.5
    raw_rec(st, "c" * 64, {"body": b, "sigs": []})
    return ["--store", st, "why", "c" * 64], None, "[VERIFY FAILED]"


def f11(tmp, st):
    pol = W.Store(st).put_blob(b"p")
    raw_rec(st, "d" * 64, {"body": body("propose", pol, [5]), "sigs": []})
    t = trust(tmp, {})
    return (["--store", st, "verify", "--settlement", "--trust-config", t],
            ["verify", "--settlement", "--trust-config", t, st], "under must be a list of >=1 hex64")


CASES = [
    ("F1 hex64 with a trailing newline is not hex64 (validity split vs Go)", f1),
    ("F2 a float in a ski@v1 check blob", f2),
    ("F2b a float in a threshold policy blob (settlement)", f2b),
    ("F3 nesting depth 600 in a record (stack-dependent before)", f3),
    ("F4 a trust config member that is null", f4),
    ("F5 \"ski\": true is not a v1 check blob (validity split vs Go)", f5),
    ("F6 a directory at a term child's address", f6),
    ("F7 a malformed ancestor reached by the re-litigation check", f7),
    ("F8 a valid signature whose actor is a list (settlement)", f8),
    ("F9 a ski@v1 reason with no check member", f9),
    ("F10 why on a record with no computable WarrantID", f10),
    ("F11 an integer in under (settlement)", f11),
]


def run(argv):
    return subprocess.run(argv, capture_output=True, text=True, env=ENV)


def main():
    for name, path in (("warrant-go", GO), ("warrant-rs", RS)):
        if not path.is_file():
            print(f"SKIP  reference defects: {name} not built ({path})")
            return 0
    ok = True
    for title, build in CASES:
        tmp = tempfile.mkdtemp(prefix="refdef-")
        try:
            st = str(Path(tmp, "s"))
            W.Store(st).init()
            args, go_args, needle = build(tmp, st)
            py, rs = run(PY + args), run([str(RS)] + args)
            problems = []
            for who, r in (("py", py), ("rs", rs)):
                if "Traceback" in r.stderr or "panicked" in r.stderr:
                    problems.append(f"{who} crashed: {r.stderr.strip().splitlines()[-1]}")
            if py.stdout != rs.stdout or py.returncode != rs.returncode:
                problems.append(f"py/rs differ (exit {py.returncode}/{rs.returncode})")
            if needle and needle not in py.stdout:
                problems.append(f"no longer reaches its branch (expected {needle!r})")
            if title.startswith("F5") and py.returncode == 0:
                problems.append("a ski:true blob was executed as a v1 check")
            if go_args:
                go = run([str(GO)] + go_args)
                if "panic" in go.stderr:
                    problems.append("go panicked")
                pc, gc = SUMMARY.search(py.stdout), SUMMARY.search(go.stdout)
                if not (pc and gc and pc.groups() == gc.groups()):
                    problems.append(f"py/go counts differ: {pc and pc.groups()} vs {gc and gc.groups()}")
            print(("OK   " if not problems else "FAIL "), title, "; ".join(problems))
            ok &= not problems
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nREFERENCE DEFECTS 2026-10: {'ALL FIXED, PY=RS(=GO)' if ok else 'REGRESSION'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
