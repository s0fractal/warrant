#!/usr/bin/env python3
"""WRT-007 reproducer: does an INSTALLED (or downloaded) sigma_glyph module satisfy a runtime tag's pin?

Given a tag from runtime-pins.json and a path to a `sigma_glyph.py` (e.g. unpacked from the
published wheel, or `python -c "import sigma_glyph; print(sigma_glyph.__file__)"` in a venv):
  1. the module's sha256 must equal the tag's `module_sha256` (else: NOT_THE_PINNED_EVALUATOR);
  2. the WRT-006 differential is run with that module as E1 against E0 (the pre-W1 bundled engine),
     so the module's normative conformance and its agreement with the historical ski@v1 evaluator
     are both measured, not assumed.
Writes nothing. Exit 0 only if the pin matches and every WRT-006 axis except boundary is at its
expected value; the boundary axis is REPORTED (a v0.5 evaluator executes foreign bytes — the
refusal belongs to warrant's fetch layer, see WRT-007 §4) and does not gate here.
"""
import argparse, hashlib, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

ap = argparse.ArgumentParser()
ap.add_argument("--tag", default="ski@v1")
ap.add_argument("--module", required=True, help="path to the candidate sigma_glyph.py")
ap.add_argument("--pins", default=os.path.join(HERE, "runtime-pins.json"))
ap.add_argument("--sigma-repo", default=None)
a = ap.parse_args()

pins = json.load(open(a.pins))["tags"]
if a.tag not in pins or not pins[a.tag].get("module_sha256") or " " in str(pins[a.tag]["module_sha256"]):
    print(json.dumps({"tag": a.tag, "verdict": "NO_REGISTERED_PIN"})); sys.exit(1)
got = hashlib.sha256(open(a.module, "rb").read()).hexdigest()
pin_ok = got == pins[a.tag]["module_sha256"]
cmd = ["python3", os.path.join(ROOT, "proposals", "wrt-006-model", "differential.py"), "--new", a.module]
if a.sigma_repo:
    cmd += ["--sigma-repo", a.sigma_repo]
r = subprocess.run(cmd, capture_output=True, text=True)
try:
    rec = json.loads(r.stdout)
except Exception:
    rec = {"error": "differential produced no receipt", "stderr": r.stderr[-400:]}
v = rec.get("verdicts", {})
gate = pin_ok and v.get("suite_shape") == "MATCH" and v.get("E1_conformance") == "PASS" \
    and v.get("differential_agreement") == "MATCH" and v.get("ski_specimen") == "MATCH"
out = {"schema": "wrt-007-installed-engine-receipt/0", "tag": a.tag, "module": os.path.relpath(a.module) if a.module.startswith(ROOT) else "<external>",
       "module_sha256": got, "pin_sha256": pins[a.tag]["module_sha256"], "pin_matches": pin_ok,
       "wrt006_verdicts": v, "boundary_reported": rec.get("axes", {}).get("boundary_observation", {}).get("observed"),
       "verdict": "PINNED_AND_CONFORMING" if gate else ("NOT_THE_PINNED_EVALUATOR" if not pin_ok else "PINNED_BUT_NOT_CONFORMING")}
print(json.dumps(out, indent=1, sort_keys=True, default=str))
sys.exit(0 if gate else 1)
