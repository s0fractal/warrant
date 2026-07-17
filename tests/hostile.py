#!/usr/bin/env python3
"""Hostile-store hardening regression (Codex v0.3 runtime hardening audit).

A malformed or adversarial `.warrants` store MUST produce a bounded report,
never a traceback / panic / unbounded recursion, and Python and Go MUST agree
on the error/warning counts. Also: an unverifiable `ski@v1` claim MUST surface
(WARN in base verification, never a silent skip).

Stdlib only. Go binary built on demand.
"""
import hashlib, json, os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = [sys.executable, str(ROOT / "impl" / "warrant.py")]
GO = ROOT / "impl-go" / "warrant-go"
Z = "0" * 64
GEN = "a" * 64
ok = []


def chk(name, cond):
    ok.append(cond)
    print(("OK  " if cond else "FAIL") + "  " + name)


def canon(b):
    return json.dumps(b, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode()


def wid_of(body):
    return hashlib.sha256(canon(body)).hexdigest()


def base(**kw):
    b = {"warrant": "0.2", "decision": "propose", "subject": {"hash": Z},
         "under": [Z], "because": [], "evidence": [], "actor": {"id": "x"},
         "prior": [], "ts": 1}
    b.update(kw)
    return b


def write_store(tmp, records):
    (tmp / "records").mkdir(parents=True)
    (tmp / "blobs").mkdir(parents=True)
    for wid, env in records.items():
        (tmp / "records" / f"{wid}.json").write_text(json.dumps(env))
    return tmp


def parse_counts(text):
    m = re.search(r"verify: (\d+) records, (\d+) errors, (\d+) warnings", text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def run(cmd, cwd=None):
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=120)


def verify_py(store, settlement=False):
    args = PY + ["--store", str(store), "verify"]
    if settlement:
        args += ["--settlement", "--genesis", GEN]
    return run(args)


def verify_go(store, settlement=False):
    args = [str(GO), "verify"]
    if settlement:
        args += ["--settlement", "--genesis", GEN]
    return run(args + [str(store)])


def agree(name, store, settlement=False):
    """Neither impl crashes; both emit a bounded report with equal counts."""
    rp, rg = verify_py(store, settlement), verify_go(store, settlement)
    cp, cg = parse_counts(rp.stdout), parse_counts(rg.stdout)
    no_crash = "Traceback" not in rp.stderr and "goroutine" not in rg.stderr
    chk(f"{name}: no crash (py+go bounded report)", no_crash and cp is not None and cg is not None)
    chk(f"{name}: py/go agree on counts {cp} == {cg}", cp == cg)


def main():
    if not GO.exists():
        b = run(["go", "build", "-o", "warrant-go", "."], cwd=ROOT / "impl-go")
        if b.returncode != 0:
            b = run(["env", f"GOCACHE={ROOT/'impl-go'/'.gocache'}", "go", "build",
                     "-o", "warrant-go", "."], cwd=ROOT / "impl-go")
        assert GO.exists(), "warrant-go build failed"

    with tempfile.TemporaryDirectory() as td:
        # two-record prior cycle
        a, b = "a" * 64, "b" * 64
        s = write_store(Path(td) / "cycle2",
                        {a: {"body": base(prior=[b]), "sigs": []},
                         b: {"body": base(prior=[a]), "sigs": []}})
        agree("two-record cycle", s, settlement=True)

        # self-cycle
        s = write_store(Path(td) / "selfcycle",
                        {a: {"body": base(prior=[a]), "sigs": []}})
        agree("self-cycle", s, settlement=True)

        # long acyclic chain beyond ordinary recursion depth
        recs, prev = {}, None
        for _ in range(3000):
            body = base(prior=[prev] if prev else [])
            w = wid_of(body)
            recs[w] = {"body": body, "sigs": []}
            prev = w
        s = write_store(Path(td) / "deep", recs)
        agree("3000-deep acyclic chain", s)

        # cycle PLUS an unrelated well-formed root — verification must continue
        c = "c" * 64
        genb = base()
        genw = wid_of(genb)
        recs = {a: {"body": base(prior=[b]), "sigs": []},
                b: {"body": base(prior=[a]), "sigs": []},
                genw: {"body": genb, "sigs": []}}
        s = write_store(Path(td) / "cycleplus", recs)
        rp = verify_py(s)
        chk("cycle+valid: verification continues over all 3 records",
            parse_counts(rp.stdout) is not None and parse_counts(rp.stdout)[0] == 3)
        agree("cycle+valid", s)

        # malformed JSON record — bounded ERR, not a traceback
        s = Path(td) / "badjson"
        (s / "records").mkdir(parents=True)
        (s / "blobs").mkdir(parents=True)
        (s / "records" / (c + ".json")).write_text("{broken")
        rp, rg = verify_py(s), verify_go(s)
        chk("malformed JSON: py bounded ERR (no traceback)",
            "Traceback" not in rp.stderr and parse_counts(rp.stdout) is not None
            and parse_counts(rp.stdout)[1] >= 1)
        chk("malformed JSON: go bounded (no panic)",
            "goroutine" not in rg.stderr and parse_counts(rg.stdout) is not None)

        # ski@v1 whose check blob is absent -> base verify WARNs, never silent,
        # and PY/GO MUST agree (Kimi K3 review: Go used to `continue` silently,
        # leaving PY at N warnings and GO at N-1 — a real cross-impl split).
        ski_reason = {"kind": "check", "check": "d" * 64, "runtime": "ski@v1",
                      "verdict": "pass"}
        body = base(decision="accept", because=[ski_reason])
        w = wid_of(body)
        s = write_store(Path(td) / "skimissing", {w: {"body": body, "sigs": []}})
        rp, rg = verify_py(s), verify_go(s)
        chk("ski@v1 missing check blob: base verify surfaces it (not silent)",
            "ski@v1 unverified" in rp.stdout and "ski@v1 unverified" in rg.stdout)
        agree("ski@v1 missing check blob", s)

        # ski@v1 whose atp exceeds the re-execution budget -> reported unverified
        # (a WARN), never evaluated, never a hang (Kimi K3 review: uint32 atp is a
        # ~4.3e9 DoS ceiling for a verifier re-running a stranger's check).
        over = {"ski": 1, "term": "e" * 64, "atp": 100_000_001, "expect": "f" * 64}
        cb = canon(over)
        ch = hashlib.sha256(cb).hexdigest()
        ski_over = {"kind": "check", "check": ch, "runtime": "ski@v1", "verdict": "pass"}
        body = base(decision="accept", because=[ski_over])
        w = wid_of(body)
        s = Path(td) / "skiatp"
        (s / "records").mkdir(parents=True)
        (s / "blobs").mkdir(parents=True)
        (s / "records" / f"{w}.json").write_text(json.dumps({"body": body, "sigs": []}))
        (s / "blobs" / ch).write_bytes(cb)
        rp, rg = verify_py(s), verify_go(s)
        chk("ski@v1 over-budget atp: reported unverified, not evaluated",
            "ski@v1 unverified" in rp.stdout and "ski@v1 unverified" in rg.stdout)
        agree("ski@v1 over-budget atp", s)

        # small-order / non-canonical Ed25519 public keys MUST be rejected
        # (SPEC §5): an all-zero (small-order) key lets a zero signature verify
        # for a fraction of messages, and Python/Go libraries disagree on which
        # they accept -> a real consensus split. Filing a record whose only
        # signature uses such a key MUST error in BOTH, for EVERY message.
        for keyhex in ("00" * 32,
                       "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05"):
            splits = 0
            for n in range(24):
                body = base(decision="accept", actor={"id": "x"}, ts=n + 1)
                w = wid_of(body)
                env = {"body": body,
                       "sigs": [{"actor": "x", "key": keyhex, "sig": "00" * 64}]}
                s = write_store(Path(td) / f"weakkey_{keyhex[:6]}_{n}", {w: env})
                rp, rg = verify_py(s), verify_go(s)
                cp, cg = parse_counts(rp.stdout), parse_counts(rg.stdout)
                # both MUST report >=1 error (no valid signature by actor), and agree
                if not (cp and cg and cp[1] >= 1 and cg[1] >= 1 and cp == cg):
                    splits += 1
            chk(f"small-order key {keyhex[:6]}: rejected in both, every message",
                splits == 0)

        # duplicate member name in a record body -> invalid I-JSON (SPEC §4),
        # bounded malformed error in BOTH, never last-wins.
        s = Path(td) / "dupkey"
        (s / "records").mkdir(parents=True)
        (s / "blobs").mkdir(parents=True)
        (s / "records" / (c + ".json")).write_text(
            '{"body":{"warrant":"0.2","ts":1,"ts":2},"sigs":[]}')
        rp, rg = verify_py(s), verify_go(s)
        chk("duplicate key record: py bounded ERR (no last-wins)",
            "Traceback" not in rp.stderr and parse_counts(rp.stdout) is not None
            and parse_counts(rp.stdout)[1] >= 1)
        chk("duplicate key record: go bounded ERR (no last-wins)",
            "goroutine" not in rg.stderr and parse_counts(rg.stdout) is not None
            and parse_counts(rg.stdout)[1] >= 1)

        # A signature entry that is not an object MUST NOT crash the verifier
        # (Gemini 3.1 Pro audit: Python `s.get('actor')` on a str sig threw).
        body = base(decision="propose")
        w = wid_of(body)
        s = write_store(Path(td) / "sigscalar", {w: {"body": body, "sigs": ["evil"]}})
        rp, rg = verify_py(s), verify_go(s)
        chk("non-object signature entry: no crash, py/go agree",
            "Traceback" not in rp.stderr and "goroutine" not in rg.stderr
            and parse_counts(rp.stdout) is not None
            and parse_counts(rp.stdout) == parse_counts(rg.stdout))

        # Deeply-nested JSON MUST be a bounded report, not a stack overflow / panic
        # (Gemini 3.1 Pro audit: Python raised RecursionError; both must survive).
        s = Path(td) / "deepnest"
        (s / "records").mkdir(parents=True)
        (s / "blobs").mkdir(parents=True)
        (s / "records" / (GEN + ".json")).write_text(
            '{"body":' + "[" * 100000 + "]" * 100000 + ',"sigs":[]}')
        rp, rg = verify_py(s), verify_go(s)
        chk("deeply-nested record: py bounded (no RecursionError crash)",
            "Traceback" not in rp.stderr and "RecursionError" not in rp.stderr
            and parse_counts(rp.stdout) is not None and parse_counts(rp.stdout)[1] >= 1)
        chk("deeply-nested record: go bounded (no stack-overflow panic)",
            "goroutine" not in rg.stderr and parse_counts(rg.stdout) is not None)

    print("\nHOSTILE: ALL PASS" if all(ok) else "\nHOSTILE: FAILURES")
    sys.exit(0 if all(ok) else 1)


if __name__ == "__main__":
    main()
