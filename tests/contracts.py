#!/usr/bin/env python3
"""tools/contract.py refuses what it says it refuses. Each predicate has a control.

Every case copies the files the contracts depend on into a scratch git
repository, commits them as the base, breaks one thing, and requires
`contract.py` to report it. The unbroken copy must hold. A check that cannot
fail is a label, not a check.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import contract as C  # noqa: E402

ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def scratch():
    tmp = Path(tempfile.mkdtemp(prefix="contracts-"))
    files = {"SPEC.md", "CONTRACTS.md", "tools/check.py", "examples/signature-vectors.json"}
    for c in C.load(ROOT).values():
        for w in c["witnesses"]:
            files.add(w.split("::")[0] if "::" in w else w.split(":")[1])
    for f in files:
        (tmp / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, tmp / f)
    shutil.copytree(ROOT / "contracts", tmp / "contracts")
    git = ["git", "-C", str(tmp), "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(git[:3] + ["init", "-q"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "base"], check=True)
    return tmp


def verdict(tmp):
    cs = C.load(tmp)
    return C.problems(tmp, cs) + C.history_problems(tmp, cs, "HEAD")


def edit_json(tmp, cid, fn):
    p = tmp / "contracts" / f"{cid}.json"
    d = json.loads(p.read_text())
    fn(d)
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def case(label, mutate, needle):
    tmp = scratch()
    mutate(tmp)
    found = verdict(tmp)
    hit = [m for _, m in found if needle in m]
    check(f"refused: {label}", hit, found)
    shutil.rmtree(tmp, ignore_errors=True)


def main():
    tmp = scratch()
    v = verdict(tmp)
    check("the unbroken copy holds", not v, v)
    shutil.rmtree(tmp, ignore_errors=True)

    def spec_edit(t):
        p = t / "SPEC.md"
        p.write_text(p.read_text().replace("A verifier MUST NOT use the cofactored equation",
                                           "A verifier SHOULD NOT use the cofactored equation"))
    case("a SPEC sentence edited under its contract", spec_edit, "not a verbatim sentence")

    def statement_only(t):
        def f(d):
            d["statement"] = d["statement"][:-1]
        edit_json(t, "KEY-C1", f)
    case("a statement changed without a decision", statement_only, "changed without a decision")

    def rewrite(t):
        def f(d):
            d["decisions"][0]["because"] = "nothing happened"
        edit_json(t, "KEY-P1", f)
    case("an accepted decision rewritten against the base", rewrite, "was rewritten")

    def drop(t):
        (t / "contracts" / "SIG-E1.json").unlink()
    case("a contract deleted instead of retired", drop, "never delete it")

    def no_reason(t):
        def f(d):
            d["decisions"].append({"date": "2026-10-17", "because": " ",
                                   "statement_sha256": d["decisions"][-1]["statement_sha256"],
                                   "previous_statement_sha256": d["decisions"][-1]["statement_sha256"]})
        edit_json(t, "KEY-C1", f)
    case("a decision without a reason", no_reason, "without a reason")

    def broken_chain(t):
        def f(d):
            d["decisions"].append({"date": "2026-10-17", "because": "x",
                                   "statement_sha256": d["decisions"][-1]["statement_sha256"],
                                   "previous_statement_sha256": "0" * 64})
        edit_json(t, "KEY-C1", f)
    case("a decision that does not chain to the one before", broken_chain, "previous_statement_sha256")

    def witness_gone(t):
        p = t / "tests" / "r13_retired_key_denial.py"
        p.write_text(p.read_text().replace("def case_terminal(", "def case_terminal_renamed("))
    case("a witness function that no longer exists", witness_gone, "defines no function")

    def unrun(t):
        p = t / "tools" / "check.py"
        p.write_text(p.read_text().replace('"tests/r13_retired_key_denial.py"', '"tests/elsewhere.py"'))
    case("a witness whose file no check runs", unrun, "not run by any check")

    def no_vectors(t):
        p = t / "examples" / "signature-vectors.json"
        p.write_text(p.read_text().replace("EDGE:", "EGDE:"))
    case("a vectors witness with no marked vector", no_vectors, "no vector in")

    def hand_edit(t):
        p = t / "CONTRACTS.md"
        p.write_text(p.read_text() + "\n| KEY-X9 | §0 | invented |\n")
    case("CONTRACTS.md edited by hand", hand_edit, "is not what the contracts render")

    def bad_cx(t):
        def f(d):
            d["decisions"][0]["counterexample"]["observed"] = ""
        edit_json(t, "SIG-E1", f)
    case("a counterexample missing what was observed", bad_cx, "counterexample must name")

    print(f"\nCONTRACTS-CONTROLS: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
