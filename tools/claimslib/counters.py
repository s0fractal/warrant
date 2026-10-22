"""Counters and challenges (the open circle, part C).

A counter blob (warrant-claims/counter@1) is admitted only by its replay (replay_counter): a patch
confined to the statements one of the claim's own mutants changes, under which every cited witness
passes and some case fails. `challenge_table` sorts the challenges against current claims into
LOWERS, COUNTED and THESIS; `standing` is every claim's status as the views show it. A downgrade
(BACKED to UNBACKED) needs such a proof (lost_backing); `check --base` replays the counters new
since the base (new_counters). Every caller outside this module reaches the replay as
`counters.replay_counter`, so a test can stub it in one place."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from warrant import jcs as C

from .base import COUNTER, COUNTER_FIELDS, git, TEST_RE
from .statements import changed_scopes, changed_statements
from .repo import Repo, witness_problems
from .model import status_of


def standing(repo, model, table=None):
    """({claim id: status}, low): every current claim's status as the views show it (status_of
    over lowered(challenge_table)), and the lowering entries by claim. `Node.backed` says only
    that a claim cites witnesses and mutants; a replaying counter (#170) lowers it to COUNTERED,
    and whatever counts backing (SPEC-CLAIMS.md, `why`, `audit`, check's totals) reads this."""
    low = lowered(challenge_table(repo, model) if table is None else table)
    return {cid: status_of(n, low) for cid, n in model.current.items()}, low


def new_counters(repo, model, before):
    """COUNTER_NOT_REPLAYED for each challenge new since the base (not in `before`) that carries
    a counter blob that does not replay against the claim it targets: a counter from anyone is
    admitted by its replay, and only by it (open circle, part C)."""
    out = []
    for rid, r in sorted(model.recs.items()):
        if r["type"] != "challenge" or rid in before:
            continue
        carried = [h for h in r["body"]["evidence"] if _is_counter(model.snap, h)]
        target = model.nodes.get(r["body"]["target"])
        for c in carried:
            why = replay_counter(repo, model.snap, c, target) if target is not None and target.backed else \
                "its target is not a BACKED claim transition"
            if why:
                out.append(("COUNTER_NOT_REPLAYED", f"challenge {rid[:12]} by {r['actor']}: counter {c[:12]}: {why}"))
    return out


class BaseTests:
    """The tests/ directory of the base revision, extracted on first use into a temporary
    Repo, so a cited case or mutant can be looked up as it was there."""

    def __init__(self, repo, rev):
        self.repo, self.rev, self.tmp, self._repo = repo, rev, None, None

    def get(self):
        if self._repo is None:
            import io
            import tarfile
            self.tmp = Path(tempfile.mkdtemp(prefix="claims-base-tests-"))
            try:
                data = git(self.repo, "archive", "--format=tar", self.rev, "--", "tests")
                with tarfile.open(fileobj=io.BytesIO(data)) as t:
                    t.extractall(self.tmp, filter="data")
            except subprocess.CalledProcessError:
                (self.tmp / "tests").mkdir(exist_ok=True)      # no tests/ at the base: every case is absent there
            self._repo = Repo(self.tmp)
        return self._repo

    def close(self):
        if self.tmp is not None:
            shutil.rmtree(self.tmp, ignore_errors=True)


def lost_backing(repo, model, n, at_base=None):
    """(code, why) when claim `n`'s chain lost its backing without a proof of the loss, or None.

    The run of UNBACKED claims that ends at `n` follows the last BACKED claim `p` of the
    chain. The loss is admitted when (a) the backing broke on its own: a witness case or a
    mutant `p` cites no longer exists or no longer targets a cited case, which `check` sees
    directly, AND it was already so at the base revision (`at_base`, a BaseTests): a witness
    removed in the same change as the downgrade is refused (W5; the case would otherwise be
    renamed away with its mutants and the downgrade pass); or (b) a transition of the run
    cites a counter blob (COUNTER) against `p`, directly or as the evidence of an authentic
    challenge whose target is `p`, and the blob replays (replay_counter). A challenge, or a
    blob, that is not such a replay is a thesis, not a proof, and admits nothing."""
    run = []
    while True:
        run.append(n)
        prev = n.doc["previous"]
        p = model.nodes.get(prev["transition"]) if prev else None
        if p is None:
            return "LOST_BACKING_WITHOUT_COUNTER", "no backed claim precedes it in its chain"
        if p.backed:
            break
        n = p
    broken = witness_problems(repo, p.doc["witnesses"], p.doc["mutants"])
    if broken:
        if at_base is not None and witness_problems(at_base.get(), p.doc["witnesses"], p.doc["mutants"]):
            return None
        return "WITNESS_REMOVED_WITH_DOWNGRADE", (
            f"the backing of {p.tid[:12]} breaks in this change ({'; '.join(f'{c} {w}' for c, w in broken)[:200]}) "
            "and was whole at the base; a downgrade needs a counter blob that replays, not a removed witness")
    tried, seen = [], set()
    for m in reversed(run):
        for h in m.rec["body"]["evidence"]:
            for c in counter_candidates(model, h, p):
                if c in seen:
                    continue
                seen.add(c)
                why = replay_counter(repo, model.snap, c, p)
                if why is None:
                    return None
                tried.append(f"{c[:12]}: {why}")
    if tried:
        return "COUNTER_NOT_REPLAYED", "; ".join(tried)
    return "LOST_BACKING_WITHOUT_COUNTER", (f"no transition from {run[-1].tid[:12]} on cites a counter blob "
                                            f"({COUNTER}) against {p.tid[:12]}, directly or through a challenge")


def counter_candidates(model, h, p):
    """The blob ids `h` offers as counter-evidence against claim `p`: itself when it is a
    COUNTER blob, or the COUNTER blobs among the evidence of a challenge `h` against `p`."""
    r = model.recs.get(h)
    if r is not None:
        if r["type"] != "challenge" or r["body"]["target"] != p.tid:
            return []
        return [x for x in r["body"]["evidence"] if _is_counter(model.snap, x)]
    return [h] if _is_counter(model.snap, h) else []


def _is_counter(snap, h):
    doc = snap.json_blob(h)
    return isinstance(doc, dict) and doc.get("counter") == COUNTER


_REPLAYS = {}


def replay_counter(repo, snap, h, p):
    """None if counter blob `h` is a proof against claim `p`, else why not.

    The patch must alter a scope (changed_scopes) that one of `p`'s cited mutants alters.
    The blob is {"counter": COUNTER, "claim": <id>, "against": <p's transition>, "patch":
    <unified diff of warrant/ or warrant_agent/>, "passes": [<test>:<case>…], "fails":
    [<test>:<case>…], "why": <text>}. The patch is applied to a copy of the packages of
    this checkout and the named test files run against the copy: every case in `passes`
    must pass and every case in `fails` must fail, and `passes` must cover every witness
    case `p` cites. The patch changes behaviour, yet the claim's witnesses do not notice:
    they did not test the sentence. `why` stays a thesis; the replay is what admits the
    loss. Cached per run by (repository, blob, claim)."""
    key = (str(repo.root), h, p.tid)
    if key not in _REPLAYS:
        _REPLAYS[key] = _replay_counter(repo, snap.json_blob(h), p)
    return _REPLAYS[key]


STATEMENT_REFUSAL = "patch changes statements no single mutant of the claim changes"


def _counter_shape(doc, p):
    """Why counter blob `doc` cannot be a proof against claim `p` before anything runs, or None."""
    if set(doc) != set(COUNTER_FIELDS):
        return f"members are not {list(COUNTER_FIELDS)}"
    if doc["claim"] != p.id or doc["against"] != p.tid:
        return f"it is against {doc['claim']!r} {str(doc['against'])[:12]}, not {p.id} {p.tid[:12]}"
    return _counter_cases(doc, p)


def _counter_cases(doc, p):
    """Why the blob's passes/fails/patch/why cannot stand, or None."""
    cases = [doc["passes"], doc["fails"]]
    if not all(isinstance(x, list) and all(isinstance(c, str) and TEST_RE.match(c.partition(":")[0]) and c.partition(":")[2]
                                           for c in x) for x in cases):
        return "passes and fails must be lists of <test file>:<case>"
    if not doc["fails"]:
        return "fails is empty: a patch that breaks nothing proves nothing"
    if set(doc["passes"]) & set(doc["fails"]):
        return "a case is in both passes and fails"
    missing = sorted(set(p.doc["witnesses"]) - set(doc["passes"]))
    if missing:
        return f"passes omits cited witnesses {', '.join(missing)}"
    if not (isinstance(doc["patch"], str) and isinstance(doc["why"], str) and doc["why"]):
        return "patch must be a string and why a non-empty string"
    return _patch_paths(doc["patch"])


def _patch_paths(patch):
    """Why a patch names a file outside warrant/ and warrant_agent/, or None."""
    for line in patch.splitlines():
        if line.startswith(("--- ", "+++ ")):
            path = line[4:].split("\t")[0].strip()
            if path != "/dev/null" and not re.match(r"[ab]/(warrant|warrant_agent)/[A-Za-z0-9_./-]+\Z", path) or ".." in path:
                return f"the patch touches {path!r}, outside warrant/ and warrant_agent/"
    return None


def _counter_locality(repo, doc, p, tmp, statements=True):
    """Why the applied patch (in `tmp`) is not confined to the claim's own code, or None.

    Locality: the patch must alter code that one of the claim's own mutants alters. Those
    mutants are the repository's statement of which code the sentence is about; a patch
    elsewhere that breaks some case proves nothing about this claim's witnesses. A scope
    counts as changed only if its AST changes (no comments, layout or docstrings), and every
    changed scope must be one the claim's mutants change: no foreign hunk can supply the FAIL
    while a cosmetic or harmless local edit supplies the locality. AMEND 1 of #169: and its
    statements must be among those ONE of the claim's mutants changes; per function, 892
    existing mutants were counters `check` admitted against claims about another rule of the
    same function (SPEC-3.6-7 by M29)."""
    files = {m.group(1) for m in re.finditer(r"^\+\+\+ b/(\S+)", doc["patch"], re.M)} | \
            {m.group(1) for m in re.finditer(r"^--- a/(\S+)", doc["patch"], re.M)}
    touched, stmts = set(), set()
    for f in sorted(files):
        if not f.endswith(".py"):
            return f"the patch changes {f}, which is not Python source"
        old = (repo.root / f).read_text() if (repo.root / f).is_file() else ""
        new = (tmp / f).read_text() if (tmp / f).is_file() else ""
        try:
            touched |= changed_scopes(f, old, new)
            stmts |= changed_statements(f, old, new)
        except SyntaxError as e:
            return f"the patch leaves {f} unparseable: {e.msg} (line {e.lineno})"
    theirs = {sc for mid in p.doc["mutants"] for sc in repo.mutant_scopes(mid)}
    fmt = lambda ss: ", ".join(f"{f}:{fn}" for f, fn in sorted(ss)) or "none"     # noqa: E731
    if not touched & theirs:
        return (f"patch changes no behaviour in the claim's mutants' scopes (patch: {fmt(touched)}; "
                f"mutants {' '.join(p.doc['mutants'])}: {fmt(theirs)})")
    if touched - theirs:
        return (f"patch changes scopes the claim's mutants do not: {fmt(touched - theirs)} "
                f"(mutants {' '.join(p.doc['mutants'])}: {fmt(theirs)})")
    if statements and not any(stmts <= repo.mutant_statements(mid) for mid in p.doc["mutants"]):
        return (f"{STATEMENT_REFUSAL} ({len(stmts)} statement(s) in {fmt(touched)}; "
                f"mutants {' '.join(p.doc['mutants'])} each change other statements)")
    return None


def _counter_run(repo, doc, tmp):
    """Why the named cases do not pass and fail as the blob says under the patch, or None."""
    got = {}
    for test in sorted({c.partition(":")[0] for c in doc["passes"] + doc["fails"]}):
        if not (repo.tests / f"{test}.py").is_file():
            return f"tests/{test}.py does not exist"
        res = tmp / f"results-{test}.json"
        env = dict(os.environ, WARRANT_IMPL=str(tmp), WARRANT_RESULTS=str(res))
        subprocess.run([sys.executable, str((repo.tests / f"{test}.py").resolve())], cwd=repo.tests.resolve(), env=env,
                       capture_output=True, timeout=900, check=False)
        if not res.is_file():
            return f"tests/{test}.py produced no results under the patch"
        got.update({f"{test}:{k}": v for k, v in json.loads(res.read_text()).items()})
    absent = [c for c in doc["passes"] + doc["fails"] if c not in got]
    if absent:
        return f"no such case ran: {', '.join(absent)}"
    bad = [f"{c} {got[c]}, not PASS" for c in doc["passes"] if got[c] != "PASS"] + \
          [f"{c} {got[c]}, not FAIL" for c in doc["fails"] if got[c] != "FAIL"]
    return "; ".join(bad) or None


def _replay_counter(repo, doc, p, statements=True):
    """replay_counter's work: the blob's shape, the patch applied to a copy of the packages,
    its locality, then the named cases. `statements=False` only for --selftest, to show that
    the statement rule is what refuses a counter that would replay per function."""
    why = _counter_shape(doc, p)
    if why:
        return why
    tmp = Path(tempfile.mkdtemp(prefix="claims-counter-"))
    try:
        for pkg in ("warrant", "warrant_agent"):
            if (repo.root / pkg).is_dir():
                shutil.copytree(repo.root / pkg, tmp / pkg, ignore=shutil.ignore_patterns("__pycache__"))
        if doc["patch"].strip():
            r = subprocess.run(["git", "apply", "--whitespace=nowarn", "-"], cwd=tmp, input=doc["patch"].encode(),
                               capture_output=True, check=False)
            if r.returncode:
                return f"the patch does not apply: {r.stderr.decode().strip()[:200]}"
        return _counter_locality(repo, doc, p, tmp, statements) or _counter_run(repo, doc, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


LOWERS, COUNTED, THESIS = "LOWERS", "COUNTED", "THESIS"


def counts_against(model, n, actor):
    """Whether `actor`'s challenge against claim `n` counts with no counter that replays: the
    claim's author, or an actor its duty is owed to or accepted by (SPEC §4.6: owed_to and
    accept_by always count). This repository's profile names no other challenger."""
    if actor == n.rec["actor"]:
        return True
    d = model.recs.get(n.doc.get("duty")) if not n.retired else None
    return d is not None and actor in set(d["body"]["owed_to"]) | set(d["body"]["accept_by"])


def challenge_table(repo, model, replay=None):
    """{challenge id: entry} for each authentic challenge against a current claim, its `kind`:
      LOWERS   it carries a counter blob against the claim that replays (replay_counter), the
               claim being BACKED: whoever filed it, the claim's backing is lowered in the view
               (COUNTERED); a counter needs nobody's permission;
      COUNTED  no counter of it replays and its filer counts (counts_against): a standing
               challenge, refused by `check` (CHALLENGED) until the author answers;
      THESIS   no counter of it replays and its filer does not count: listed, nothing more.
    `replay(c, n)` (None or why not) defaults to replay_counter; tests pass their own."""
    replay = replay or (lambda c, n: replay_counter(repo, model.snap, c, n))
    out = {}
    for cid, chs in sorted(model.challenges.items()):
        n = model.current[cid]
        for ch in chs:
            actor = model.recs[ch]["actor"]
            counters = sorted(counter_candidates(model, ch, n))
            whys = {c: replay(c, n) if n.backed else "the claim is not BACKED: it has no backing to lower"
                    for c in counters}
            good = [c for c in counters if whys[c] is None]
            kind = LOWERS if good else COUNTED if counts_against(model, n, actor) else THESIS
            out[ch] = {"claim": cid, "transition": n.tid, "actor": actor, "kind": kind, "counters": counters,
                       "replays": good, "why": "; ".join(f"{c[:12]}: {whys[c]}" for c in counters if whys[c])}
    return out


def lowered(table):
    """{claim id: [table entries]} of the claims whose backing a replaying counter lowers."""
    out = {}
    for ch, x in sorted(table.items()):
        if x["kind"] == LOWERS:
            out.setdefault(x["claim"], []).append(dict(x, challenge=ch))
    return out


def counter_citations(model):
    """{counter blob: [record ids]}: each COUNTER blob any authentic challenge or transition
    carries as evidence."""
    out = {}
    for rid, r in model.recs.items():
        if r["type"] in ("challenge", "transition"):
            for h in r["body"]["evidence"]:
                if _is_counter(model.snap, h):
                    out.setdefault(h, []).append(rid)
    return out


def downgrade_counters(model):
    """{counter blob: claim transition it is against}: the counters a downgrade cites, i.e. a
    run of UNBACKED claims after the BACKED claim `p` cites them, directly or through a
    challenge against `p` (the route `check --base` replays when the downgrade is filed)."""
    out = {}
    for q in model.nodes.values():
        if q.retired or q.kind != "normative" or q.backed:
            continue
        run, p = [q], None
        while run[-1].doc["previous"]:
            prev = model.nodes.get(run[-1].doc["previous"]["transition"])
            if prev is None or prev.retired:
                break
            if prev.backed:
                p = prev
                break
            run.append(prev)
        if p is None:
            continue
        for m in run:
            for h in m.rec["body"]["evidence"]:
                for c in counter_candidates(model, h, p):
                    if model.snap.json_blob(c).get("against") == p.tid:
                        out[c] = p.tid
    return out


def counter_file_bytes(path):
    """The blob bytes of a counter file: canonical JSON for a counter blob (so `check` can
    read it back), the file's bytes otherwise."""
    data = Path(path).read_bytes()
    try:
        doc = json.loads(data)
    except ValueError:
        return data
    return C.canon(doc) if isinstance(doc, dict) and doc.get("counter") == COUNTER else data
