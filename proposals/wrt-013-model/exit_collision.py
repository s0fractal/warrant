#!/usr/bin/env python3
"""The counterexample `ski@v2` exists for: one result hash, one spend, two exits.

    python3 proposals/wrt-013-model/exit_collision.py /path/to/sigma_glyph.py

`/path/to/sigma_glyph.py` is the Book I 0.6.0 module — the one inside PyPI
`sigma-glyph==0.7.0` (sha256 f4d9990d40f07c8cfd3aa10512c2195a0a04e8dc78bc955c0f53dfe737d3feb4).

Under `ski@v1` a reason states "eval(term, atp) has NodeHash `expect`". Two runs
that reach the same NodeHash are, to that statement, the same event. They are not:

  A  the §8.2 term under a budget it cannot finish in  -> exit atp_exhausted
  B  a term whose NORMAL FORM is DISSONANCE("ATP Exhausted")
                                                       -> exit normal_form

Both answer `8bb0006f…`. This script searches a small family of B terms for one
that also matches A's `atp_spent`, so that every observable `ski@v1` has — and
every field of its §7 outcome fingerprint — is identical across a finished
computation and an unfinished one. It prints the first such pair.

Exit status 0 if the collision reproduces, 1 if it does not.
"""
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(v06_path):
    e = load(Path(v06_path), "sigma_v06")
    e1 = load(ROOT / "impl/sigma_glyph_v05.py", "sigma_v05")   # the ski@v1 evaluator
    work = Path(tempfile.mkdtemp(prefix="wrt013-"))

    class CAS:
        def get(self, h):
            p = work / h.hex()
            if p.exists():
                return p.read_bytes()
            q = ROOT / "examples/ski" / (h.hex() + ".bin")
            return q.read_bytes() if q.exists() else None

    def put(b):
        h = e.node_hash(b)
        (work / h.hex()).write_bytes(b)
        return h

    dissonance = put(e.ser(e.DISSONANCE, e.F_ATOM, atom=e.sha(b"ATP Exhausted")))
    a_term = bytes.fromhex(json.loads((ROOT / "examples/ski/check.json").read_text())["term"])

    family, node = {}, dissonance            # APPLY(I, …)^k over the DISSONANCE node
    for k in range(6):
        family[k] = node
        node = put(e.ser(e.APPLY, e.F_LEFT | e.F_RIGHT, left=e.I_H, right=node))

    for atp_a in range(25):
        ra = e.eval_receipt(a_term, atp_a, CAS())
        if ra.exit != "atp_exhausted":
            continue
        for k, term in family.items():
            for atp_b in range(25):
                rb = e.eval_receipt(term, atp_b, CAS())
                if (rb.exit == "normal_form"
                        and rb.result_hash == ra.result_hash
                        and rb.atp_spent == ra.atp_spent):
                    # What ski@v1 can see about each run, from its own evaluator.
                    a1, sa = e1.eval_hash(a_term, atp_a, CAS())
                    b1, sb = e1.eval_hash(term, atp_b, CAS())
                    print(f"result_hash {ra.result_hash.hex()}  atp_spent {ra.atp_spent}")
                    print(f"  A  §8.2 term, atp={atp_a:<3}            "
                          f"ski@v1: ({e1.term_hash(a1).hex()[:16]}, {sa})   "
                          f"ski@v2 exit: {ra.exit}")
                    print(f"  B  APPLY(I,·)^{k} over DISSONANCE, atp={atp_b:<3} "
                          f"ski@v1: ({e1.term_hash(b1).hex()[:16]}, {sb})   "
                          f"ski@v2 exit: {rb.exit}")
                    print("\nEvery ski@v1 observable agrees; the exits do not. "
                          "A verdict and a §7 fingerprint built from the result "
                          "hash alone cannot tell these apart.")
                    return 0
    print("no collision found in this family", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
