#!/usr/bin/env python3
"""Each mutant of impl/grants.py or impl/loops.py undoes one S3 rule and must make
ITS case of tests/grants_test.py fail (via tests/mutant_runner.py).

    python3 tests/grants_mutants.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutant_runner import campaign  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {f: (ROOT / "impl" / f).read_text() for f in ("grants.py", "loops.py")}

MUTANTS = [
    ("G01", "loops.py", "a valid grant does not authorize a release",
     [('        return ("ADMITTED", f"by grant {gid[:12]}") if gid else', '        return ("OVERCLAIMED", "x") if gid else')]),
    ("G02", "grants.py", "any root is accepted",
     [('            return ("VALID", "root") if gid in self.roots else', '            return ("VALID", "root") if True else')]),
    ("G05", "grants.py", "acts need not be delegable by the parent",
     [('    if not set(g["acts"]) <= set(p["delegable"]):', '    if not set(g["acts"]) <= set(p["acts"]):')]),
    ("G06", "grants.py", "anyone may attenuate a grant",
     [('    if g["grantor"] != p["grantee"]:', '    if False:')]),
    ("G07", "grants.py", "a child may widen the scope",
     [('    if not set(g["duties"]) <= set(p["duties"]):', '    if False:')]),
    ("G08", "grants.py", "expiry is ignored",
     [('        if g["expires"] is not None and at >= g["expires"]:', '        if False:')]),
    ("G09", "grants.py", "a child may outlive its parent",
     [('    if p["expires"] is not None and (g["expires"] is None or g["expires"] > p["expires"]):', '    if False:')]),
    ("G10", "grants.py", "a grant counts before it was issued",
     [('        if ts > at:\n            return "NOT_YET", "granted after this position"\n', '')]),
    ("G11", "loops.py", "a grant need not be signed by its grantor",
     [('            if why is None and body["actor"]["id"] != doc["grantor"]:', '            if False:')]),
    ("G13", "grants.py", "a grant's duties are not consulted",
     [('        if g["grantee"] != actor or act not in g["acts"] or duty not in g["duties"]:',
       '        if g["grantee"] != actor or act not in g["acts"]:')]),
    ("G14", "grants.py", "acts are tested for membership before type",
     [('    if not (_strs_sorted_unique(g["acts"], lambda a: a in ACTS) and g["acts"]):',
       '    if not (set(g["acts"]) <= ACTS and g["acts"]):')]),
    ("G17", "loops.py", "the grant evaluator is not in the assessment identity (GR-01)",
     [('             "grant_evaluator": GR.EVALUATOR,\n', '')]),
    ("G15", "grants.py", "the parent is judged at the act's position, not the child's",
     [('        pst, why = self.state(g["parent"], ts, depth + 1)', '        pst, why = self.state(g["parent"], at, depth + 1)')]),
]


def prepare(tmp, srcs):
    for f, text in srcs.items():
        (tmp / f).write_text(text)
    return {"GRANTS_IMPL": str(tmp)}


if __name__ == "__main__":
    sys.exit(campaign("GRANT MUTANTS", MUTANTS, SOURCES, prepare, ROOT / "tests" / "grants_test.py", "GRANTS_RESULTS"))
