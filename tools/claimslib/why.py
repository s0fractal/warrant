"""`why`: from a source statement to the claims BACKED in the view whose mutants change it, the
roadmap obligations naming those claims' duties, and the goals they answer; `why --uncovered`
lists the statements no cited mutant changes."""
import importlib.util
import json
import os
import re
from pathlib import Path

from .base import id_key, Refused
from .statements import statement_lines
from .model import Model
from .counters import standing


WHY_ROOTS = ("warrant", "warrant_agent", "tools")      # where the mutant harnesses edit: the files `why` reads
UNCOVERED_ROOTS = ("warrant", "warrant_agent")          # the code SPEC.md is about: `why --uncovered`'s default
WHY_LINE = re.compile(r"^(.+):([1-9][0-9]{0,6})\Z")     # FILE:LINE; \Z: `$` admits a trailing newline
CLAIMED, NO_CLAIM, NOT_A_STATEMENT = "CLAIMED", "NO_CLAIM", "NOT_A_STATEMENT"


def why_files(repo):
    """{relative path: Path} of the Python files under WHY_ROOTS. A command-line FILE is looked
    up here and never opened as given: `why` reads only files of this list."""
    out = {}
    for top in WHY_ROOTS:
        d = repo.root / top
        if d.is_dir():
            out.update({q.relative_to(repo.root).as_posix(): q for q in sorted(d.rglob("*.py"))
                        if "__pycache__" not in q.parts})
    return out


def _roadmap_links(repo):
    """{duty id: [link]}: each obligation (tools/roadmap.py) whose `serves` or `requires` names
    the duty, with its goal; {} when the repository has no roadmap configuration."""
    # roadmap.py imports the claims tool as `claims` (tools/claims.py), which re-exports this package.
    spec = importlib.util.spec_from_file_location("roadmap", Path(__file__).resolve().parents[1] / "roadmap.py")
    rm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rm)
    try:
        m = rm.Roadmap(repo.root).model()
    except rm.Refused:
        return {}
    out = {}
    for did in sorted(m.obligations):
        body, key = m.recs[did]["body"], m.goal_of(did)
        cur = [f for f in m.goals.get(key, []) if f.state == rm.CURRENT] or m.goals.get(key, [])[-1:]
        for rel in ("serves", "requires"):
            for x in body[rel]:
                out.setdefault(x, []).append({
                    "obligation": did, "relation": rel, "statement": m.rep["duties"][did]["statement"],
                    "state": m.rep["duties"][did]["disposition"], "goal": key, "goal_state": m.goal_state(key),
                    "goal_text": cur[0].text if cur else None})
    return out


class Why:
    """From a statement of a source file to the mutants that change it (Repo.mutant_statements,
    a key ("at", i) for unit i: an insertion before a statement changes none), the claims citing
    those mutants that are BACKED in the view (standing: a claim a replaying counter lowered is
    COUNTERED, shown with its counters and never as backing), the roadmap obligations whose
    serves or requires name the backing claims' duties, and the goals those obligations answer.
    Everything is read from the files and the records as they are now."""

    def __init__(self, repo):
        self.repo = repo
        self.files = why_files(repo)
        known = repo.mutants()
        model = Model(repo.snapshot(), repo.trust())
        status, self.low = standing(repo, model)
        self.cited = {}             # mutant id -> [Node]: the current claims citing it that are BACKED in the view
        self.countering = {}        # mutant id -> [Node]: those COUNTERED (a replaying counter lowered them)
        for n in sorted(model.current.values(), key=lambda n: id_key(n.id)):
            index = {"BACKED": self.cited, "COUNTERED": self.countering}.get(status[n.id])
            for mid in n.doc["mutants"] if index is not None else ():
                index.setdefault(mid, []).append(n)
        self.lineage = {}           # claim id -> {duty id}: every duty its lineage had (a duty is never superseded)
        for n in model.nodes.values():
            if not n.retired and n.doc["duty"]:
                self.lineage.setdefault(n.id, set()).add(n.doc["duty"])
        self.changes = {}           # (path, unit index) -> {mutant id}: the mutants that change unit i
        self.inserts = {}           # (path, unit index) -> {mutant id}: those inserting before it (shown, not counted)
        for mid in sorted(known):
            for path, (kind, i) in repo.mutant_statements(mid):
                (self.changes if kind == "at" else self.inserts).setdefault((os.path.normpath(path), i), set()).add(mid)
        self.links = _roadmap_links(repo)

    def units(self, path):
        """[(scope, function, own lines)] of a file of `files`; Refused WHY_FILE if it does not parse."""
        try:
            return statement_lines(self.files[path].read_text())
        except SyntaxError as e:
            raise Refused(f"{path} does not parse: {e}", "WHY_FILE") from e

    def covered(self, path, i):
        return any(mid in self.cited for mid in self.changes.get((path, i), ()))

    def at(self, path, line):
        """The answer for one line: its statements and what they serve (`why FILE:LINE`)."""
        if path not in self.files:
            raise Refused(f"{path}: not a Python file under {', '.join(r + '/' for r in WHY_ROOTS)} of this repository",
                          "WHY_FILE")
        src = self.files[path].read_text()
        lines = src.splitlines()
        if line > len(lines):
            raise Refused(f"{path} has no line {line}", "WHY_LINE")
        try:
            units = statement_lines(src)
        except SyntaxError as e:
            raise Refused(f"{path} does not parse: {e}", "WHY_FILE") from e
        hits = [i for i, (_, _, own) in enumerate(units) if line in own]
        stmts, claims, countered, obligations, goals = [], {}, {}, {}, {}
        for i in hits:
            scope, fn, own = units[i]
            mids = sorted(self.changes.get((path, i), ()), key=_mid_key)
            stmts.append({"index": i, "function": fn, "lines": [min(own), max(own)], "mutants": mids,
                          "cited": [mid for mid in mids if mid in self.cited],
                          "inserted_before": sorted(self.inserts.get((path, i), ()), key=_mid_key)})
            for mid in mids:
                for n in self.cited.get(mid, []):
                    c = claims.setdefault(n.id, {"claim": n.id, "transition": n.tid, "duty": n.doc["duty"],
                                                 "text": n.doc["text"], "via": []})
                    c["via"] = sorted(set(c["via"]) | {mid}, key=_mid_key)
                for n in self.countering.get(mid, []):
                    c = countered.setdefault(n.id, {"claim": n.id, "transition": n.tid, "duty": n.doc["duty"],
                                                    "status": "COUNTERED", "via": [],
                                                    "challenges": [{"challenge": x["challenge"], "actor": x["actor"],
                                                                    "counters": x["replays"]} for x in self.low[n.id]]})
                    c["via"] = sorted(set(c["via"]) | {mid}, key=_mid_key)
        for c in claims.values():
            for ln in (x for d in sorted(self.lineage.get(c["claim"], {c["duty"]})) for x in self.links.get(d, [])):
                o = obligations.setdefault(ln["obligation"], dict(ln, claims=[]))
                if c["claim"] not in o["claims"]:
                    o["claims"].append(c["claim"])
                if ln["goal"]:
                    goals[ln["goal"]] = {"goal": ln["goal"], "state": ln["goal_state"], "text": ln["goal_text"]}
        status = NOT_A_STATEMENT if not hits else CLAIMED if claims else NO_CLAIM
        return {"file": path, "line": line, "status": status, "source": (lines[line - 1:line] or [""])[0],
                "statements": stmts, "claims": sorted(claims.values(), key=lambda c: id_key(c["claim"])),
                "countered": sorted(countered.values(), key=lambda c: id_key(c["claim"])),
                "obligations": [obligations[d] for d in sorted(obligations)],
                "goals": [goals[k] for k in sorted(goals, key=lambda k: int(k[1:]))]}

    def uncovered(self, paths):
        """Each statement of `paths` that no cited mutant changes, the functions none of whose
        statements is covered (largest first), and the counts (`why --uncovered`)."""
        stmts, funcs, total, covered, mutated, lowered_only = [], {}, 0, 0, 0, 0
        for path in paths:
            lines = self.files[path].read_text().splitlines()
            for i, (scope, fn, own) in enumerate(self.units(path)):
                ok = self.covered(path, i)
                total, covered, mutated = total + 1, covered + ok, mutated + bool(self.changes.get((path, i)))
                if fn is not None:
                    f = funcs.setdefault((path, fn), {"file": path, "function": fn, "line": min(own), "statements": 0,
                                                      "covered": 0})
                    f["statements"] += 1
                    f["covered"] += ok
                    f["line"] = min(f["line"], min(own))
                if not ok:
                    low = sorted({n.id for mid in self.changes.get((path, i), ()) for n in self.countering.get(mid, [])},
                                 key=id_key)
                    lowered_only += bool(low)
                    stmts.append({"file": path, "line": min(own), "index": i, "function": fn, "countered": low,
                                  "source": lines[min(own) - 1].strip()})
        bare = sorted((f for f in funcs.values() if not f["covered"]), key=lambda f: (-f["statements"], f["file"], f["line"]))
        return {"files": list(paths), "statements": total, "covered": covered, "mutated": mutated,
                "countered_only": lowered_only, "uncovered": stmts,
                "functions": bare, "functions_total": len(funcs)}


def _mid_key(mid):
    return mid[0], int(re.sub(r"\D", "", mid) or 0)


def render_why(d):
    out = [f"{d['file']}:{d['line']} [{d['status']}] {d['source'].strip()}"]
    if d["status"] == NOT_A_STATEMENT:
        out.append("  no statement owns this line (blank, a comment or a docstring)")
    for s in d["statements"]:
        uncited = [m for m in s["mutants"] if m not in s["cited"]]
        out.append(f"  statement {s['index']} of {s['function'] or '<module>'} (lines {s['lines'][0]}-{s['lines'][1]}): "
                   + (f"changed by {', '.join(s['mutants'])}" if s["mutants"] else "no mutant changes it")
                   + (f"; not cited by a BACKED claim: {', '.join(uncited)}" if uncited else "")
                   + (f"; inserting before it (not counted): {', '.join(s['inserted_before'])}" if s["inserted_before"] else ""))
    for c in d["claims"]:
        out.append(f"  claim {c['claim']} (duty {c['duty'][:12]}, via {', '.join(c['via'])}): {c['text']}")
    for c in d["countered"]:
        out.append(f"  claim {c['claim']} [COUNTERED] (via {', '.join(c['via'])}), not backing: lowered by "
                   + "; ".join(f"challenge {x['challenge'][:12]} of {x['actor']} (counter {', '.join(h[:12] for h in x['counters'])})"
                               for x in c["challenges"]))
    for o in d["obligations"]:
        out.append(f"  obligation {o['obligation'][:12]} [{o['state']}] {o['relation']} {', '.join(o['claims'])}: "
                   f"{o['statement']} -> {o['goal'] or 'no goal'}")
    for g in d["goals"]:
        out.append(f"  goal {g['goal']} [{g['state']}] {g['text']}")
    if d["status"] == NO_CLAIM:
        out.append("  no claim: no mutant a claim BACKED in the view cites changes this statement")
    return "\n".join(out) + "\n"


def render_uncovered(d):
    out = [f"UNCOVERED {s['file']}:{s['line']} {s['function'] or '<module>'}: {s['source'][:100]}"
           + (f" (COUNTERED: {', '.join(s['countered'])})" if s["countered"] else "") for s in d["uncovered"]]
    out += [f"FUNCTION {f['file']}:{f['line']} {f['function']}: none of its {f['statements']} statements is covered"
            for f in d["functions"]]
    n, c = d["statements"], d["covered"]
    out.append(f"WHY: {n} statements in {len(d['files'])} files; {c} covered (changed by a mutant a claim BACKED in the view "
               f"cites), {n - c} uncovered ({100 * c // max(n, 1)}% covered), {d['countered_only']} of them changed by a COUNTERED claim's mutant; "
               f"{d['mutated']} changed by some mutant; "
               f"{len(d['functions'])} of {d['functions_total']} functions have no covered statement")
    return "\n".join(out) + "\n"


def _why_path(repo, arg):
    """A command-line FILE as a key of why_files: relative to the repository root."""
    return os.path.normpath(os.path.relpath(arg, repo.root) if os.path.isabs(arg) else arg)


def cmd_why(repo, a):
    if bool(a.target) == bool(a.uncovered is not None):
        raise Refused("give FILE:LINE, or --uncovered [FILE]", "WHY_USAGE")
    w = Why(repo)
    if a.target:
        m = WHY_LINE.match(a.target)
        if not m:
            raise Refused(f"{a.target!r} is not FILE:LINE", "WHY_USAGE")
        d = w.at(_why_path(repo, m.group(1)), int(m.group(2)))
        print(json.dumps(d, indent=1, ensure_ascii=False) if a.json else render_why(d), end="\n" if a.json else "")
        return 0
    if a.uncovered:
        path = _why_path(repo, a.uncovered)
        if path not in w.files:
            raise Refused(f"{a.uncovered}: not a Python file under {', '.join(r + '/' for r in WHY_ROOTS)}", "WHY_FILE")
        paths = [path]
    else:
        paths = [p for p in w.files if p.split("/")[0] in UNCOVERED_ROOTS]
    d = w.uncovered(paths)
    print(json.dumps(d, indent=1, ensure_ascii=False) if a.json else render_uncovered(d), end="\n" if a.json else "")
    return 0
