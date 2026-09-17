#!/usr/bin/env python3
"""The `ski@v1` evaluator and the Book I 0.6.0 module, on the same check blobs.

    python3 proposals/wrt-013-model/engine_differential.py /path/to/sigma_glyph.py

`/path/to/sigma_glyph.py` is the Book I 0.6.0 module — the one inside PyPI
`sigma-glyph==0.7.0`. Both modules are hashed before they are imported and the
run REFUSES on any mismatch, because a differential between unidentified bytes
measures nothing.

WHAT IS COMPARED, EXACTLY
-------------------------
For each case: the `ski@v1` engine's `eval_hash` → `(result_hash, atp_spent)`,
and the 0.6.0 engine's `eval_receipt` → `(exit, result_hash, atp_spent)`.

The `verdict` columns are BOTH the **`ski@v1` projection** — `pass` iff the
result hash equals `expect`. That is deliberately *not* the `ski@v2` verdict
WRT-013 proposes (which also requires the exit to match the blob's declared
exit); printing the v1 projection for both engines is what makes "the engines
agree on everything v1 can express" a measurement rather than a definition.

SCOPE. This compares the §8.2 specimen at six budgets. It is not a conformance
run, it does not sample the space of expressible terms, and agreement here
certifies no record.

Exit status: 0 iff every case agrees on `(result_hash, atp_spent)`; 1 otherwise.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]            # the checkout this file is in
V05 = ROOT / "impl/sigma_glyph_v05.py"
V05_SHA = "80299d6869e7c93ece3455db32c0a6a1346a8b7162e6ef0954a4bd425497bab5"
V06_SHA = "f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4"


def load_pinned(path, name, expected_sha):
    path = Path(path)
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    if got != expected_sha:
        sys.exit(f"REFUSING: {path} is sha256 {got}, expected {expected_sha}")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CAS:
    """The §8.2 specimen's node blobs, as a Σ-GLYPH content-addressed store."""

    def __init__(self, directory):
        self.dir = Path(directory)

    def get(self, h):
        for name in (h.hex(), h.hex() + ".bin"):
            p = self.dir / name
            if p.exists():
                return p.read_bytes()
        return None


def main(v06_path):
    e1 = load_pinned(V05, "sigma_v05", V05_SHA)             # the pinned ski@v1 engine
    e2 = load_pinned(v06_path, "sigma_v06", V06_SHA)        # published Book I 0.6.0
    print(f"ski@v1 evaluator {V05_SHA}\nBook I 0.6.0     {V06_SHA}\n")

    blobs = ROOT / "examples/ski"
    spec = json.loads((blobs / "check.json").read_text())
    cases = [("§8.2 specimen", spec)]
    cases += [(f"same term, atp={a}", dict(spec, atp=a)) for a in (0, 1, 5, 19, 20, 21)]

    disagreements = 0
    print(f"{'case':22s} {'v1 result':14s} {'spent':>5}  {'0.6.0 result':14s} {'spent':>5}  "
          f"{'exit':20s} v1-projection verdicts")
    for name, doc in cases:
        term, atp = bytes.fromhex(doc["term"]), doc["atp"]
        r1, s1 = e1.eval_hash(term, atp, CAS(blobs))
        h1 = e1.term_hash(r1).hex()
        rec = e2.eval_receipt(term, atp, CAS(blobs))
        h2, s2 = rec.result_hash.hex(), rec.atp_spent
        agree = (h1 == h2) and (s1 == s2)
        disagreements += 0 if agree else 1
        v1 = "pass" if h1 == doc["expect"] else "fail"
        v2 = "pass" if h2 == doc["expect"] else "fail"
        print(f"{name:22s} {h1[:14]} {s1:>5}  {h2[:14]} {s2:>5}  {rec.exit:20s} "
              f"{v1}/{v2}{'' if agree else '   <-- DISAGREE'}")

    print(f"\n{len(cases)} cases, {disagreements} disagreement(s) on "
          f"(result_hash, atp_spent).")
    if disagreements:
        print("the engines disagree — every conclusion in WRT-013 §2 is void",
              file=sys.stderr)
        return 1
    print("The exit column is the observable ski@v1 has no way to report; "
          "see fingerprint_collision.py for why that matters to §7.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
