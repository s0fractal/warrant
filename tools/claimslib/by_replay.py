"""Acceptances by replay (G4), as `check` reads them.

A BACKED claim filed under a pinned checker has a duty whose accept_by is that checker
(`checkers` in .warrant/claims.json). The checker is an actor whose id names the bytes of
tools/claimslib/replay.py (replay.identity). It accepts a claim's closure only after replaying the
claim's witnesses and mutants at one commit, and its `accept` carries the report of that replay
as support (replay.REPORT). This module is the receiver's side. It does not trust the checker's
signature for what the report says:

  every acceptance by an actor named `checker sha256:…`
    CHECKER_REPORT   the support is exactly one well-formed report blob;
    CHECKER_ACTOR    the signer is the checker the report names;
    CHECKER_UNPINNED the checker is one .warrant/claims.json adopts (`checkers`);
    CHECKER_CLAIM    the report names the accepted transition, its claim and its duty, and the
                     acceptance is of that claim's discharge item;
    CHECKER_REPORT_FAILS  the report lists exactly the claim's witnesses, each PASS, and exactly
                     its mutants, each KILLED by cited cases;
    CHECKER_COMMIT_NAME   the report names its commit and tree by canonical ids: full lowercase
                     hex of the repository's object format (AMEND 1 of #176: a tag that moved
                     redirected what `--verify` ran);
  acceptances new since the base (the commit is read in this repository's history)
    CHECKER_COMMIT_NAME   the commit id is one Git resolves to itself as a commit (replay.canonical);
    CHECKER_COMMIT   the reported commit is an ancestor of HEAD;
    CHECKER_OTHER_TREE    the commit's tree is the reported tree, and the claim's transition was
                     in that tree's store: the replay was of the claim's own repository state;
    CHECKER_CODE_MISMATCH the commit's replay.py hashes to the reported checker: the same actor id
                     with other code is refused;
    CHECKER_ACCEPTED_CHALLENGED no challenge against the claim was in the replayed store;
  the pins
    CHECKER_PIN_STALE the checker new duties are filed under is the one this checkout's replay.py
                     is.

`verify` re-executes: for each acceptance new since the base whose commit is canonical and has
the reported tree (both checked before anything runs: it never follows a name), the reported
commit's own replay.py (its bytes hashed first) replays the claim at that commit, and a result
other than the report's is CHECKER_REPLAY_DIFFERS. That is the only step that runs code. It is
`claims.py replay --verify`, a CI job of its own.
"""
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import replay as RP
from .base import git


def is_checker(actor):
    return isinstance(actor, str) and actor.startswith(RP.PREFIX)


def current_checker(repo):
    """The actor id of this checkout's replay.py (the running one when the repository has none)."""
    f = repo.root / RP.SELF
    return RP.actor(f.read_bytes() if f.is_file() else None)


def report_of(model, rec):
    """The report blob an acceptance carries as support, or None when it is not well-formed."""
    sup = rec["body"]["support"]
    doc = model.snap.json_blob(sup[0]) if len(sup) == 1 else None
    if not (isinstance(doc, dict) and set(doc) == set(RP.REPORT_FIELDS) and doc["replay"] == RP.REPORT
            and all(isinstance(doc[k], str) for k in ("checker", "commit", "tree", "claim", "transition", "duty"))
            and isinstance(doc["witnesses"], dict) and isinstance(doc["mutants"], dict)
            and all(isinstance(v, dict) and set(v) == {"outcome", "fails"} and isinstance(v["fails"], list)
                    for v in doc["mutants"].values())):
        return None
    return doc


def accepts(model):
    """[(accept id, record, report or None)] of every authentic acceptance by a checker actor."""
    return [(rid, r, report_of(model, r)) for rid, r in sorted(model.recs.items())
            if r["type"] == "accept" and is_checker(r["actor"])]


def claim_problem(model, rec, rep):
    """(code, why) when report `rep` does not stand for acceptance `rec` of a BACKED claim, or None."""
    b = rec["body"]
    n = model.nodes.get(b["transition"])
    if n is None or not n.backed or b["item"] != 0 or rep["transition"] != b["transition"] or rep["claim"] != n.id \
            or rep["duty"] != n.doc["duty"] or b["evidence"] != n.rec["body"]["closes"][0]["evidence"] \
            or rec["actor"] not in model.recs[n.doc["duty"]]["body"]["accept_by"]:
        return "CHECKER_CLAIM", (f"the report names {rep['claim']} {rep['transition'][:12]}, the acceptance is of "
                                 f"{b['transition'][:12]} item {b['item']}: not the discharge item of a BACKED claim "
                                 "whose duty names this checker")
    w, m = rep["witnesses"], rep["mutants"]
    if sorted(w) != n.doc["witnesses"] or any(v != "PASS" for v in w.values()) or sorted(m) != n.doc["mutants"] \
            or any(v["outcome"] != "KILLED" or not v["fails"] or not set(v["fails"]) <= set(n.doc["witnesses"])
                   for v in m.values()):
        return "CHECKER_REPORT_FAILS", (f"{n.id}: the report does not show every cited witness PASS and every cited "
                                        "mutant KILLED by cited cases")
    return None


def problems(repo, model, pins):
    """[(code, detail)] of the pins and of every checker acceptance (the module docstring)."""
    out, adopted, n = [], pins.get("checkers", []), RP.id_length(repo.root) if accepts(model) else None
    if adopted and adopted[-1] != current_checker(repo):
        out.append(("CHECKER_PIN_STALE", f".warrant/claims.json files new BACKED duties under {adopted[-1][:28]}…, "
                    f"and this checkout's {RP.SELF} is {current_checker(repo)[:28]}…: pin the checker its code is"))
    for rid, r, rep in accepts(model):
        where = f"accept {rid[:12]} by {r['actor'][:28]}…"
        if rep is None:
            out.append(("CHECKER_REPORT", f"{where}: its support is not one {RP.REPORT} blob"))
            continue
        if r["actor"] != RP.PREFIX + rep["checker"]:
            out.append(("CHECKER_ACTOR", f"{where}: the report is by checker {rep['checker'][:12]}"))
            continue
        if r["actor"] not in adopted:
            out.append(("CHECKER_UNPINNED", f"{where}: .warrant/claims.json does not adopt this checker"))
            continue
        if not (RP.is_object_id(rep["commit"], n) and RP.is_object_id(rep["tree"], n)):
            out.append(("CHECKER_COMMIT_NAME", f"{where}: the report names commit {rep['commit'][:50]!r} and tree "
                        f"{rep['tree'][:50]!r}, not full lowercase {n}-digit ids"))
            continue
        bad = claim_problem(model, r, rep)
        if bad:
            out.append((bad[0], f"{where}: {bad[1]}"))
    return out


def new_problems(repo, model, before):
    """[(code, detail)]: each checker acceptance not in `before` (the record ids at the base)
    whose report stands for its claim, read against the reported commit (commit_problems)."""
    return [(c, f"accept {rid[:12]} by {r['actor'][:28]}…: {why}") for rid, r, rep in accepts(model)
            if rid not in before and rep is not None and r["actor"] == RP.PREFIX + rep["checker"]
            and claim_problem(model, r, rep) is None for c, why in commit_problems(repo, model, rep)]


def resolved(repo, rep):
    """(commit, None) when the report's commit is a canonical id whose tree is the reported tree,
    else (None, (code, why)). Every reader of a reported commit goes through here first."""
    try:
        c, tree = RP.canonical(repo.root, rep["commit"])
    except RP.Refusal as e:
        return None, ("CHECKER_COMMIT_NAME", str(e))
    if tree != rep["tree"]:
        return None, ("CHECKER_OTHER_TREE", f"commit {c[:12]} has tree {tree[:12]}, the report says {str(rep['tree'])[:12]}")
    return c, None


def commit_problems(repo, model, rep):
    """[(code, why)]: the reported commit against this repository's history."""
    c, bad = resolved(repo, rep)
    if bad:
        return [bad]
    try:
        subprocess.run(["git", "-C", str(repo.root), "merge-base", "--is-ancestor", c, "HEAD"], check=True,
                       capture_output=True)
    except subprocess.CalledProcessError:
        return [("CHECKER_COMMIT", f"commit {c[:12]} is not an ancestor of HEAD in this repository")]
    out = []

    def at_commit(path):
        r = subprocess.run(["git", "-C", str(repo.root), "show", f"{c}:{path}"], capture_output=True, check=False)
        return r.stdout if r.returncode == 0 else None

    if at_commit(f".warrant/store/records/{rep['transition']}.json") is None:
        out.append(("CHECKER_OTHER_TREE", f"the claim's transition {rep['transition'][:12]} is not in the store of "
                    f"commit {c[:12]}: the replay was not of that claim's repository"))
    code = at_commit(RP.SELF)
    if code is None or RP.identity(code) != rep["checker"]:
        out.append(("CHECKER_CODE_MISMATCH", f"{RP.SELF} at {c[:12]} is checker "
                    f"{RP.identity(code)[:12] if code is not None else 'none'}, the report's is {rep['checker'][:12]}"))
    for ch, r in model.recs.items():
        if r["type"] == "challenge" and r["body"]["target"] == rep["transition"] \
                and at_commit(f".warrant/store/records/{ch}.json") is not None:
            out.append(("CHECKER_ACCEPTED_CHALLENGED", f"challenge {ch[:12]} against {rep['claim']} was in the "
                        f"replayed store; the checker accepts no challenged claim"))
    return out


def _base_records(repo, base):
    """The record ids at revision `base`, an operator's argument (never a report's): resolved once
    to its commit id, which every later read uses."""
    base = git(repo, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").decode().strip()
    rows = git(repo, "ls-tree", "-r", "--name-only", base, "--", ".warrant/store/records").decode().split()
    return {Path(p).name[:-5] for p in rows if p.endswith(".json")}


def verify(repo, model, base, jobs=4):
    """[(code, detail)]: each checker acceptance new since `base` whose report the reported
    commit's own replay.py does not reproduce there (CHECKER_REPLAY_DIFFERS), or that cannot be
    replayed (CHECKER_COMMIT_NAME, CHECKER_OTHER_TREE, CHECKER_COMMIT, CHECKER_CODE_MISMATCH).
    The commit and its tree are checked against the report before anything is extracted or run,
    here and not only by `check`: a name is never resolved into what runs."""
    before = _base_records(repo, base)
    todo, out = {}, []
    for rid, r, rep in accepts(model):
        if rid not in before and rep is not None and rep["transition"] in model.nodes:
            c, bad = resolved(repo, rep)
            if bad:
                out.append((bad[0], f"accept {rid[:12]} of {rep['claim']}: {bad[1]}; nothing replayed"))
            else:
                todo.setdefault(c, []).append((rid, rep))
    for commit, items in sorted(todo.items()):
        work = Path(tempfile.mkdtemp(prefix="claims-replay-verify-"))
        try:
            try:
                RP.extract(repo.root, commit, work)
            except (subprocess.CalledProcessError, OSError) as e:
                out += [("CHECKER_COMMIT", f"accept {rid[:12]}: commit {commit[:12]} cannot be extracted: {e}")
                        for rid, _ in items]
                continue
            code = (work / RP.SELF).read_bytes() if (work / RP.SELF).is_file() else b""
            mine = [(rid, rep) for rid, rep in items if RP.identity(code) == rep["checker"]]
            out += [("CHECKER_CODE_MISMATCH", f"accept {rid[:12]}: {RP.SELF} at {commit[:12]} is not checker "
                     f"{rep['checker'][:12]}") for rid, rep in items if (rid, rep) not in mine]
            if not mine:
                continue
            spec = importlib.util.spec_from_file_location(f"replay_at_{commit[:12]}", work / RP.SELF)
            then = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(then)        # the bytes just hashed: the checker that signed
            claims = {rep["transition"]: model.nodes[rep["transition"]].doc for _, rep in mine}
            got = then.replay(work, claims, jobs)
            for rid, rep in mine:
                w, m = got[rep["transition"]]
                if w != rep["witnesses"] or m != rep["mutants"]:
                    diff = sorted(k for k in set(w) | set(rep["witnesses"]) if w.get(k) != rep["witnesses"].get(k))
                    diff += sorted(k for k in set(m) | set(rep["mutants"]) if m.get(k) != rep["mutants"].get(k))
                    out.append(("CHECKER_REPLAY_DIFFERS", f"accept {rid[:12]} of {rep['claim']}: replayed at "
                                f"{commit[:12]}, {', '.join(diff[:6])} differ from the report"))
        finally:
            shutil.rmtree(work, ignore_errors=True)
    return out


def replayed(model):
    """{transition: report} of the checker acceptances whose report stands for the claim, for
    the views: an acceptance by replay is named for what it checked."""
    return {r["body"]["transition"]: rep for _, r, rep in accepts(model)
            if rep is not None and r["actor"] == RP.PREFIX + rep["checker"] and claim_problem(model, r, rep) is None}
