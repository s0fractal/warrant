"""Differential: ski@v1 evaluator (Book I v0.5, warrant-bundled) vs the published
sigma-glyph 0.7.0 module (Book I 0.6.0), over real Warrant ski check blobs."""
import hashlib, importlib.util, json, sys
from pathlib import Path

W = Path("/Users/s0fractal/Projects/warrant")
V05 = W / "impl/sigma_glyph_v05.py"
V07 = Path(sys.argv[1])           # installed sigma_glyph.py (PyPI 0.7.0)

def load(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

e1, e2 = load(V05, "sg_v05"), load(V07, "sg_v07")
print("v05", hashlib.sha256(V05.read_bytes()).hexdigest()[:16],
      "| v07", hashlib.sha256(V07.read_bytes()).hexdigest()[:16])

class CAS:
    def __init__(self, d): self.d = d
    def get(self, h):
        for name in (h.hex(), h.hex() + ".bin"):
            p = self.d / name
            if p.exists():
                return p.read_bytes()
        return None

def run(doc, store):
    out = {}
    r, spent = e1.eval_hash(bytes.fromhex(doc["term"]), doc["atp"], CAS(store))
    out["v1"] = {"result": e1.term_hash(r).hex(), "spent": spent, "exit": None}
    rec = e2.eval_receipt(bytes.fromhex(doc["term"]), doc["atp"], CAS(store))
    out["v2"] = {"result": rec.result_hash.hex(), "spent": rec.atp_spent, "exit": rec.exit}
    out["agree"] = out["v1"]["result"] == out["v2"]["result"] and out["v1"]["spent"] == out["v2"]["spent"]
    out["verdict_v1"] = "pass" if out["v1"]["result"] == doc["expect"] else "fail"
    out["verdict_v2"] = "pass" if out["v2"]["result"] == doc["expect"] else "fail"
    return out

cases = []
d = json.loads((W / "examples/ski/check.json").read_text())
cases.append(("examples/ski/check.json", d, W / "examples/ski"))
# same term, budgets around the exact cost: exhaustion behaviour on both engines
for atp in (0, 1, 5, 19, 20, 21):
    cases.append((f"check.json@atp={atp}", dict(d, atp=atp), W / "examples/ski"))

for name, doc, store in cases:
    r = run(doc, store)
    print(f"{name:34s} v1={r['v1']['result'][:12]} spent={r['v1']['spent']:<4} "
          f"v2={r['v2']['result'][:12]} spent={r['v2']['spent']:<4} exit={r['v2']['exit']:<20} "
          f"agree={r['agree']} verdicts={r['verdict_v1']}/{r['verdict_v2']}")
