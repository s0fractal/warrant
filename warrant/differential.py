"""Differential assessment (roadmap G12): the published release n and this package assess one store under its
receiver (`.warrant/v3.json`), and their reports must be the same bytes but for the engine's identity.

    python -m warrant.differential --python N_PYTHON [--root DIR] [--declared FILE]

N_PYTHON is a Python whose site-packages hold the published warrant-graph n (installed from PyPI); it runs isolated
(-I: no script directory, no PYTHONPATH, no user site), from outside the checkout, so it imports n and never this
tree. Each report is canonical JSON. `code` (the digest of the engine's files) and `assessment` (the digest of the
operands, `code` among them) name the engine and differ whenever the engine does; every other member is compared
as bytes, after checking that each report's `assessment` is the digest of its own operands. A difference is admitted
only when FILE declares it: {"warrant": "differential/1", "differs": [MEMBER, ...], "because": TEXT}, naming exactly
the members that differ (an undeclared difference is refused, and so is a declared one that did not occur). Prints
the verdict as JSON; exit 0 SAME or DECLARED, 1 REFUSED, 2 when a report could not be made."""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import engine as E
from . import jcs as C
from .store import Store, dot_of, read_inside

FORMAT = "differential/1"
IDENTITY = ("assessment", "code")            # what names the engine, not what it found
OPERANDS = ("snapshot", "trust", "profile", "as_of", "code")
# run by N_PYTHON: the store and its receiver from argv, the report on stdout
SCRIPT = """import json, sys
from warrant import engine as E
from warrant.store import Store
dot, receiver = sys.argv[1], json.loads(sys.argv[2])
rep = E.assess(Store(dot).snapshot(), receiver["trust"], receiver["profile"], None)
sys.stdout.write(json.dumps(rep, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
"""


class Unmade(Exception):
    pass


def receiver(root):
    dot = dot_of(root)
    return dot, json.loads(read_inside(dot / "v3.json", dot))


def head_report(root):
    dot, doc = receiver(root)
    return E.assess(Store(dot).snapshot(), doc["trust"], doc["profile"], None)


def published_report(python, root, run=subprocess.run):
    """The report of the warrant-graph N_PYTHON imports, on the same store and receiver."""
    dot, doc = receiver(root)
    with tempfile.TemporaryDirectory() as away:                 # its directory: nothing of the checkout to import
        r = run([str(python), "-I", "-c", SCRIPT, str(dot), json.dumps({"trust": doc["trust"], "profile": doc["profile"]})],
                capture_output=True, cwd=away, check=False, timeout=3600)
    if r.returncode:
        raise Unmade(f"{python} exited {r.returncode}: {r.stderr.decode(errors='replace').strip()[-400:]}")
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        raise Unmade(f"{python} printed no report: {e}") from None


def compare(n, head, declared=None):
    """{verdict: SAME|DECLARED|REFUSED, differs: [member], why?}."""
    for name, rep in (("n", n), ("head", head)):
        if not isinstance(rep, dict) or rep.get("assessment") != C.doc_id({k: rep.get(k) for k in OPERANDS}):
            return {"verdict": "REFUSED", "differs": [], "why": f"the {name} report's assessment is not its operands' digest"}
    members = sorted((set(n) | set(head)) - set(IDENTITY))
    differs = [m for m in members if m not in n or m not in head or C.canon(n[m]) != C.canon(head[m])]
    if not differs and not (declared or {}).get("differs"):
        return {"verdict": "SAME", "differs": []}
    named = sorted((declared or {}).get("differs") or [])
    if named == differs:
        return {"verdict": "DECLARED", "differs": differs, "because": declared.get("because")}
    return {"verdict": "REFUSED", "differs": differs,
            "why": f"undeclared: {sorted(set(differs) - set(named))}; declared but the same: {sorted(set(named) - set(differs))}"}


def declaration(path):
    doc = json.loads(Path(path).read_text())
    if not (isinstance(doc, dict) and set(doc) == {"warrant", "differs", "because"} and doc["warrant"] == FORMAT
            and isinstance(doc["differs"], list) and all(isinstance(m, str) for m in doc["differs"]) and doc["differs"]
            and isinstance(doc["because"], str) and doc["because"].strip()):
        raise Unmade(f"{path} is not a {FORMAT} declaration {{warrant, differs: [member, ...], because}}")
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m warrant.differential", description=__doc__.split("\n\n")[0])
    ap.add_argument("--python", required=True, help="a Python with the published warrant-graph n installed")
    ap.add_argument("--root", default=".", help="the repository whose .warrant/ both releases assess")
    ap.add_argument("--declared", help=f"a {FORMAT} declaration of the members that differ")
    a = ap.parse_args(argv)
    try:
        declared = declaration(a.declared) if a.declared else None
        out = compare(published_report(a.python, a.root), head_report(a.root), declared)
    except (Unmade, OSError, ValueError) as e:
        print(json.dumps({"verdict": "UNMADE", "why": str(e)}))
        return 2
    print(json.dumps(out, sort_keys=True))
    return 0 if out["verdict"] in ("SAME", "DECLARED") else 1


if __name__ == "__main__":
    sys.exit(main())
