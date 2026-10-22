"""`audit`: the blind-spot hunt. From the matrices tests/mutants.py --matrix writes, every BACKED claim
and every other mutant of its code under which some case fails and every witness passes, with
the would-be counter blob. A report, not a refusal of `check`."""
import difflib
import importlib.util
import json
import os
import re
import tempfile
from pathlib import Path

from .base import COUNTER, HARNESSES, id_key, Refused
from .model import Model
from .counters import standing


MATRIX = "warrant-mutants/matrix@1"


def confined(arg):
    """The file a command-line path `arg` names in the temporary directory,
    tempfile.gettempdir() ($TMPDIR, else /tmp): its base name there. Refused, before anything
    is opened, when `arg` names another directory: matrices and counters live in $TMPDIR (an
    operator keeping them elsewhere sets TMPDIR for the command; CI: $RUNNER_TEMP)."""
    base = os.path.realpath(tempfile.gettempdir())
    name = os.path.basename(os.path.normpath(arg))
    if not name or name in (".", "..") or os.path.realpath(os.path.join(base, arg)) != os.path.join(base, name):
        raise Refused(f"{arg}: not a file name in the temporary directory {base} (set TMPDIR)")
    return Path(base) / name


def _harness(repo, name):
    spec = importlib.util.spec_from_file_location(f"claims_audit_{Path(name).stem}", repo.tests / name)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _definitions(repo, core):
    """{mutant id: definition digest} of every harness of HARNESSES, as defined now."""
    defs = {}
    for name, _ in HARNESSES:
        if (repo.tests / name).is_file():
            mod = core if name == "mutants.py" else _harness(repo, name)
            defs.update({m[0]: core.mutant_digest(m) for m in mod.MUTANTS})
    return defs


def _read_matrix(p, here, defs):
    """(rows, problems) of one matrix file `p` (a Path already confined)."""
    try:
        doc = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        return {}, [("MATRIX_UNREADABLE", f"{p}: {e}")]
    if not isinstance(doc, dict) or doc.get("matrix") != MATRIX or not isinstance(doc.get("mutants"), dict):
        return {}, [("MATRIX_UNREADABLE", f"{p}: not a {MATRIX} document")]
    if doc.get("source") != here:
        return {}, [("MATRIX_STALE", f"{p}: written for source {str(doc.get('source'))[:12]}, this checkout is "
                     f"{here[:12]} (rerun tests/mutants.py --matrix)")]
    rows, problems = {}, []
    for mid, row in sorted(doc["mutants"].items()):
        if defs.get(mid) != row.get("definition"):
            problems.append(("MATRIX_STALE", f"{p}: {mid} is defined otherwise now"))
        else:
            rows[mid] = row
    return rows, problems


def load_matrices(repo, paths):
    """({mutant id: matrix row}, [(code, detail)]): the rows of matrices written by
    `tests/mutants.py --matrix` / `tests/agent_mutants.py --matrix`. A matrix answers only
    for the code and tests it ran: its source digest must be this checkout's, and a row
    only for the mutant as defined now (its definition digest), else MATRIX_STALE. `paths`
    come from the caller (cmd_audit confines command-line paths first)."""
    core = _harness(repo, "mutants.py")
    here, defs = core.source_digest(repo.root), _definitions(repo, core)
    rows, problems = {}, []
    for p in paths:
        got, why = _read_matrix(Path(p), here, defs)
        rows.update(got)
        problems += why
    return rows, problems


def _mutant_patch(repo, mid):
    """The unified diff of mutant `mid`'s edits on the file as it is now ('' if they do not apply)."""
    path, edits = repo.mutant_edits.get(mid, (None, ()))
    f = repo.root / path if path else None
    if f is None or not f.is_file():
        return ""
    old = new = f.read_text()
    for o, n in edits:
        if new.count(o) != 1:
            return ""
        new = new.replace(o, n)
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"a/{path}", f"b/{path}"))


def mutant_lines(repo, mid):
    """{(path, line)} the old text of mutant `mid`'s edits covers in the file as it is now."""
    path, edits = repo.mutant_edits.get(mid, (None, ()))
    f = repo.root / path if path else None
    if f is None or not f.is_file():
        return set()
    src, out = f.read_text(), set()
    for o, _ in edits:
        i = src.find(o)
        if i < 0 or src.count(o) != 1:
            return set()
        first = src.count("\n", 0, i) + 1
        out |= {(path, k) for k in range(first, first + o.rstrip("\n").count("\n") + 1)}
    return out


class _MutantFacts:
    """A mutant's scopes, statements and line spans in the files as they are now, computed once."""

    def __init__(self, repo):
        self.repo, self._memo = repo, {}

    def _get(self, kind, fn, mid):
        if (kind, mid) not in self._memo:
            self._memo[(kind, mid)] = fn(mid)
        return self._memo[(kind, mid)]

    def scopes(self, mid):
        return self._get("scopes", self.repo.mutant_scopes, mid)

    def statements(self, mid):
        return self._get("statements", self.repo.mutant_statements, mid)

    def lines(self, mid):
        return self._get("lines", lambda m: mutant_lines(self.repo, m), mid)


def _failing(runs):
    return sorted(f"{t}:{c}" for t, res in runs.items() if isinstance(res, dict) for c, v in res.items() if v == "FAIL")


def _witness_results(n, runs):
    """{witness: PASS | FAIL | None (its file or case did not run)} under one matrix row."""
    out = {}
    for w in n.doc["witnesses"]:
        test, _, case = w.partition(":")
        res = runs.get(test)
        out[w] = res.get(case) if isinstance(res, dict) else None
    return out


def _audit_entry(facts, n, mid, row, fails):
    mine = {sc for m in n.doc["mutants"] for sc in facts.scopes(m)}
    lines = {x for m in n.doc["mutants"] for x in facts.lines(m)}
    st = facts.statements(mid)
    return {"claim": n.id, "transition": n.tid, "mutant": mid, "what": row.get("what", ""),
            "scopes": sorted(f"{f}:{q}" for f, q in facts.scopes(mid)), "fails": fails, "witnesses": n.doc["witnesses"],
            # the would-be counter replays (replay_counter's locality): confined to the claim's
            # scopes, and its statements among those of ONE of the claim's mutants
            "confined": facts.scopes(mid) <= mine and bool(st) and any(st <= facts.statements(m) for m in n.doc["mutants"]),
            "tier": "line" if facts.lines(mid) & lines else "function"}


def _audit_claim(repo, facts, n, rows, blind, unknown):
    mine = {sc for m in n.doc["mutants"] for sc in facts.scopes(m)}
    for mid, row in sorted(rows.items(), key=lambda kv: (kv[0][0], int(re.sub(r"\D", "", kv[0]) or 0))):
        fails = _failing(row.get("runs") or {}) if facts.scopes(mid) & mine else []
        seen = _witness_results(n, row.get("runs") or {}) if fails else {}
        if not fails or "FAIL" in seen.values():
            continue
        entry = _audit_entry(facts, n, mid, row, fails)
        if None in seen.values():
            unknown.append(dict(entry, not_run=sorted({w.partition(":")[0] for w, v in seen.items() if v is None})))
            continue
        entry["counter"] = {"counter": COUNTER, "claim": n.id, "against": n.tid, "patch": _mutant_patch(repo, mid),
                            "passes": sorted(n.doc["witnesses"]), "fails": fails,
                            "why": f"mutant {mid} ({row.get('what', '')}) alters code the mutants of {n.id} alter; "
                                   f"{', '.join(fails)} fail under it and every witness of {n.id} passes"}
        blind.append(entry)


def audit(repo, rows):
    """(blind, unknown) over every current BACKED claim and every matrix row (mutant X)
    whose AST scopes overlap the scopes of the claim's mutants, and under which some case
    fails (a claim's own mutant is no exception: it is seen, since it fails a cited case,
    or its claim is blind to it):
      blind:   every witness the claim cites ran under X and passed: a candidate blind
               spot. Each entry carries the would-be counter blob (COUNTER): the claim, X's
               patch, passes = the witnesses, fails = the cases X fails. It replays (check's
               replay_counter) iff `confined`: X's scopes are within the claim's and its
               statements (changed_statements) among those one of the claim's mutants changes.
      unknown: some cited witness's test file did not run under X (an own-file matrix):
               neither blind nor seen.
    Each entry's `tier` is "line" when X's edits cover a line that an edit of one of the
    claim's mutants covers (the same statement, most likely the same rule), else
    "function" (the same function only: often another rule of it).
    A witness that fails under X sees it; nothing is reported then. A COUNTERED claim (standing:
    a replaying counter lowered it already) is not audited: its witnesses are shown blind, the
    remedy is re-backing it, and a second counter would add nothing (cmd_audit lists it)."""
    repo.mutants()
    model = Model(repo.snapshot(), repo.trust())
    status, _ = standing(repo, model)
    facts, blind, unknown = _MutantFacts(repo), [], []
    for n in sorted((n for n in model.current.values() if status[n.id] == "BACKED"), key=lambda n: id_key(n.id)):
        _audit_claim(repo, facts, n, rows, blind, unknown)
    return blind, unknown


def cmd_audit(repo, a):
    rows, problems = load_matrices(repo, [confined(m) for m in a.matrix])
    for code, detail in problems:
        print(f"REFUSED {code} {detail}")
    if problems:
        return 2
    blind, unknown = audit(repo, rows)
    _, low = standing(repo, Model(repo.snapshot(), repo.trust()))
    for cid, xs in sorted(low.items(), key=lambda kv: id_key(kv[0])):
        print(f"COUNTERED {cid}: not audited, re-back it first; lowered by "
              + ", ".join(f"challenge {x['challenge'][:12]} of {x['actor']}" for x in xs))
    out = confined(a.counters) if a.counters else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    for b in sorted(blind, key=lambda b: (not b["confined"], b["tier"] != "line")):
        print(f"BLIND[{b['tier']}] {b['claim']} {b['transition'][:12]}: {b['mutant']} ({', '.join(b['scopes'])}) {b['what']!r} fails "
              f"{' '.join(b['fails'])}; every witness passes ({' '.join(b['witnesses'])}); "
              + ("the would-be counter replays" if b["confined"] else "not confined: as a counter it would be refused"))
        if out:
            (out / f"counter-{b['claim']}-{b['mutant']}.json").write_text(json.dumps(b["counter"], indent=1) + "\n")
    for u in unknown:
        print(f"UNKNOWN {u['claim']}: {u['mutant']} fails {' '.join(u['fails'])}; "
              f"witness files not run under it: {' '.join(u['not_run'])}")
    claims = {b["claim"] for b in blind}
    line = [b for b in blind if b["tier"] == "line"]
    ok = [b for b in blind if b["confined"]]
    print(f"AUDIT: {len(rows)} mutants in the matrix; {len(blind)} candidate blind spots in {len(claims)} claims; "
          f"{len(ok)} admissible as counters (confined) in {len({b['claim'] for b in ok})} claims; tier line {len(line)} "
          f"in {len({b['claim'] for b in line})} claims, tier function {len(blind) - len(line)}; "
          f"{len(unknown)} unknown (witness file not run)")
    return 1 if a.refuse and blind else 0
