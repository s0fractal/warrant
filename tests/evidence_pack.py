#!/usr/bin/env python3
"""Evidence-pack guard — keeps the shipped demo packs honest.

For every pack under demos/*/pack:
  * `verify` reports 0 errors (recomputes IDs, checks sigs/links, re-runs ski),
  * each manifest ski_check re-executes to its stated `expect`,
  * the manifest's `expected_verification.errors` matches reality,
  * no private key material (*.key) is shipped in the pack,
  * if a frozen replay vector (demos/<name>/replay.json) sits beside the pack:
    its input digests, evaluator pin and per-record vector match this tree,
    and its controls target blobs that exist and a check that really runs.

Run: python3 tests/evidence_pack.py   (nonzero exit on any failure)
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMOS = os.path.join(ROOT, "demos")

# Use the BUNDLED oracle, exactly as an installed verifier would (no env reliance).
os.environ.pop("SIGMA_GLYPH", None)
spec = importlib.util.spec_from_file_location(
    "warrant_impl", os.path.join(ROOT, "impl", "warrant.py"))
W = importlib.util.module_from_spec(spec)
spec.loader.exec_module(W)


def find_packs():
    if not os.path.isdir(DEMOS):
        return []
    out = []
    for name in sorted(os.listdir(DEMOS)):
        pack = os.path.join(DEMOS, name, "pack")
        if os.path.isdir(os.path.join(pack, ".warrants")):
            out.append(pack)
    return out


def check_pack(pack):
    ok = []

    def chk(cond, label, detail=""):
        ok.append(cond)
        print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")

    store = W.Store(os.path.join(pack, ".warrants"))
    manifest = json.load(open(os.path.join(pack, "manifest.json")))

    errs, warns = W.verify_store(store, quiet=True)
    exp = manifest.get("expected_verification", {}).get("errors", 0)
    chk(errs == 0, f"{os.path.basename(os.path.dirname(pack))}: verify 0 errors",
        f"got {errs} errors, {warns} warnings")
    chk(errs == exp, "  manifest expected_verification.errors matches", f"{errs} != {exp}")

    for c in manifest.get("ski_checks", []):
        try:
            verdict, rh, spent = W.run_ski_check(store, c["check"])
        except RuntimeError as ex:
            chk(False, f"  ski check {c['check'][:12]} re-executes", str(ex))
            continue
        chk(verdict == "pass" and rh == c["expect"] and spent == c["atp"],
            f"  ski check {c['check'][:12]} -> {c['expect'][:12]} @ {c['atp']} ATP",
            f"{verdict} {rh[:12]} {spent}")

    leaked = [f for _, _, fs in os.walk(pack) for f in fs if f.endswith(".key")]
    chk(not leaked, "  no private keys shipped", ", ".join(leaked))

    # A frozen replay vector beside the pack (demos/<name>/replay.json) is a
    # claim about THESE bytes under THIS evaluator. Hold it to the tree offline,
    # so the clean-environment replay (replay-clean.sh, which needs a wheel and a
    # venv) can never be the first place a stale freeze is noticed.
    replay = os.path.join(os.path.dirname(pack), "replay.json")
    if os.path.isfile(replay):
        check_replay_freeze(pack, store, replay, chk)
    return all(ok)


def check_replay_freeze(pack, store, replay_path, chk):
    rp = json.load(open(replay_path))
    chk(rp.get("replay") == "warrant-evidence-replay/0", "  replay.json is warrant-evidence-replay/0")

    # exact input bytes: every frozen file present and unchanged, nothing extra
    present = sorted(os.path.relpath(os.path.join(d, f), pack).replace(os.sep, "/")
                     for d, _, fs in os.walk(pack) for f in fs)
    frozen = rp["inputs"]
    chk(present == sorted(frozen), "  replay: frozen input set equals the pack's files",
        f"extra={sorted(set(present) - set(frozen))} missing={sorted(set(frozen) - set(present))}")
    drift = [rel for rel, want in frozen.items()
             if os.path.isfile(os.path.join(pack, rel)) and W.blob_hash(
                 open(os.path.join(pack, rel), "rb").read()) != want]
    chk(not drift, "  replay: every frozen input hashes to its digest", ", ".join(drift))

    # the evaluator the replay pins is the one this tree admits for the tag
    ev = rp["evaluator"]
    ent = W.SKI_EVALUATORS.get(ev["tag"])
    chk(ent is not None and ent == (ev["module"], ev["sha256"]),
        f"  replay: {ev['tag']} evaluator pin equals SKI_EVALUATORS", f"{ent} vs {ev}")

    # the frozen per-record vector is what THIS implementation produces
    trust = os.path.join(pack, rp["profile"]["trust_config"])
    base = W.verify_report(store)
    settle = W.verify_report(store, settlement={"genesis_roots": [], "trust_config": trust})
    chk(base["records"] == settle["records"] == len(rp["records"]),
        "  replay: record count as frozen", f"{base['records']}/{settle['records']}")
    for wid, spec in rp["records"].items():
        for grade, report in (("base", base), ("settlement", settle)):
            got = [{"level": f["level"], "message": f["message"]}
                   for f in report["findings"] if f["subject"] == wid]
            chk(got == spec[f"verify_{grade}"],
                f"  replay: {wid[:12]} verify ({grade}) findings as frozen",
                f"got {got} want {spec[f'verify_{grade}']}")
        sk = spec.get("ski_check")
        if sk:
            try:
                verdict, rh, spent = W.run_ski_check(store, sk["check"])
                got = (verdict, rh, spent)
            except RuntimeError as ex:
                got = ("unverified", str(ex))
            chk(got == (sk["verdict"], sk["result"], sk["atp_spent"]),
                f"  replay: {wid[:12]} check {sk['check'][:12]} as frozen", str(got))
    # the controls name blobs that exist in the pack (a control on an absent
    # blob would be testing "missing", not "mis-addressed")
    for name in ("cas-root", "cas-nested"):
        blob = rp["controls"][name]["blob"]
        chk(store.has_blob(blob), f"  replay: control {name} targets a blob the pack ships", blob[:12])
    # the verdict-fail control must be a check the evaluator RUNS to `fail` —
    # a malformed blob would be refused before evaluation and the control would
    # test the validator, not the verdict (the first freeze had a 66-char expect).
    vf = rp["controls"]["verdict-fail"]
    scratch = tempfile.mkdtemp(prefix="replay-freeze-")
    try:
        shutil.copytree(store.root, os.path.join(scratch, ".warrants"))
        st2 = W.Store(os.path.join(scratch, ".warrants"))
        doc = json.dumps({"atp": vf["atp"], "expect": vf["expect"], "ski": 1, "term": vf["term"]},
                         sort_keys=True, separators=(",", ":")).encode()
        try:
            got = W.run_ski_check(st2, st2.put_blob(doc))
        except RuntimeError as ex:
            got = ("unverified", str(ex))
        e = vf["expected"]
        chk(got == (e["verdict"], e["result"], e["atp_spent"]),
            "  replay: control verdict-fail evaluates to `fail` (not a refusal)", str(got))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def main():
    packs = find_packs()
    if not packs:
        print("no demo packs found under demos/*/pack — nothing to guard")
        return 0
    all_ok = all(check_pack(p) for p in packs)
    print("\n" + ("EVIDENCE-PACKS: ALL PASS" if all_ok else "EVIDENCE-PACKS: FAILURES PRESENT"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
