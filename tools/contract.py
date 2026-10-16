#!/usr/bin/env python3
"""SPEC rules as contracts: a MUST sentence, the tests that witness it, and why it is so.

WHY
---
SPEC is prose. A MUST in it is held by some test, but nothing said which one,
and nothing stopped a SPEC sentence and its test from drifting apart. Nor did
anything keep the reason a rule exists. The counterexample that forced it
lived in a CHANGELOG line, a triage table or a commit message. The method is
taken from sokol-core (docs/adr/0023, 0024, docs/contracts/), where it held
up well:

  * a contract (`contracts/<ID>.json`) names the exact SPEC sentence, its
    witnesses, and the history of decisions behind it, each with its `because`.
    A decision made on a counterexample records it: the commit it was observed
    on, what was observed and what was expected. **The red is recorded as
    evidence. CI is not made to fail to show it.**
  * the statement is bound to SPEC verbatim: editing the sentence without a new
    decision, or a contract quoting a sentence SPEC no longer has, is refused;
  * history is append-only against the base: an accepted decision cannot be
    rewritten or dropped, only followed by a new one;
  * `CONTRACTS.md` is generated from the contracts and never edited by hand.

Not here yet: an owner signature over the contracts and their witnesses'
bodies (sokol-core's witness-pin). Without it the append-only rule rests on
the base the check is given, i.e. on git. This file states that as a limit.

USAGE
    python3 tools/contract.py check [--base REF]   all predicates (history only with --base)
    python3 tools/contract.py render               rewrite CONTRACTS.md
"""
import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = "contracts"
DOC = "CONTRACTS.md"
PROFILE = "warrant.contract.v1"
FIELDS = {"profile", "id", "spec", "statement", "witnesses", "decisions", "annotations"}
DECISION_FIELDS = {"date", "because", "statement_sha256", "previous_statement_sha256",
                   "counterexample"}
CX_FIELDS = {"at", "witness", "observed", "expected"}
ID_RE = re.compile(r"^[A-Z]{2,8}-[A-Z]\d+$")
# A git revision as this tool accepts it: no option-looking or shell-shaped input.
REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/~^-]{0,199}$")


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load(root):
    out = {}
    for p in sorted((root / CONTRACTS).glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def checked_files(root):
    """Every path a check in tools/check.py runs, from its argv."""
    src = (root / "tools" / "check.py").read_text(encoding="utf-8")
    return set(re.findall(r'"((?:tests|tools|impl|integrations|proofs)/[^"]+\.py)"', src))


def witness_problem(root, w, executed):
    """None if the witness resolves and is executed by a check, else why not."""
    if w.startswith("vectors:"):
        try:
            _, path, marker = w.split(":", 2)
        except ValueError:
            return "vectors witness must be vectors:<path>:<marker>"
        p = root / path
        if not p.is_file():
            return f"{path} does not exist"
        doc = json.loads(p.read_text(encoding="utf-8"))
        rows = [r for k in ("accept", "reject") for r in doc.get(k, [])]
        if not any(marker in r.get("why", "") for r in rows):
            return f"no vector in {path} is marked {marker!r}"
        return None
    if "::" not in w:
        return "witness must be <path>::<function> or vectors:<path>:<marker>"
    path, fn = w.split("::", 1)
    p = root / path
    if not p.is_file():
        return f"{path} does not exist"
    tree = ast.parse(p.read_text(encoding="utf-8"))
    if not any(isinstance(n, ast.FunctionDef) and n.name == fn for n in ast.walk(tree)):
        return f"{path} defines no function {fn}"
    if path not in executed:
        return f"{path} is not run by any check in tools/check.py"
    return None


def decision_problems(c):
    """The decision chain: reasons, dates, links, and the statement it ends on."""
    out = []
    prev = None
    for i, d in enumerate(c["decisions"]):
        if not isinstance(d, dict) or set(d) - DECISION_FIELDS or \
                {"date", "because", "statement_sha256", "previous_statement_sha256"} - set(d):
            out.append(f"decision {i}: fields must be {sorted(DECISION_FIELDS)}")
            continue
        if not (isinstance(d["because"], str) and d["because"].strip()):
            out.append(f"decision {i}: a decision without a reason")
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(d["date"])):
            out.append(f"decision {i}: date must be YYYY-MM-DD")
        if d["previous_statement_sha256"] != prev:
            out.append(f"decision {i}: previous_statement_sha256 must be the statement "
                       f"the decision before it established ({prev})")
        cx = d.get("counterexample")
        if cx is not None and (not isinstance(cx, dict) or set(cx) != CX_FIELDS
                               or not all(isinstance(cx[k], str) and cx[k] for k in CX_FIELDS)):
            out.append(f"decision {i}: counterexample must name {sorted(CX_FIELDS)}")
        prev = d["statement_sha256"]
    if prev != sha(c["statement"]):
        out.append("the statement changed without a decision that establishes it "
                   "(the last decision's statement_sha256 is not the statement's hash)")
    return out


def contract_problems(root, cid, c, spec, executed):
    """Every predicate on one contract except history."""
    required = {"profile", "id", "spec", "statement", "witnesses", "decisions"}
    if set(c) - FIELDS or required - set(c):
        return [f"fields must be {sorted(FIELDS)} (annotations optional)"]
    out = []
    if c["profile"] != PROFILE:
        out.append(f"profile must be {PROFILE}")
    if c["id"] != cid or not ID_RE.match(cid):
        out.append("id must match the file name and the form AAA-X1")
    if not isinstance(c["statement"], str) or c["statement"] not in spec:
        out.append("statement is not a verbatim sentence of SPEC.md")
    if not (isinstance(c["witnesses"], list) and c["witnesses"]):
        out.append("witnesses must be a nonempty list")
    else:
        out += [f"witness {w}: {why}" for w in c["witnesses"]
                for why in [witness_problem(root, w, executed)] if why]
    if not (isinstance(c["decisions"], list) and c["decisions"]):
        return out + ["decisions must be a nonempty list"]
    return out + decision_problems(c)


def problems(root, contracts):
    """Every predicate except history. A list of (contract id, message)."""
    spec = (root / "SPEC.md").read_text(encoding="utf-8")
    executed = checked_files(root)
    out = [(cid, msg) for cid, c in contracts.items()
           for msg in contract_problems(root, cid, c, spec, executed)]
    doc = root / DOC
    if not doc.is_file() or doc.read_text(encoding="utf-8") != render(contracts):
        out.append(("*", f"{DOC} is not what the contracts render (python3 tools/contract.py render)"))
    return out


def history_problems(root, contracts, base):
    """Append-only against `base`: no contract vanishes, no decision is rewritten."""
    out = []
    if not REF_RE.match(base):
        return [("*", f"refusing base {base!r}: not a plain git revision")]
    r = subprocess.run(["git", "-C", str(root), "ls-tree", "-r", "--name-only", base, CONTRACTS + "/"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [("*", f"cannot read {CONTRACTS}/ at {base}: {r.stderr.strip()}")]
    for path in r.stdout.split():
        cid = Path(path).stem
        old = json.loads(subprocess.run(["git", "-C", str(root), "show", f"{base}:{path}"],
                                        capture_output=True, text=True, check=True).stdout)
        if cid not in contracts:
            out.append((cid, f"present at {base} and gone now; retire a contract, never delete it"))
            continue
        new_ds, old_ds = contracts[cid].get("decisions", []), old.get("decisions", [])
        if new_ds[:len(old_ds)] != old_ds:
            out.append((cid, f"decision history at {base} was rewritten; only appending is allowed"))
    return out


def render(contracts):
    lines = ["# Contracts", "",
             "<!-- Generated by tools/contract.py from contracts/*.json. Never edit by hand. -->", "",
             "Each row binds one MUST sentence of SPEC.md to the tests that witness it and to",
             "the decisions behind it. A decision made on a counterexample records where it was",
             "observed and what was seen. `python3 tools/contract.py check` holds all of it.", "",
             "| ID | SPEC | Statement | Witnesses | Decisions |", "|---|---|---|---|---|"]
    for cid, c in sorted(contracts.items()):
        st = c.get("statement", "")
        short = st.split(". ")[0].replace("**", "")[:110].replace("|", "\\|")
        ws = "<br>".join(f"`{w}`" for w in c.get("witnesses", []))
        lines.append(f"| {cid} | {c.get('spec', '')} | {short}… | {ws} | {len(c.get('decisions', []))} |")
    lines += ["", "## Decisions", ""]
    for cid, c in sorted(contracts.items()):
        for i, d in enumerate(c.get("decisions", [])):
            lines.append(f"- **{cid} #{i}** ({d.get('date')}): {d.get('because')}")
            cx = d.get("counterexample")
            if cx:
                lines.append(f"  - counterexample at `{cx['at']}` via `{cx['witness']}`: "
                             f"observed {cx['observed']}; expected {cx['expected']}")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--base", help="git ref whose decision histories must be a prefix of ours")
    sub.add_parser("render")
    a = ap.parse_args(argv)
    contracts = load(ROOT)
    if a.cmd == "render":
        (ROOT / DOC).write_text(render(contracts), encoding="utf-8")
        print(f"{DOC} written: {len(contracts)} contracts")
        return 0
    found = problems(ROOT, contracts)
    if a.base:
        found += history_problems(ROOT, contracts, a.base)
    for cid, msg in found:
        print(f"FAIL  {cid}: {msg}")
    hist = f"history checked against {a.base}" if a.base else "history NOT checked (no --base)"
    print(f"\nCONTRACTS: {'ALL HOLD' if not found else 'VIOLATED'} "
          f"({len(contracts)} contracts; {hist})")
    return 0 if not found else 1


if __name__ == "__main__":
    sys.exit(main())
