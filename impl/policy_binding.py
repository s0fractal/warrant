#!/usr/bin/env python3
"""WRT-020 reference profile: does a decision follow from the policy it cites?

    python3 impl/policy_binding.py STORE [STORE ...] [--json]

Warrant pins the policy a record cites (`under`) and re-runs the record's
`ski@v1` reasons, but nothing connects the two. A reason can be an unrelated
computation, and the decision can disagree with the policy's own answer. Both
verify clean today (tests/countermodel_policy_binding.py, and an `accept` whose
reason replays the policy's FALSE). This profile reports, for every record and
every policy blob it cites, one of:

    BOUND         the policy is WPL; a ski@v1 reason of the record is exactly its
                  compilation (same check hash), and the decision does not
                  contradict the policy's answer
    CONTRADICTED  as BOUND, but the record ACCEPTS while the policy answers false
    UNBOUND       the policy is WPL, but no ski@v1 reason is its compilation: the
                  reasons, whatever they compute, are not this policy
    OPAQUE        the policy is not machine-readable (prose, any other bytes):
                  compliance is NOT CHECKED, and is reported as such
    SIGNATURES    a v0.3 threshold policy: it governs who signs, which settlement
                  already enforces; there is no computation to bind

Only `accept` is gated by the answer: a `reject` where the policy would allow is
discretion, not a contradiction, and `propose`/`supersede` decide nothing yet.

This is a profile, not SPEC. It changes no verdict of `warrant verify`, and a
verifier that ignores it is still conformant. Whether CONTRADICTED (or UNBOUND)
should become an error at settlement grade is the open decision of WRT-020.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import policy_lang as WPL  # noqa: E402

MAX_POLICY_BYTES = 64 * 1024
GATED = {"accept"}
ORDER = ["CONTRADICTED", "UNBOUND", "OPAQUE", "BOUND", "SIGNATURES"]


def classify_policy(raw):
    """('wpl', Compiled) | ('threshold', None) | ('opaque', why)."""
    try:
        doc = json.loads(raw)
        if isinstance(doc, dict) and doc.get("warrant_policy") == "0.3":
            return "threshold", None
    except (ValueError, UnicodeDecodeError):
        pass
    if len(raw) > MAX_POLICY_BYTES:
        return "opaque", "larger than the profile reads"
    try:
        src = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "opaque", "not UTF-8"
    try:
        # put() only hashes: the profile must not write to the store it reads,
        # and without a put the compiler computes no check hash at all.
        return "wpl", WPL.compile_source(src, lambda b: hashlib.sha256(b).hexdigest())
    except WPL.PolicyError as e:
        return "opaque", f"not WPL: {str(e).splitlines()[0][:80]}"
    except (WPL.CompilerBug, RecursionError, ValueError) as e:
        return "opaque", f"did not compile: {type(e).__name__}"


def classify_record(body, blobs):
    rows = []
    reasons = [r for r in body.get("because", []) if isinstance(r, dict)
               and r.get("kind") == "check" and r.get("runtime") == "ski@v1"]
    decision = body.get("decision")
    for h in body.get("under", []):
        p = blobs / h if isinstance(h, str) else None
        if p is None or not p.is_file():
            rows.append({"policy": h, "status": "OPAQUE", "why": "policy blob absent"})
            continue
        kind, info = classify_policy(p.read_bytes())
        if kind == "threshold":
            rows.append({"policy": h, "status": "SIGNATURES", "why": "v0.3 threshold policy"})
        elif kind == "opaque":
            rows.append({"policy": h, "status": "OPAQUE", "why": info})
        else:
            match = [r for r in reasons if r.get("check") == info.blob]
            if not match:
                rows.append({"policy": h, "status": "UNBOUND", "check": info.blob,
                             "why": f"no ski@v1 reason is this policy's compilation ({info.blob[:12]})"})
            elif decision in GATED and info.result is not True:
                rows.append({"policy": h, "status": "CONTRADICTED", "check": info.blob,
                             "why": f"{decision} while the policy answers {info.result}"})
            else:
                rows.append({"policy": h, "status": "BOUND", "check": info.blob,
                             "why": f"policy answers {info.result}; decision {decision}"})
    if not rows:
        rows.append({"policy": None, "status": "OPAQUE", "why": "cites no policy"})
    return rows


def classify_store(root):
    root = Path(root)
    out = []
    for p in sorted((root / "records").glob("*.json")):
        try:
            body = json.loads(p.read_text())["body"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for row in classify_record(body, root / "blobs"):
            out.append({"record": p.stem, "decision": body.get("decision"), **row})
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stores", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = {s: classify_store(s) for s in args.stores}
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    for s, rows in report.items():
        counts = {k: sum(r["status"] == k for r in rows) for k in ORDER}
        print(f"{s}: {len(rows)} (record, policy) pairs  " + "  ".join(f"{k} {v}" for k, v in counts.items() if v))
        for r in rows:
            if r["status"] in ("CONTRADICTED", "UNBOUND"):
                print(f"  {r['status']:12} {r['record'][:12]} {r['decision']:9} {r['why']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
