#!/usr/bin/env python3
"""WRT-020 reference profile: does a decision follow from the policy it cites?

    python3 impl/policy_binding.py STORE [STORE ...] [--json]

Warrant pins the policy a record cites (`under`) and re-runs the record's
`ski@v1` reasons, but nothing connects the two. A reason can be an unrelated
computation, and the decision can disagree with the policy's own answer. Both
verify clean today (tests/countermodel_policy_binding.py, and an `accept` whose
reason replays the policy's FALSE). This profile reports, for every record and
every policy blob it cites, one of:

    BOUND         the policy is WPL; a ski@v1 reason of the record runs its
                  compilation (same term, same expected answer, at least the
                  budget it needs), and the decision does not contradict the
                  policy's answer
    CONTRADICTED  as BOUND, but the record ACCEPTS while the policy answers false
    UNBOUND       the policy is WPL, but no ski@v1 reason runs its term with its
                  answer and enough budget; the row says which, when one came
                  close
    OPAQUE        the policy is not machine-readable (prose, any other bytes):
                  compliance is NOT CHECKED, and is reported as such
    SIGNATURES    a v0.3 threshold policy: it governs who signs, which settlement
                  already enforces; there is no computation to bind

The CLI exits 1 when any pair is CONTRADICTED, else 0.

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
    except ValueError:               # UnicodeDecodeError is a ValueError
        pass
    if len(raw) > MAX_POLICY_BYTES:
        return "opaque", "larger than the profile reads"
    try:
        src = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "opaque", "not UTF-8"
    seen = {}

    def put(b):
        # Keeps the bytes in memory and nothing else: the profile must not write
        # to the store it reads, and without a put the compiler emits no check.
        h = hashlib.sha256(b).hexdigest()
        seen[h] = b
        return h
    try:
        c = WPL.compile_source(src, put)
        return "wpl", (c, json.loads(seen[c.blob]))
    except WPL.PolicyError as e:
        return "opaque", f"not WPL: {str(e).splitlines()[0][:80]}"
    except (WPL.CompilerBug, RecursionError, ValueError) as e:
        return "opaque", f"did not compile: {type(e).__name__}"


def runs_policy(reason, want, blobs):
    """True if this reason's check runs the policy: the same term and the same
    expected answer as the policy's own compilation, with at least the budget
    that compilation needs. `atp` is a budget, not part of what is computed:
    compiling with headroom (a permitted option) raises it and changes the check
    hash, so the hash is not the binding. Otherwise False, or a string naming a
    near miss worth reporting."""
    h = reason.get("check")
    p = blobs / h if isinstance(h, str) else None
    if p is None or not p.is_file():
        return False
    try:
        got = json.loads(p.read_bytes())
    except ValueError:               # UnicodeDecodeError is a ValueError
        return False
    if not isinstance(got, dict) or got.get("ski") != want["ski"] or got.get("term") != want["term"]:
        return False
    if got.get("expect") != want["expect"]:
        return "a reason runs this policy's term but pins a different answer"
    atp = got.get("atp")
    if not isinstance(atp, int) or isinstance(atp, bool) or atp < want["atp"]:
        return f"a reason runs this policy's term with less than the {want['atp']} ATP it needs"
    if reason.get("verdict") != "pass":
        return "a reason runs this policy but does not claim pass"
    return True


def _wpl_row(h, info, reasons, decision, blobs):
    compiled, want = info
    row = {"policy": h, "term": want["term"]}
    verdicts = [runs_policy(r, want, blobs) for r in reasons]
    if True not in verdicts:
        why = next((v for v in verdicts if isinstance(v, str)), None)
        return {**row, "status": "UNBOUND",
                "why": why or f"no ski@v1 reason runs this policy's term ({want['term'][:12]})"}
    if decision in GATED and compiled.result is not True:
        return {**row, "status": "CONTRADICTED", "why": f"{decision} while the policy answers {compiled.result}"}
    return {**row, "status": "BOUND", "why": f"policy answers {compiled.result}; decision {decision}"}


def _policy_row(h, reasons, decision, blobs):
    p = blobs / h if isinstance(h, str) else None
    if p is None or not p.is_file():
        return {"policy": h, "status": "OPAQUE", "why": "policy blob absent"}
    kind, info = classify_policy(p.read_bytes())
    if kind == "threshold":
        return {"policy": h, "status": "SIGNATURES", "why": "v0.3 threshold policy"}
    if kind == "opaque":
        return {"policy": h, "status": "OPAQUE", "why": info}
    return _wpl_row(h, info, reasons, decision, blobs)


def classify_record(body, blobs):
    reasons = [r for r in body.get("because", []) if isinstance(r, dict)
               and r.get("kind") == "check" and r.get("runtime") == "ski@v1"]
    rows = [_policy_row(h, reasons, body.get("decision"), blobs) for h in body.get("under", [])]
    return rows or [{"policy": None, "status": "OPAQUE", "why": "cites no policy"}]


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
    # Exit 1 when a decision contradicts its own policy: the one status that is a
    # defect of the record rather than an absence of evidence.
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 1 if any(r["status"] == "CONTRADICTED" for rows in report.values() for r in rows) else 0


def print_report(report):
    for s, rows in report.items():
        counts = {k: sum(r["status"] == k for r in rows) for k in ORDER}
        print(f"{s}: {len(rows)} (record, policy) pairs  " + "  ".join(f"{k} {v}" for k, v in counts.items() if v))
        for r in rows:
            if r["status"] in ("CONTRADICTED", "UNBOUND"):
                print(f"  {r['status']:12} {r['record'][:12]} {r['decision']:9} {r['why']}")


if __name__ == "__main__":
    sys.exit(main())
