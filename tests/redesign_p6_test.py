#!/usr/bin/env python3
"""Redesign P6 draft checks (N66, N67, N68), one case each, reason named.

N68 copies ONLY demos/redesign-refund and the impl files it needs into a fresh
directory, runs it with `python3 -I` from there, and fails if the run names any
path of this checkout: no sibling repository, no hidden import of the tree.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "impl"))
import assessment as A   # noqa: E402
import warrant as W      # noqa: E402

IMPL_FILES = ["assessment.py", "warrant.py", "policy_lang.py", "ski_policy.py", "policy_binding.py",
              "sigma_glyph_v05.py", "sigma_glyph_v06.py"]
results = []


def case(nid, ok, what, detail=""):
    results.append(ok)
    print(("ok    " if ok else "FAIL  ") + f"{nid} {what}" + ("" if ok else f" | {detail}"))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="p6-"))
    S = W.Store(str(tmp / "s"))
    S.init()
    key = tmp / "a.key"
    key.write_text("44" * 32 + "\n")
    # N66: an old-shape record is refused by the current reader, bytes untouched
    body = {"warrant": "0.2", "decision": "accept", "subject": {"hash": S.put_blob(b"x\n"), "note": "old"},
            "under": [S.put_blob(b"prose policy\n")], "because": [], "evidence": [], "actor": {"id": "a@x"},
            "prior": [], "ts": 1}
    old = S.put_record({"body": body, "sigs": [W.sign_envelope(body, "a@x", str(key))]})
    before = (S.records / f"{old}.json").read_bytes()
    got = A.read_current(S, old)
    after = (S.records / f"{old}.json").read_bytes()
    prog = A.program("o", {"amount": "int"}, "amount <= 5")
    facts = A.fact_set("o", {"amount": A.observed(3, "none")})
    new = A.write_decision(S, "accept", S.put_blob(b"y\n"), prog, facts, A.plan(prog, facts, put=S.put_blob),
                           "a@x", key, ts=2)
    case("N66", got["profile"] == A.UNSUPPORTED_HISTORICAL_PROFILE and before == after
         and got["basis"]["warrant_id"] == old and A.read_current(S, new)["profile"] == A.CURRENT_PROFILE,
         "old body: UNSUPPORTED_HISTORICAL_PROFILE with its exact identity, bytes unchanged; "
         "the one writer only writes the current shape", got)

    # N66, historical side: the frozen verifier pack verifies what the current path refuses
    pack = tmp / "pack"
    hp = [sys.executable, str(ROOT / "tools" / "historical_pack.py")]
    subprocess.run(hp + ["build", str(pack)], capture_output=True, check=True)
    r_old = subprocess.run(hp + ["verify", str(pack), str(S.root)], capture_output=True, text=True, check=False)
    (pack / "impl" / "warrant.py").write_bytes((pack / "impl" / "warrant.py").read_bytes() + b"# tampered\n")
    r_bad = subprocess.run(hp + ["verify", str(pack), str(S.root)], capture_output=True, text=True, check=False)
    # Independent review WA06: an empty self-declared file list and a substituted verifier.
    sub = tmp / "substituted"
    (sub / "impl").mkdir(parents=True)
    (sub / "impl" / "warrant.py").write_text('print("SUBSTITUTED_VERIFIER")\n')
    (sub / "MANIFEST.json").write_text(json.dumps({"schema": "warrant.historical-pack@draft-1",
                                                   "repository": "https://github.com/s0fractal/warrant",
                                                   "commit": "ca53e6489c5d888768193e2d172e72409a1eb560",
                                                   "files": {}}))
    r_sub = subprocess.run(hp + ["verify", str(sub), str(S.root)], capture_output=True, text=True, check=False)
    case("N66-pack", r_old.returncode == 0 and " 0 errors" in r_old.stdout
         and r_bad.returncode == 2 and "PACK" in r_bad.stdout
         and r_sub.returncode == 2 and "SUBSTITUTED_VERIFIER" not in r_sub.stdout,
         "the baseline pack verifies the old record; a tampered pack, or one declaring the baseline with an "
         "empty file list and its own verifier (review WA06), runs nothing",
         (r_old.stdout[-200:], r_bad.stdout[-200:], r_sub.stdout[-200:]))

    # N67: a co-signature changes the envelope snapshot, not the body id
    env = json.loads((S.records / f"{new}.json").read_text())
    key2 = tmp / "b.key"
    key2.write_text("55" * 32 + "\n")
    cosigned = dict(env, sigs=env["sigs"] + [W.sign_envelope(env["body"], "b@x", str(key2))])
    case("N67", W.warrant_id(env["body"]) == W.warrant_id(cosigned["body"])
         and A.envelope_snapshot_id(env) != A.envelope_snapshot_id(cosigned)
         and A.envelope_snapshot_id(env) == A.envelope_snapshot_id(json.loads(json.dumps(env))),
         "added co-signature: same body id, new envelope snapshot id (the anchor does not prove the quorum)")

    # N68: the demo in a fresh directory, isolated
    fresh = Path(tempfile.mkdtemp(prefix="p6-fresh-"))
    shutil.copytree(ROOT / "demos" / "redesign-refund", fresh / "demos" / "redesign-refund",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (fresh / "impl").mkdir()
    for f in IMPL_FILES:
        shutil.copy2(ROOT / "impl" / f, fresh / "impl" / f)
    r = subprocess.run([sys.executable, "-I", "demos/redesign-refund/run.py"],
                       cwd=fresh, capture_output=True, text=True, check=False, timeout=600)
    out = r.stdout + r.stderr
    leaked = str(ROOT) in out
    case("N68", r.returncode == 0 and "SCENARIO HOLDS" in out and not leaked,
         "the §25 scenario runs from a fresh directory with only its own files, python -I, no checkout path",
         out[-600:])
    print("\nREDESIGN P6:", "ALL PASS" if all(results) else "FAILURES")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
