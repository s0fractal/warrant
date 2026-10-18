#!/usr/bin/env python3
"""Each mutant of impl/loops.py undoes one revalidation rule and must make ITS case of
tests/revalidation_test.py fail (via tests/mutant_runner.py).

    python3 tests/revalidation_mutants.py

Rules shared with ordinary closures (holder or delegate files; the creditor's
acceptance is required) are killed by the loops campaign, not repeated here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutant_runner import campaign  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {"loops.py": (ROOT / "impl" / "loops.py").read_text()}

MUTANTS = [
    ("V01", "loops.py", "a revalidation supersedes nothing: fired triggers stay current",
     [('"current": tid not in superseded}', '"current": True}')]),
    ("V03", "loops.py", "a revalidation may name any transition",
     [('        if not set(m["revalidates"]) <= set(state["admitted"]):', '        if False:')]),
    ("V04", "loops.py", "a revalidation is judged without any admitted closure",
     [('        if not state["admitted"]:\n            return "OVERCLAIMED", "nothing admitted to revalidate"\n', '')]),
    ("V07", "loops.py", "a revalidation supersedes every closure, named or not",
     [('        superseded = {x for rv in revalidations for x in rv[5]} if kinds[0] == "DISCHARGED" else set()',
       '        superseded = {c[1] for c in chosen} if revalidations and kinds[0] == "DISCHARGED" else set()')]),
    ("V08", "loops.py", "a REVALIDATED mapping need not name what it revalidates",
     [('        if (m["disposition"] == "REVALIDATED") != ("revalidates" in m):\n            return "revalidates"\n', '')]),
    ("V09", "loops.py", "a revalidation's basis is not checked against the duty",
     [('    if [admit_as, claimed] not in d["admits"]:',
       '    if disp != "REVALIDATED" and [admit_as, claimed] not in d["admits"]:')]),
    ("V10", "loops.py", "a revalidation may name a closure admitted after it",
     [('        if verdict == "ADMITTED" and m["disposition"] == "REVALIDATED":\n            verdict, why = _revalidation_order(',
       '        if False:\n            verdict, why = _revalidation_order(')]),
    ("V11", "loops.py", "a predecessor's admission position is its filing position (RV-01)",
     [('    pos = (tbody["ts"], t_id)\n    got = view.accepted_at(did, t_id, i, m["evidence"])\n    for actor in d["acceptance"]:',
       '    pos = (tbody["ts"], t_id)\n    got = view.accepted_at(did, t_id, i, m["evidence"])\n    for actor in d["acceptance"] if m["disposition"] == "REVALIDATED" else ():')]),
    ("V13", "loops.py", "revalidations are judged against the final holder and delegates (RV-02)",
     [('            state["holder"], state["delegates"] = h, set(dl)\n', '')]),
    ("V16", "loops.py", "a transfer takes effect at its filing, not at its last required consent",
     [('    pos = max((tbody["ts"], t_id), got.get(m["to"], (tbody["ts"], t_id)))',
       '    pos = (tbody["ts"], t_id)'),
      ('    if m["disposition"] == "SUBSTITUTED" and creditors:', '    if False:')]),
]


def prepare(tmp, srcs):
    (tmp / "loops.py").write_text(srcs["loops.py"])
    return {"REVAL_IMPL": str(tmp)}


if __name__ == "__main__":
    sys.exit(campaign("REVALIDATION MUTANTS", MUTANTS, SOURCES, prepare, ROOT / "tests" / "revalidation_test.py",
                      "REVAL_RESULTS"))
