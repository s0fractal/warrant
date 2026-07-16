#!/usr/bin/env python3
"""Evidence-pack guard — keeps the shipped demo packs honest.

For every pack under demos/*/pack:
  * `verify` reports 0 errors (recomputes IDs, checks sigs/links, re-runs ski),
  * each manifest ski_check re-executes to its stated `expect`,
  * the manifest's `expected_verification.errors` matches reality,
  * no private key material (*.key) is shipped in the pack.

Run: python3 tests/evidence_pack.py   (nonzero exit on any failure)
"""
import importlib.util
import json
import os
import sys

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
    return all(ok)


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
