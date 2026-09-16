#!/usr/bin/env python3
"""WRT-012 e2e-001 — one stream, one real timestamp, a same-custody holder,
the verifier actually run, and the three freshness controls.

Deterministic driver. protocol.json is written FIRST (predeclared endpoints),
then every step runs through tools/witness.py as a subprocess and results.json
records expected vs observed per endpoint. Re-running refuses: the store and
the initial receipt are never overwritten.

Network: exactly one `ots stamp` (a digest to the two public calendars). The
holder here is on the same host and under the same custody as the committer,
so the external half is expected NOT_DEMONSTRATED — that expectation is itself
an endpoint. Zero model calls.
"""
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
TOOL = ROOT / "tools" / "witness.py"
PAPER = ROOT / "papers" / "the-reason-runs-again"
KEYDIR = pathlib.Path(os.environ.get("WRT012_KEYDIR", str(pathlib.Path.home() / ".local" / "share" / "warrant" / "wrt012-e2e-001-keys")))

SUBJECT = "da2f5506e315cb2243eac2700dc7898c2b52930f667963304e0db7904b13a111"   # the-reason-runs-again.pdf (deposited/SHA256SUMS)
CLOSURE = hashlib.sha256((PAPER / "check_claims.py").read_bytes()).hexdigest()
STREAM = hashlib.sha256(b"warrant:papers/the-reason-runs-again:wrt-012-e2e-001").hexdigest()
DEPOSIT_COMMIT = "d83984f"


def sha_file(p):
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def w(*args, cwd=None):
    r = subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True, cwd=cwd)
    last = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "{}"
    try:
        out = json.loads(last)
    except json.JSONDecodeError:
        out = {"raw": r.stdout[-500:]}
    return r.returncode, out, r.stderr[-500:]


def report(store, c, holders):
    rc, out, err = w("report", "--store", store, "--commitment", c, "--holders", holders, "--compact")
    assert rc == 0, (rc, out, err)
    return out


def main():
    if (HERE / "results.json").exists():
        print("REFUSED: experiment already completed (results.json exists); never overwrite")
        return 1
    resume = (HERE / "store").exists()
    protocol = {
        "type": "warrant.experiment-protocol@wrt012-e2e-001",
        "wrt": "WRT-012 rev 3 §4",
        "subject": {"kind": "file", "sha256": SUBJECT, "ref": "papers/the-reason-runs-again/deposited/SHA256SUMS: the-reason-runs-again.pdf"},
        "verifier": {"closure_sha256": CLOSURE, "ref": "papers/the-reason-runs-again/check_claims.py", "argv": ["--ref", DEPOSIT_COMMIT]},
        "stream": STREAM,
        "holder": {"id": "same-host-holder", "custody": "github:s0fractal", "independent": False,
                   "note": "same host, same custody as the committer; exists to exercise mechanics only"},
        "network": "one `ots stamp` of C1 (a digest) to the two public calendars; `report` is offline",
        "endpoints": {
            "E1": "C1 canonical bytes reproduce the digest on a second read",
            "E2": "classify C1 = FILE_BOUND_PENDING; time_verified false; a receipt for other bytes is refused",
            "E3": "holder receipt for C1 verifies -> holding EXTERNALLY_OBSERVED(same-host-holder, custody github:s0fractal); external half = NOT_DEMONSTRATED (holder not independent)",
            "E4": "report before any run: verification method=EXTERNAL_CLOSURE result=NOT_RUN",
            "E4b": "after run-verifier with check_claims.py --ref d83984f: result in {PASS,FAIL} recorded; every other axis byte-identical; proof inputs identical",
            "E5A": "local stream truncated at C1, holder store WITHOUT anything after C1 -> freshness UNKNOWN and nothing stronger",
            "E5B": "same truncated stream, holder store WITH C2 (prev=C1) -> LATER_STATE_WITNESSED(same-host-holder, path C1->C2, steps 1)",
            "E5C": "holder store with a branch commitment of larger sequence and no path to C1 -> UNKNOWN with note DISCONNECTED, no PATH_INCOMPLETE",
            "E6": "external half: NOT_DEMONSTRATED (no holder outside our custody); §5 spread stays closed",
        },
        "model_calls": 0,
    }
    if resume:
        # protocol.json was written by the first attempt; it must be byte-identical to what we would write now
        assert (HERE / "protocol.json").read_text() == json.dumps(protocol, indent=1, sort_keys=True) + "\n", "PROTOCOL_CHANGED"
    else:
        (HERE / "protocol.json").write_text(json.dumps(protocol, indent=1, sort_keys=True) + "\n")
    res = {"protocol_sha256": sha_file(HERE / "protocol.json"), "steps": [], "endpoints": {},
           "resumed": resume,
           "resume_note": ("first attempt (2026-09-10) completed steps 1-4b and stopped at step 5 with FileNotFoundError: "
                           "the driver ran on `master`, where the C2 subject file (WRT-012 on the branch) does not exist. "
                           "The store, the initial .ots receipt, the holder store and reports 1/2 were kept; nothing was re-stamped. "
                           "E1-E4b below are re-derived from those stored artifacts on resume.") if resume else None}

    def step(name, **kw):
        res["steps"].append({"step": name, **kw})
        print(name, json.dumps(kw)[:300])

    def endpoint(name, ok, observed):
        res["endpoints"][name] = {"expected": protocol["endpoints"][name], "met": bool(ok), "observed": observed}
        print(("MET  " if ok else "MISS "), name)

    store = HERE / "store"
    # 1. commit C1
    if resume:
        c1 = (store / "tip").read_text().strip()
        step("commit C1 (reused from first attempt)", commitment=c1)
    else:
        rc, out, err = w("commit", "--store", store, "--subject-kind", "file", "--subject-sha256", SUBJECT,
                         "--verifier-closure-sha256", CLOSURE, "--stream", STREAM)
        assert rc == 0, (out, err)
        c1 = out["commitment"]
        step("commit C1", commitment=c1, sequence=out["sequence"])
    b = (store / "commitments" / f"{c1}.json").read_bytes()
    endpoint("E1", hashlib.sha256(b).hexdigest() == c1 and json.loads(b)["subject"]["sha256"] == SUBJECT, {"reread_sha256": hashlib.sha256(b).hexdigest()})

    # 2. stamp C1 (network) + classify
    if resume:
        rc, out = 0, {"proof_sha256": sha_file(store / "proofs" / f"{c1}.ots")}
        step("stamp C1 (initial receipt from first attempt, not re-stamped)", proof_sha256=out["proof_sha256"])
    else:
        rc, out, err = w("stamp", "--store", store, "--commitment", c1)
        step("stamp C1", exit=rc, proof_sha256=out.get("proof_sha256"), stderr=err[-200:])
    rc2, cls, _ = w("classify", "--store", store, "--commitment", c1)
    step("classify C1", exit=rc2, classification=cls)
    # wrong-bytes refusal: classify a copy of the receipt against C1 bytes + 1 byte
    tmp = HERE / "scratch"
    tmp.mkdir(exist_ok=True)
    wrong_store = tmp / "wrong"
    (wrong_store / "commitments").mkdir(parents=True)
    (wrong_store / "proofs").mkdir()
    wb = b + b"\n"
    wc = hashlib.sha256(wb).hexdigest()
    (wrong_store / "commitments" / f"{wc}.json").write_bytes(wb)
    if (store / "proofs" / f"{c1}.ots").exists():
        shutil.copy(store / "proofs" / f"{c1}.ots", wrong_store / "proofs" / f"{wc}.ots")
        rc3, wrong, _ = w("classify", "--store", wrong_store, "--commitment", wc)
    else:
        rc3, wrong = 2, {"reason": "NO_OTS_TO_TEST"}
    step("classify receipt against other bytes", exit=rc3, out=wrong)
    endpoint("E2", rc == 0 and cls.get("status") == "FILE_BOUND_PENDING" and cls.get("time_verified") is False
             and rc3 == 2 and wrong.get("reason") == "OTS_FILE_DIGEST", {"classify": cls.get("status"), "wrong": wrong.get("reason")})

    # 3. same-custody holder receives C1
    KEYDIR.mkdir(parents=True, exist_ok=True)
    key = KEYDIR / "same-host-holder.secret.hex"
    holder_store = HERE / "holder-same-host"
    holders = HERE / "holders.json"
    if resume:
        assert key.exists() and holders.exists(), "RESUME_NEEDS_KEY_AND_HOLDERS"
        kg = {"pubkey_hex": json.loads(holders.read_text())["holders"][0]["pubkey_hex"]}
        step("holder receipt for C1 (reused)", receipt_sha256=sha_file(holder_store / "receipts" / f"{c1}.json"), pubkey=kg["pubkey_hex"])
    else:
        if key.exists():
            key.unlink()
        rc, kg, _ = w("keygen", "--out", key)
        rc, rcv, err = w("receive", "--holder-store", holder_store, "--holder-id", "same-host-holder", "--key", key,
                         "--commitment-file", store / "commitments" / f"{c1}.json", "--observed", "2026-09-10")
        assert rc == 0, (rcv, err)
        holders.write_text(json.dumps({"holders": [{"id": "same-host-holder", "pubkey_hex": kg["pubkey_hex"],
                                                    "store": str(holder_store), "custody": "github:s0fractal"}]}, indent=1) + "\n")
        step("holder receives C1", receipt_sha256=rcv["receipt_sha256"], pubkey=kg["pubkey_hex"], key_location=str(key))

    # 4. report before run
    if resume:
        r1 = json.loads((HERE / "report-1-before-run.json").read_text())
    else:
        r1 = report(store, c1, holders)
        (HERE / "report-1-before-run.json").write_text(json.dumps(r1, indent=1, sort_keys=True) + "\n")
    endpoint("E3", r1["holding"][0]["status"] == "EXTERNALLY_OBSERVED" and r1["holding"][0]["custody"] == "github:s0fractal",
             {"holding": r1["holding"], "external_half": "NOT_DEMONSTRATED (holder not independent)"})
    endpoint("E4", r1["verification"] == {"method": "EXTERNAL_CLOSURE", "result": "NOT_RUN", "scope": None}, r1["verification"])

    # 4b. run the pinned verifier, then report again on the same frozen proofs
    if resume:
        rc, run = 0, json.loads((store / "runs" / f"{c1}.json").read_text())
        step("run-verifier (run record from first attempt, never re-run)", run={k: run[k] for k in ("method", "result", "scope", "exit")})
        r2 = json.loads((HERE / "report-2-after-run.json").read_text())
        r2_now = report(store, c1, holders)
        assert r2_now == r2, "REPORT_2_NOT_REPRODUCIBLE"
        step("report-2 recomputed on resume: identical to stored", identical=True)
    else:
        rc, run, err = w("run-verifier", "--store", store, "--commitment", c1, "--script", PAPER / "check_claims.py",
                         "--cwd", PAPER, "--scope", f"countable claims in paper.md recounted at {DEPOSIT_COMMIT}; source identity of paper.md/references.bib/build.sh",
                         "--", "--ref", DEPOSIT_COMMIT)
        step("run-verifier", exit=rc, run=run, stderr=err[-200:])
        r2 = report(store, c1, holders)
        (HERE / "report-2-after-run.json").write_text(json.dumps(r2, indent=1, sort_keys=True) + "\n")
    strip = lambda r: {k: v for k, v in r.items() if k not in ("verification", "inputs_sha256")}
    proofs = lambda r: {k: v for k, v in r["inputs_sha256"].items() if "/runs/" not in k}
    endpoint("E4b", rc == 0 and r2["verification"]["result"] in ("PASS", "FAIL") and strip(r1) == strip(r2) and proofs(r1) == proofs(r2),
             {"verification": r2["verification"], "other_axes_identical": strip(r1) == strip(r2), "proof_inputs_identical": proofs(r1) == proofs(r2)})

    # 5. C2 on the same stream (subject: WRT-012 rev 3 text), holder receives it
    wrt = ROOT / "proposals" / "WRT-012-ownerless-root.md"
    rc, out, err = w("commit", "--store", store, "--subject-kind", "file", "--subject-sha256", sha_file(wrt), "--verifier-closure-sha256", CLOSURE)
    assert rc == 0, (out, err)
    c2 = out["commitment"]
    step("commit C2", commitment=c2, sequence=out["sequence"], prev=out["prev"])
    # Control A: truncated local stream at C1; holder store snapshot BEFORE receiving C2
    trunc = HERE / "truncated-at-C1"
    shutil.copytree(store, trunc)
    os.remove(trunc / "commitments" / f"{c2}.json")
    (trunc / "tip").write_text(c1 + "\n")
    holder_a = HERE / "holder-snapshot-before-C2"
    shutil.copytree(holder_store, holder_a)
    hA = HERE / "holders-A.json"
    hA.write_text(json.dumps({"holders": [{"id": "same-host-holder", "pubkey_hex": kg["pubkey_hex"], "store": str(holder_a), "custody": "github:s0fractal"}]}) + "\n")
    fA = report(trunc, c1, hA)["freshness"]
    endpoint("E5A", fA["status"] == "UNKNOWN", fA)
    # Control B: holder receives C2; truncated stream consults the live holder store
    rc, rcv2, err = w("receive", "--holder-store", holder_store, "--holder-id", "same-host-holder", "--key", key,
                      "--commitment-file", store / "commitments" / f"{c2}.json", "--observed", "2026-09-10")
    assert rc == 0, (rcv2, err)
    fB = report(trunc, c1, holders)["freshness"]
    endpoint("E5B", fB["status"] == "LATER_STATE_WITNESSED" and fB.get("holder") == "same-host-holder" and fB.get("steps") == 1, fB)
    # Control C: a branch on the same stream with different subjects, sequence 0..1, received by a second same-host holder
    branch = HERE / "branch"
    for i in range(2):
        subj = hashlib.sha256(f"branch-{i}".encode()).hexdigest()
        rc, out, err = w("commit", "--store", branch, "--subject-kind", "file", "--subject-sha256", subj, "--verifier-closure-sha256", CLOSURE, *(["--stream", STREAM] if i == 0 else []))
        assert rc == 0, (out, err)
        bc = out["commitment"]
    key2 = KEYDIR / "branch-holder.secret.hex"
    if key2.exists():
        key2.unlink()
    rc, kg2, _ = w("keygen", "--out", key2)
    holder_c = HERE / "holder-branch"
    for f in sorted((branch / "commitments").glob("*.json")):
        rc, _, err = w("receive", "--holder-store", holder_c, "--holder-id", "branch-holder", "--key", key2, "--commitment-file", f, "--observed", "2026-09-10")
        assert rc == 0, err
    hC = HERE / "holders-C.json"
    hC.write_text(json.dumps({"holders": [{"id": "branch-holder", "pubkey_hex": kg2["pubkey_hex"], "store": str(holder_c), "custody": "github:s0fractal"}]}) + "\n")
    # local C_i = C0 of the main stream? The main stream's genesis IS C1 (sequence 0). Branch has sequence 1 with prev = branch genesis != C1.
    fC = report(trunc, c1, hC)["freshness"]
    outs = {n.get("outcome") for n in fC["notes"]}
    endpoint("E5C", fC["status"] == "UNKNOWN" and "DISCONNECTED" in outs and "PATH_INCOMPLETE" not in outs, fC)
    endpoint("E6", True, {"external_half": "NOT_DEMONSTRATED", "reason": "no holder outside custody github:s0fractal", "spread_open": False})

    shutil.rmtree(tmp, ignore_errors=True)
    res["all_endpoints_met"] = all(e["met"] for e in res["endpoints"].values())
    res["external_half"] = "NOT_DEMONSTRATED"
    res["model_calls"] = 0
    (HERE / "results.json").write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    # SHA256SUMS over everything tracked here except itself
    lines = []
    for p in sorted(HERE.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS":
            lines.append(f"{sha_file(p)}  {p.relative_to(HERE)}")
    (HERE / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    print("ALL ENDPOINTS MET" if res["all_endpoints_met"] else "ENDPOINT(S) MISSED", "| external half:", res["external_half"])
    return 0 if res["all_endpoints_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
