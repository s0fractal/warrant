#!/usr/bin/env python3
"""The specification's claims as claim@1 records: each normative sentence of docs/V3.md is a lineage
whose versions carry the sentence verbatim, the section, the witnesses (test cases `file_test:CASE`) and
the mutants (ids of tests/mutants.py) that back it. A `backed` version waits for a claim/verifier's
acceptance: the claims checker (`replay`) accepts it after it ran the witnesses and the mutants at one
commit, naming that commit, its tree, the checker's code and its environment. The Warrant 2 claims (source
SPEC.md) are history: retired, never deleted.

    python3 tools/claims.py check                      # the store, and every live claim against the spec and tests
    python3 tools/claims.py view [--out FILE]          # CLAIMS.md, a build artifact
    python3 tools/claims.py file --from FILE.json --actor A --key SEED     # file new claims or new versions
    python3 tools/claims.py retire-v2 --actor A --key SEED                 # retire every live Warrant 2 claim
    python3 tools/claims.py identity                   # the claims checker's actor, code and environment
    python3 tools/claims.py replay --key -             # the checker: run, then accept what held (clean tree only)
    python3 tools/claims.py verify --base M            # CI: re-execute the checker's acceptances new since M

`check` refuses (exit 1): a store that is not canonical, rejects a line or has a problem (a schema short of its
quorum is a proposal, not one); a live claim not of docs/V3.md (V2_CLAIM_LIVE), whose sentence is not in docs/V3.md
(CLAIM_TEXT_MISSING), that cites a witness case no test file prints (WITNESS_MISSING), a mutant not in
tests/mutants.py (UNKNOWN_MUTANT) or one whose cases are not among its witnesses (MUTANT_OFF_CLAIM); a
`backed` claim with no witness or no mutant (UNBURNED); one id in two live lineages (CLAIM_ID_TWICE). It
never parses the spec to find claims: the records say where they are, and the spec must hold their words."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from repo import ROOT, Failed, Repo, checker_problem, code_tree, dump, git, identity, inside, load_key, main, tree_id

from warrant import records as R

SOURCE = "docs/V3.md"
V2_SOURCE = "SPEC.md"
CHECKER = "claims-checker"            # the claims checker's actor: one key, bound once; its code is in each attest
CHECKER_FILES = ("tools/claims.py", "tools/repo.py", "warrant")
CASE_LINE = re.compile(r"""check\(\s*f?["']([A-Za-z0-9-]+)[ "']""")


def harness(root=ROOT):
    out = subprocess.run([sys.executable, str(root / "tests" / "mutants.py"), "--list"], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def cases(root=ROOT):
    """{test file name: {case ids}} printed by check(...) calls in tests/*_test.py and the plugin tests."""
    out = {}
    for p in sorted((root / "tests").glob("*_test.py")) + sorted((root / "integrations").glob("*/test_plugin.py")):
        name = p.stem if p.parent.name == "tests" else f"{p.parent.name}/{p.stem}"
        out[name] = set(CASE_LINE.findall(p.read_text()))
    return out


def live(rep):
    """{lineage: leaf body} of the claim@1 lineages not retired (a forked one under its root's body)."""
    recs = rep["_recs"]
    return {L: recs[lin["leaf"] or L]["body"] for L, lin in rep["lineages"].items()
            if lin["schema"] == "claim@1" and (recs[lin["leaf"]]["body"]["state"] if lin["leaf"] else None) != "retired"}


def store_problems(rep):
    out = []
    if not rep["canonical"]:
        out.append(("NOT_CANONICAL", "records.jsonl is not in canonical order: `python3 -m warrant fmt`"))
    out += [("REJECTED", f"{i[:12]} {w[:120]}") for i, w in rep["rejected"].items()]
    out += [(c, f"{str(i)[:12]} {d[:120]}") for c, i, d in rep["problems"]]
    return out          # a schema awaiting backers (schemas_pending) is a proposal, not a problem: no claim rests on it


def check(repo):
    rep = repo.report()
    out = store_problems(rep)
    spec = (repo.root / SOURCE).read_text()
    known, printed = harness(repo.root), cases(repo.root)
    ids = {}
    for L, b in sorted(live(rep).items()):
        lin = rep["lineages"][L]
        tag = f"{b.get('id')} ({L[:12]})"
        if lin["verdict"] == "FORK":
            out.append(("CLAIM_FORK", tag))
        if b["source"] != SOURCE:
            out.append(("V2_CLAIM_LIVE" if b["source"] == V2_SOURCE else "CLAIM_SOURCE", f"{tag} is of {b['source']}"))
            continue
        ids.setdefault(b["id"], []).append(L)
        if b["text"] not in spec:
            out.append(("CLAIM_TEXT_MISSING", f"{tag}: its sentence is not in {SOURCE}"))
        ws = b["witnesses"]
        for w in ws:
            f, _, c = w.partition(":")
            if c not in printed.get(f, set()):
                out.append(("WITNESS_MISSING", f"{tag}: {w} is printed by no test"))
        for m in b["mutants"]:
            if m not in known:
                out.append(("UNKNOWN_MUTANT", f"{tag}: {m}"))
            elif not {f"{witness_of(m, known)}:{c}" for c in known.get(m, ["", "", []])[2]} & set(ws):
                out.append(("MUTANT_OFF_CLAIM", f"{tag}: {m} fails {known.get(m)}, none a witness of the claim"))
        if b["state"] == "backed" and not (ws and b["mutants"]):
            out.append(("UNBURNED", f"{tag} is backed with {len(ws)} witness(es) and {len(b['mutants'])} mutant(s)"))
    out += [("CLAIM_ID_TWICE", f"{i} in {len(Ls)} lineages") for i, Ls in sorted(ids.items()) if len(Ls) > 1]
    return rep, out


def witness_of(m, known):
    """The name a witness gives a mutant's test file: tests/x_test.py is x_test, integrations/P/test_plugin.py is
    P/test_plugin."""
    f = Path(known.get(m, ["", "tests/none"])[1])           # total: an unknown id names no file
    return f.stem if f.parts[0] == "tests" else f"{f.parent.name}/{f.stem}"


def test_path(name, root=ROOT):
    return root / "tests" / f"{name}.py" if "/" not in name else root / "integrations" / f"{name}.py"


def checked(rep):
    """{version: [commits]} of the claims checker's signed acceptances."""
    out = {}
    for i, r in sorted(rep["_recs"].items()):
        if r["kind"] == "attest" and r["actor"] == CHECKER and rep["_basis"].get(i) == "SIGNED" and r["body"].get("verdict") == "accept":
            out.setdefault(r["body"]["target"], []).append(r["body"].get("commit"))
    return out


def at_tree(root, commits, here):
    """Whether one of `commits` has the code `here` (a tree outside .warrant/); a commit not in this clone has not."""
    for x in commits:
        try:
            if code_tree(root, x) == here:
                return True
        except (subprocess.CalledProcessError, TypeError):
            continue
    return False


def view(rep, root=None):
    recs = rep["_recs"]
    done, here = checked(rep), code_tree(root, "HEAD") if root is not None else None
    lines = ["# Claims of docs/V3.md", "", f"Generated from `.warrant/records.jsonl` (snapshot `{rep['snapshot'][:12]}`, "
             f"assessment `{rep['assessment'][:12]}`); a build artifact, never committed.", ""]
    rows = sorted(((b["section"], b["id"], L, b) for L, b in live(rep).items() if b["source"] == SOURCE),
                  key=lambda r: ([int(x) if x.isdigit() else x for x in r[0].split(".")], r[1]))
    for section, cid, L, b in rows:
        lin = rep["lineages"][L]
        g = rep["versions"].get(lin["leaf"] or L, {})
        state = f"{lin['state'] or 'none effective'}, leaf {b['state']} {g.get('guard')}"
        if root is not None and done.get(lin["leaf"]):
            xs = done[lin["leaf"]]
            state += ", checked at this tree" if at_tree(root, xs, here) else f", checked at {', '.join(str(x)[:12] for x in xs)}, not this tree"
        lines += [f"- **{cid}** (§{section}; {state}; {lin['reliance']}) {b['text']}",
                  f"  witnesses: {', '.join(b['witnesses']) or 'none'}; mutants: {', '.join(b['mutants']) or 'none'}"
                  + (f"; why unbacked: {b['reason']}" if b.get("reason") else "")]
    v2 = sum(1 for L, lin in rep["lineages"].items() if lin["schema"] == "claim@1" and recs[L]["body"]["source"] == V2_SOURCE)
    lines += ["", f"Warrant 2 claims (SPEC.md, history: retired): {v2} lineages."]
    return "\n".join(lines) + "\n"


def schema_guard(rep, state):
    return rep["_recs"][rep["schemas"]["claim@1"]]["body"]["states"][state]


def file_claims(repo, actor, key, doc):
    """File each claim of `doc` ([{id, section, text, witnesses, mutants, state?, reason?}]) as a new lineage, or a
    new version of the live lineage with its id when anything differs; unchanged ones are skipped."""
    rep = repo.report()
    by_id = {b["id"]: L for L, b in live(rep).items() if b["source"] == SOURCE}
    recs = []
    for c in doc:
        state = c.get("state", "backed")
        body = {"state": state, "id": c["id"], "source": SOURCE, "section": c["section"], "text": c["text"],
                "witnesses": c["witnesses"], "mutants": c["mutants"], **({"reason": c["reason"]} if c.get("reason") else {})}
        L = by_id.get(c["id"])
        leaf = rep["lineages"][L]["leaf"] if L else None
        if leaf and rep["_recs"][leaf]["body"] == body:
            continue
        recs.append(R.record("entity", actor, 0, body, "claim@1", lineage=leaf, guard=schema_guard(rep, state)))
    return repo.file(actor, key, recs)


def retire_v2(repo, actor, key):
    rep = repo.report()
    recs = []
    for L, b in sorted(live(rep).items()):
        lin = rep["lineages"][L]
        if b["source"] != V2_SOURCE or lin["leaf"] is None or rep["_recs"][L]["actor"] != actor:
            continue
        body = dict(b, state="retired", reason="a Warrant 2 claim (SPEC.md 2.0.0a1, history/warrant-2-2026-10-27): "
                    "Warrant 3 replaced the engine it is about; docs/V3.md's claims are the current ones")
        for k in ("established", "residual", "opened", "subject", "because", "counter", "challenge", "evidence"):
            body.pop(k, None)
        recs.append(R.record("entity", actor, 0, body, "claim@1", lineage=lin["leaf"], refs=R.body_refs({}, body)))
    return repo.file(actor, key, recs)


def run_checks(root, witnesses, mutants):
    """({test file: cases printed `ok`}, {mutant: matrix row}) of running `witnesses`' test files and `mutants` in
    the checkout `root`."""
    ran = {}
    for f in sorted({w.split(":")[0] for w in witnesses}):
        r = subprocess.run([sys.executable, "-B", str(test_path(f, root))], cwd=root, capture_output=True, text=True, timeout=1800)
        ran[f] = {ln.split()[1] for ln in r.stdout.splitlines() if ln.startswith("ok   ")}
    killed = {}
    if mutants:
        out = Path(root) / "build" / "claims-replay-matrix.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.unlink(missing_ok=True)
        subprocess.run([sys.executable, str(Path(root) / "tests" / "mutants.py"), *sorted(mutants), "--matrix", str(out)], cwd=root,
                       capture_output=True, text=True, timeout=7200)
        killed = {r["id"]: r for r in json.loads(out.read_text())["rows"]} if out.is_file() else {}
    return ran, killed


def held(b, ran, killed):
    return all(w.split(":")[1] in ran.get(w.split(":")[0], set()) for w in b["witnesses"]) and all(
        killed.get(m, {}).get("outcome") == "KILLED" for m in b["mutants"])


def replay(repo, key, root=ROOT):
    """The claims checker at a clean commit: each live `backed` claim whose leaf waits, or whose acceptances by the
    checker are all at another tree, is accepted when every witness case passes and every mutant it cites is
    killed on one of its cases, in this tree. Each acceptance names the commit, its tree, the checker's code and
    its environment."""
    me = identity(CHECKER_FILES, root)
    trust, _, _ = repo.config()
    if key.public not in trust["keys"].get(CHECKER, []):
        raise Failed("SIGNER", f"the seed's key is not one .warrant/v3.json binds to {CHECKER}")
    commit, tree = tree_id(root)
    rep, problems = check(repo)
    if problems:
        raise Failed("CHECK", f"{len(problems)} problem(s): the checker accepts nothing over a failing check")
    done, here = checked(rep), code_tree(root, commit)
    todo = {L: b for L, b in live(rep).items() if b["state"] == "backed" and (
        rep["versions"][rep["lineages"][L]["leaf"]]["guard"] == "PENDING" or not at_tree(root, done.get(rep["lineages"][L]["leaf"], []), here))}
    ran, killed = run_checks(root, [w for b in todo.values() for w in b["witnesses"]], {m for b in todo.values() for m in b["mutants"]})
    recs = []
    for L, b in sorted(todo.items()):
        ok = held(b, ran, killed)
        if ok:
            leaf = rep["lineages"][L]["leaf"]
            recs.append(R.record("attest", CHECKER, 0, {"target": leaf, "verdict": "accept", "commit": commit, "tree": tree, **me,
                                                        "witnesses": b["witnesses"], "mutants": b["mutants"]}, refs=[leaf]))
        print(f"{'ACCEPT' if ok else 'HELD  '} {b['id']} {L[:12]}")
    return repo.file(CHECKER, key, recs)


def verify(repo, base):
    """Re-execute every acceptance the claims checker signed since commit `base`, in a temporary worktree of the
    commit it names: its `code` must be the checker's code at that commit (CODE_DIFFERS), its witnesses and mutants
    those of the version it accepts, and every witness must pass and every mutant be killed there again
    (CLAIM_REPLAY_DIFFERS). Acceptances by a person (codex) are trust decisions, not re-executed."""
    import gate as GT                   # verify only: the checker's own run (replay) does not load the gate
    old, _ = GT.store_at(repo.root, base)
    rep = repo.report()
    recs, bad, by_commit = rep["_recs"], [], {}
    for i, r in sorted(recs.items()):
        if r["kind"] != "attest" or r["actor"] != CHECKER or i in old.lines or rep["_basis"].get(i) != "SIGNED":
            continue
        b, v = r["body"], recs.get(r["body"].get("target"))
        why = checker_problem(b, CHECKER_FILES, repo.root)
        if why is None and not (v and v["kind"] == "entity" and v["schema"] == "claim@1"
                                and (b.get("witnesses"), b.get("mutants")) == (v["body"]["witnesses"], v["body"]["mutants"])):
            why = "lists other witnesses or mutants than the claim version it accepts"
        if why:
            bad.append(f"{i[:12]}: {why}")
        else:
            by_commit.setdefault(b["commit"], []).append((i, v["body"]))
    for x, rows in sorted(by_commit.items()):
        wt = Path(repo.root) / "build" / f"verify-claims-{os.getpid()}-{x[:12]}"      # the checkout's own scratch, ignored
        git(repo.root, "worktree", "add", "--detach", "--quiet", str(wt), x)
        try:
            ran, killed = run_checks(wt, [w for _, b in rows for w in b["witnesses"]], {m for _, b in rows for m in b["mutants"]})
        finally:
            git(repo.root, "worktree", "remove", "--force", str(wt))
        bad += [f"{i[:12]}: CLAIM_REPLAY_DIFFERS {b['id']} does not hold at {x[:12]}" for i, b in rows if not held(b, ran, killed)]
    if bad:
        raise Failed("CLAIM_REPLAY_DIFFERS", "; ".join(bad))
    return sum(len(rows) for rows in by_commit.values())


def run(argv=None):
    ap = argparse.ArgumentParser(prog="claims.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    v = sub.add_parser("view")
    v.add_argument("--out")
    f = sub.add_parser("file")
    f.add_argument("--from", dest="src", required=True)
    rt = sub.add_parser("retire-v2")
    for p in (f, rt):
        p.add_argument("--actor", required=True)
        p.add_argument("--key", required=True)
    sub.add_parser("identity")
    r = sub.add_parser("replay")
    r.add_argument("--key", required=True)
    vf = sub.add_parser("verify")
    vf.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    repo = Repo()
    if a.cmd == "identity":
        dump({"actor": CHECKER, **identity(CHECKER_FILES)})
        return 0
    if a.cmd == "verify":
        print(f"claims checker acceptances new since {a.base[:12]}: {verify(repo, a.base)} re-executed, all held")
        return 0
    if a.cmd == "check":
        rep, out = check(repo)
        for c, d in out:
            print(f"{c} {d}")
        n = len([1 for b in live(rep).values() if b["source"] == SOURCE])
        print(f"claims: {n} live of {SOURCE}; {len(out)} problem(s)")
        return 1 if out else 0
    if a.cmd == "view":
        text = view(repo.report(), repo.root)
        if a.out:
            out = inside(a.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text)
        else:
            sys.stdout.write(text)
        return 0
    key = load_key(a.key)
    if a.cmd == "replay":
        dump({"filed": replay(repo, key)})
    elif a.cmd == "file":
        dump({"filed": file_claims(repo, a.actor, key, json.loads(inside(a.src).read_text()))})
    else:
        dump({"filed": retire_v2(repo, a.actor, key)})
    return 0


if __name__ == "__main__":
    sys.exit(main(run))
