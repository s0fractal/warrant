#!/usr/bin/env python3
"""Generated mutants: the repository looks for its own blind spots (roadmap G7).

    python3 tests/generated_mutants.py list [--json] [FILE ...]          # what the generator makes
    python3 tests/generated_mutants.py coverage --out MAP.json [--jobs N] # each test file once, traced
    python3 tests/generated_mutants.py run --coverage MAP.json [--shard K/N] [--matrix FILE] [--jobs N] [ID ...]
    python3 tests/generated_mutants.py merge --coverage MAP.json OUT PART.json ...
    python3 tests/generated_mutants.py report MATRIX.json --out DIR [--previous LIST.json]
    python3 tests/generated_mutants.py --selftest

A generated mutant is a discovery tool, never backing: a SPEC claim is backed only by a curated
mutant of tests/mutants.py or tests/agent_mutants.py that it cites. The generator (generate())
applies fixed AST operators to every statement of warrant/, warrant_agent/ and tools/claimslib/
(the claims selftests excepted) and names each mutant by what it changes, not where: the id is a
hash of (file, scope, the statement's AST, its occurrence among equal statements of that scope,
operator, occurrence of the operator's site in the statement). The statements are the units of
tools/claimslib/statements.py, the ones counter locality and `claims.py why` read, so an edit
elsewhere in the file leaves the id alone, and an edit to the statement itself gives new ids.

`coverage` runs every tests/*_test.py once, unmutated, in a copy laid out as a mutant's run, with
a line tracer of the standard library (sys.settrace and threading.settrace, started by a
sitecustomize.py on PYTHONPATH, so Python subprocesses of a test are traced too, except those run
with -I or -E, which Python keeps from PYTHONPATH: no package code runs in those). It writes the map:
which test files execute which lines, each file's cases and run time, over the source identity of
tests/mutants.py (the git tree id of a clean checkout). A case that fails there is BASELINE_RED
and no map is written, since every mutant on it would read as KILLED.

`run` takes that map (refused unless it names this tree) and hands the mutants to tests/mutants.py's
run_all in hunt mode: the same parallel controller, shards, matrix, merge and source identity, with
the map as the baseline. Each mutant runs only the test files that execute its statement, the
cheapest first, and stops at the first that notices it. Outcomes:

    KILLED    a case failed (the row names the cases)
    CRASHED   a test file wrote no results (the suite would go red, but on no assertion)
    TIMEOUT   a test file ran past its limit (TIMEOUT_FACTOR x its unmutated time, at least TIMEOUT_MIN s)
    SURVIVED  every test file that executes the statement passed
    NOT_RUN   no test file executes the statement (per the map)
    INVALID   the mutated file does not compile, or the mutation changes no syntax

The exit status says whether the hunt ran, never whether something survived: 0 when every chosen
mutant got an outcome, 2 on a stale map, a red baseline or a source that changed during the run.

`report` turns a merged matrix into DIR/survivors.json (warrant-generated/list@1: every id with its
outcome; the survivors with where they are; the tree) and DIR/report.md. With --previous (the last
run's list) it names what changed since that tree: BLIND, a mutant KILLED or CRASHED before that
survives now (a witness went blind; a TIMEOUT depends on the runner's load and counts for neither
side), and NEW, a survivor whose id the previous run did not have.
A survivor that changes no behaviour is not a blind spot: tests/equivalent_mutants.json lists such
ids with a reason (reviewed like any change), and the report counts them apart. An equivalent id
that some test notices is a wrong entry; the report names it (EQUIVALENT_NOTICED), as it names
entries whose id is no longer generated (EQUIVALENT_STALE)."""
import ast
import collections
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True      # importing tests/mutants.py must not write tests/__pycache__ (NO_BYTECODE)
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import mutants as MU                # noqa: E402

PROG = "generated_mutants"
COVERAGE = "warrant-generated/coverage@1"
LIST = "warrant-generated/list@1"
EQUIVALENT = "warrant-generated/equivalent@1"
EQUIVALENT_FILE = ROOT / "tests" / "equivalent_mutants.json"
# Where the generator looks, relative to the repository root; the claims selftests are tests.
ROOTS = ("warrant", "warrant_agent", "tools/claimslib")
NOT_CODE = ("tools/claimslib/selftest.py", "tools/claimslib/report_selftest.py")
# What a run copies: the three directories every mutant's run has, whichever file it changes.
COPIED = ("warrant", "warrant_agent", "tools")
NOTICED = ("KILLED", "CRASHED", "TIMEOUT")
# What the comparison with a previous run counts as noticed: a TIMEOUT depends on the runner's load
# (a mutant that only slows a test file down reads TIMEOUT on a busy runner and SURVIVED on an idle
# one: six jcs.py mutants did so between two local runs), so it neither makes a later survivor
# BLIND nor closes an earlier one.
SURELY_NOTICED = ("KILLED", "CRASHED")
OUTCOMES = ("KILLED", "CRASHED", "TIMEOUT", "SURVIVED", "NOT_RUN", "INVALID")
TIMEOUT_FACTOR, TIMEOUT_MIN = 5, 30


def _statements():
    """tools/claimslib/statements.py, loaded by path: the package's __init__ would put the
    checkout's warrant on sys.path."""
    spec = importlib.util.spec_from_file_location("claims_statements", ROOT / "tools" / "claimslib" / "statements.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ST = _statements()


def source_files(root=ROOT):
    """[relative path]: the Python files the generator mutates, sorted."""
    out = []
    for top in ROOTS:
        d = root / top
        out += [p.relative_to(root).as_posix() for p in sorted(d.rglob("*.py")) if "__pycache__" not in p.parts]
    return sorted(p for p in out if p not in NOT_CODE)


# ---------------------------------------------------------------- the generator

CMP_SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq,
            ast.NotEq: ast.Eq, ast.In: ast.NotIn, ast.NotIn: ast.In, ast.Is: ast.IsNot, ast.IsNot: ast.Is}
NOT_DELETED = (ast.Pass, ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal)


def _head(st):
    """The statement without its statement lists: what a compound unit owns (its children are
    units of their own)."""
    lists = [f for f in ST.STMT_LISTS if isinstance(getattr(st, f, None), list)]
    if not lists:
        return st
    import copy
    head = copy.copy(st)
    for f in lists:
        setattr(head, f, [])
    return head


def _sites(st):
    """The expression nodes of a unit an operator may change, in ast.walk order: none inside an
    f-string (3.11 gives them no reliable position), a type annotation or a match pattern."""
    head = _head(st)
    skip = set()
    for n in ast.walk(head):
        if isinstance(n, ast.JoinedStr):
            skip |= {id(x) for x in ast.walk(n)}
        for f in ("annotation", "returns"):
            a = getattr(n, f, None)
            if isinstance(a, ast.AST):
                skip |= {id(x) for x in ast.walk(a)}
        if isinstance(n, ast.match_case):
            skip |= {id(x) for x in ast.walk(n.pattern)}
    return [n for n in ast.walk(head) if id(n) not in skip and hasattr(n, "end_col_offset")]


def _bool_typed(e):
    return isinstance(e, (ast.Compare, ast.BoolOp)) or (isinstance(e, ast.UnaryOp) and isinstance(e.op, ast.Not))


EMPTY = {ast.List: "[]", ast.ListComp: "[]", ast.Dict: "{}", ast.DictComp: "{}", ast.Tuple: "()",
         ast.Set: "set()", ast.SetComp: "set()"}


def _operators(st):
    """[(family, variant, node, replacement source)] for one unit, in a fixed order: family by
    family, sites in ast.walk order. A replacement is the source of the node it replaces."""
    out = []
    sites = _sites(st)
    tests = []
    if isinstance(st, (ast.If, ast.While, ast.Assert)):
        tests.append(st.test)
    tests += [n.test for n in sites if isinstance(n, ast.IfExp)]
    tests += [c for n in sites if isinstance(n, ast.comprehension) for c in n.ifs]
    for t in tests:
        out.append(("NEGATE", "not", t, f"(not ({ast.unparse(t)}))"))
    for n in sites:
        if isinstance(n, ast.Compare):
            for k, op in enumerate(n.ops):
                new = ast.Compare(left=n.left, ops=list(n.ops), comparators=n.comparators)
                new.ops[k] = CMP_SWAP[type(op)]()
                out.append(("COMPARE", f"{type(op).__name__}->{CMP_SWAP[type(op)].__name__}", n, f"({ast.unparse(new)})"))
    for n in sites:
        if isinstance(n, ast.BoolOp):
            new = ast.BoolOp(op=ast.Or() if isinstance(n.op, ast.And) else ast.And(), values=n.values)
            out.append(("BOOLOP", "and->or" if isinstance(n.op, ast.And) else "or->and", n, f"({ast.unparse(new)})"))
    if _head(st) is st:
        if not isinstance(st, NOT_DELETED) and not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant)):
            out.append(("DELETE", "pass", st, "pass"))
    if isinstance(st, ast.Return) and st.value is not None:
        v = st.value
        if not (isinstance(v, ast.Constant) and v.value is None):
            out.append(("RETURN", "None", v, "None"))
        if _bool_typed(v):
            out.append(("RETURN", "True", v, "True"))
        elif type(v) in EMPTY and (getattr(v, "elts", None) or getattr(v, "keys", None) or hasattr(v, "generators")):
            out.append(("RETURN", "empty", v, EMPTY[type(v)]))
        elif isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value:
            out.append(("RETURN", "empty", v, '""'))
    for n in sites:
        if isinstance(n, ast.Constant) and isinstance(n.value, bool):
            out.append(("BOOL", f"{n.value}->{not n.value}", n, str(not n.value)))
    for n in sites:
        if isinstance(n, ast.Constant) and type(n.value) is int:
            out.append(("INT", "+1", n, f"({n.value + 1})"))
            out.append(("INT", "-1", n, f"({n.value - 1})"))
    return out


def _span(node):
    return node.lineno, node.col_offset, node.end_lineno, node.end_col_offset


def splice(src, span, new):
    """`src` with the node at `span` ((line, byte column) to (line, byte column), as ast gives
    them: columns count UTF-8 bytes) replaced by `new`."""
    l1, c1, l2, c2 = span
    lines = src.encode().splitlines(keepends=True)
    head = b"".join(lines[:l1 - 1]) + lines[l1 - 1][:c1]
    tail = lines[l2 - 1][c2:] + b"".join(lines[l2:])
    return (head + new.encode() + tail).decode()


def _segment(raw, node):
    """The source of `node` from the file's lines as bytes (ast.get_source_segment splits the
    whole file on every call)."""
    l1, c1, l2, c2 = _span(node)
    if l1 == l2:
        return raw[l1 - 1][c1:c2].decode()
    return (raw[l1 - 1][c1:] + b"".join(raw[l1:l2 - 1]) + raw[l2 - 1][:c2]).decode()


def _mid(path, scope, dump, occ, family, variant, site):
    key = json.dumps([path, scope, dump, occ, family, variant, site])
    return "G" + hashlib.sha256(key.encode()).hexdigest()[:12]


def generate_file(path, src):
    """[mutant dict] for one file's source: id, file, unit index ("at" key of statements.py),
    own lines, scope, function, operator, what, span, replacement."""
    nodes, units = [], []
    ST._units(ast.parse(src).body, "", 0, units, nodes=nodes)
    lines = ST.statement_lines(src)
    seen = collections.Counter()
    raw = src.encode().splitlines(keepends=True)
    out = []
    for i, ((scope, _, dump), st, (_, fn, own)) in enumerate(zip(units, nodes, lines)):
        occ = seen[(scope, dump)]
        seen[(scope, dump)] += 1
        sites = collections.Counter()
        for family, variant, node, new in _operators(st):
            site = sites[(family, variant)]
            sites[(family, variant)] += 1
            old = _segment(raw, node)
            old1 = " ".join(old.split())
            out.append({"id": _mid(path, scope, dump, occ, family, variant, site), "file": path, "unit": i,
                        "line": node.lineno, "lines": sorted(own), "scope": scope.rstrip(".") or "<module>",
                        "function": fn, "operator": f"{family}:{variant}", "span": list(_span(node)), "new": new,
                        "what": f"{family} {(old1[:70] + '…') if len(old1) > 70 else old1} -> {new[:40]}"})
    return out


def generate(root=ROOT, files=None):
    """Every generated mutant of the source files, in file then unit order. Two mutants with one
    id is a generator defect and raises."""
    out = []
    for path in files or source_files(root):
        out += generate_file(path, (root / path).read_text())
    ids = collections.Counter(m["id"] for m in out)
    twice = sorted(i for i, n in ids.items() if n > 1)
    if twice:
        raise RuntimeError(f"generated ids used twice: {' '.join(twice[:5])}")
    return out


def mutated(src, m):
    """(the mutated source, None) or (None, why it is INVALID)."""
    try:
        new = splice(src, tuple(m["span"]), m["new"])
    except (IndexError, UnicodeDecodeError) as e:
        return None, f"span: {e}"
    try:
        tree = ast.parse(new)
        compile(tree, m["file"], "exec")
    except (SyntaxError, ValueError) as e:
        return None, f"does not compile: {e.msg if isinstance(e, SyntaxError) else e}"
    if ast.dump(tree) == ast.dump(ast.parse(src)):
        return None, "no syntax change"
    return new, None


# ---------------------------------------------------------------- the coverage map

TRACER = r'''
# Written by tests/generated_mutants.py coverage: records the lines executed in files under
# $WARRANT_TRACE_ROOT into $WARRANT_TRACE_DIR, at exit or on SIGTERM.
import atexit, json, os, signal, sys, threading
_root = os.path.realpath(os.environ["WARRANT_TRACE_ROOT"]) + os.sep
_out = os.environ["WARRANT_TRACE_DIR"]
_hits, _keep = set(), {}
def _local(frame, event, arg):
    if event == "line":
        _hits.add((frame.f_code.co_filename, frame.f_lineno))
    return _local
def _global(frame, event, arg):
    f = frame.f_code.co_filename
    k = _keep.get(f)
    if k is None:
        k = _keep[f] = bool(f) and not f.startswith("<") and os.path.realpath(f).startswith(_root)
    return _local if k else None
def _dump():
    sys.settrace(None)
    threading.settrace(None)
    d = {}
    for f, n in list(_hits):
        d.setdefault(os.path.relpath(os.path.realpath(f), _root), set()).add(n)
    p = os.path.join(_out, "%d-%d.json" % (os.getpid(), threading.get_ident()))
    with open(p, "w") as fh:
        json.dump({k: sorted(v) for k, v in d.items()}, fh)
def _term(signum, frame):
    _dump()
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
atexit.register(_dump)
if threading.current_thread() is threading.main_thread() and signal.getsignal(signal.SIGTERM) == signal.SIG_DFL:
    signal.signal(signal.SIGTERM, _term)
sys.settrace(_global)
threading.settrace(_global)
'''


def test_files(root=ROOT):
    return sorted(p.stem for p in (root / "tests").glob("*_test.py"))


def copy_tree(tmp, root=ROOT):
    """The layout of every run, mutated or not: the three directories under `tmp`."""
    for top in COPIED:
        shutil.copytree(root / top, tmp / top, ignore=shutil.ignore_patterns("__pycache__"))


def run_test(tmp, test, timeout, env_extra=None, root=ROOT):
    """(results or None or "TIMEOUT", seconds): one test file against the packages in `tmp`, in
    its own process group, killed whole at `timeout`."""
    res = tmp / f"results-{test}.json"
    env = dict(os.environ, WARRANT_IMPL=str(tmp), WARRANT_RESULTS=str(res), PYTHONDONTWRITEBYTECODE=MU.NO_BYTECODE,
               **(env_extra or {}))
    t0 = time.monotonic()
    p = subprocess.Popen([sys.executable, str(root / "tests" / f"{test}.py")], env=env, cwd=root / "tests",
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)
        p.wait()
        return "TIMEOUT", time.monotonic() - t0
    try:
        os.killpg(p.pid, signal.SIGKILL)            # a child the test left behind
    except ProcessLookupError:
        pass
    return (json.loads(res.read_text()) if res.exists() else None), time.monotonic() - t0


def coverage_map(jobs, root=ROOT, tests=None):
    """(map, red): every test file run once, unmutated and traced, in parallel. `red` lists the
    files whose run failed a case or gave no results; with any, the map must not be used."""
    import concurrent.futures
    tests = tests or test_files(root)

    def one(test):
        tmp = Path(tempfile.mkdtemp(prefix=f"warrant-cov-{test}-"))
        hook, trace = tmp.with_name(tmp.name + "-hook"), tmp.with_name(tmp.name + "-trace")
        try:
            copy_tree(tmp, root)
            hook.mkdir()
            trace.mkdir()
            (hook / "sitecustomize.py").write_text(TRACER)
            pp = os.pathsep.join([str(hook)] + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
            results, secs = run_test(tmp, test, 3600, {"PYTHONPATH": pp, "WARRANT_TRACE_ROOT": str(tmp),
                                                       "WARRANT_TRACE_DIR": str(trace)}, root)
            lines = {}
            for f in sorted(trace.glob("*.json")):
                for rel, ns in json.loads(f.read_text()).items():
                    lines.setdefault(rel, set()).update(ns)
            return results, secs, {k: sorted(v) for k, v in sorted(lines.items()) if not k.startswith("..")}
        finally:
            for d in (tmp, hook, trace):
                shutil.rmtree(d, ignore_errors=True)

    out, red = {}, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        for test, (results, secs, lines) in zip(tests, pool.map(one, tests)):
            failing = None if not isinstance(results, dict) else sorted(k for k, v in results.items() if v != "PASS")
            if failing is None or failing:
                red.append((test, failing))
            out[test] = {"results": results, "seconds": round(secs, 2), "lines": lines}
    return out, red


def load_map(path, root=ROOT):
    """The map at `path`, or SystemExit 2 when it is unreadable, of another format, of another
    tree or from a red baseline."""
    try:
        doc = json.loads(Path(path).read_text())
    except (OSError, ValueError) as e:
        raise SystemExit(f"COVERAGE_UNREADABLE {path}: {e}") from None
    if doc.get("format") != COVERAGE:
        raise SystemExit(f"COVERAGE_FORMAT {path}: {doc.get('format')!r}, not {COVERAGE}")
    try:
        src = MU.source_digest(root)
    except MU.SourceUnknown as e:
        raise SystemExit(f"SOURCE_UNKNOWN {e}") from None
    if doc.get("source") != src:
        raise SystemExit(f"COVERAGE_STALE {path} names {doc.get('source')}, this checkout is {src}")
    return doc


def covering(m, cmap):
    """The test files that execute any own line of m's statement, cheapest first."""
    own = set(m["lines"])
    hit = [t for t, d in cmap["tests"].items() if own & set(d["lines"].get(m["file"], ()))]
    return tuple(sorted(hit, key=lambda t: (cmap["tests"][t]["seconds"], t)))


def as_tuples(gen, cmap):
    """tests/mutants.py's shape: (id, file, what, edits, test files, targets). The one edit is
    [span, replacement]; a generated mutant has no target cases."""
    return [(m["id"], m["file"], m["what"], [["%d:%d-%d:%d" % tuple(m["span"]), m["new"]]], covering(m, cmap), ())
            for m in gen]


def _parse_span(s):
    a, b = s.split("-")
    return tuple(int(x) for x in a.split(":") + b.split(":"))


def classify(runs, tests):
    """(outcome, detail) from the runs of a mutant's test files in its order, as run_generated
    stops: the first file that notices decides."""
    if not tests:
        return "NOT_RUN", "no test file executes the statement"
    for t in tests:
        if t not in runs:
            return "INVALID", f"{t} was not run"
        r = runs[t]
        if r == "TIMEOUT":
            return "TIMEOUT", t
        if r is None:
            return "CRASHED", f"{t}: no results"
        failed = sorted(k for k, v in r.items() if v != "PASS")
        if failed:
            return "KILLED", f"{t}:{','.join(failed)}"
    return "SURVIVED", ",".join(tests)


def make_runner(cmap, root=ROOT):
    limits = {t: max(TIMEOUT_MIN, TIMEOUT_FACTOR * d["seconds"]) for t, d in cmap["tests"].items()}

    def run_generated(mid, fname, what, edits, tests, targets, also=()):
        """(outcome, detail, runs): the mutant applied to a copy, its test files run in order
        until one notices it."""
        src = (root / fname).read_text()
        span, new = edits[0]
        text, bad = mutated(src, {"span": _parse_span(span), "new": new, "file": fname})
        if bad:
            return "INVALID", bad, {}
        if not tests:
            return (*classify({}, tests), {})
        tmp = Path(tempfile.mkdtemp(prefix=f"warrant-{mid}-"))
        try:
            copy_tree(tmp, root)
            (tmp / fname).write_text(text)
            runs = {}
            for t in tests:
                runs[t] = run_test(tmp, t, limits[t], root=root)[0]
                outcome, detail = classify(runs, [x for x in tests if x in runs])
                if outcome in NOTICED:
                    return outcome, detail, runs
            return (*classify(runs, tests), runs)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return run_generated


def judge(row, m, root=ROOT):
    """The outcome a matrix row's own runs give (merge recomputes it): INVALID from the
    mutation itself, the rest from classify()."""
    if row.get("outcome") == "INVALID":
        span, new = m[3][0]
        _, bad = mutated((root / m[1]).read_text(), {"span": _parse_span(span), "new": new, "file": m[1]})
        return "INVALID" if bad else "NOT_INVALID"
    return classify(row.get("runs") or {}, m[4])[0]


def hunt(cmap, root=ROOT):
    """tests/mutants.py's Hunt for these mutants: cost = the run time of every covering test file
    (an upper bound; a kill stops early), baseline = the map's own unmutated runs."""
    secs = {t: d["seconds"] for t, d in cmap["tests"].items()}

    def baseline(chosen):
        red = []
        for t, d in sorted(cmap["tests"].items()):
            r = d["results"]
            failing = None if not isinstance(r, dict) else sorted(k for k, v in r.items() if v != "PASS")
            if failing is None or failing:
                red.append((t, "", failing, [m[0] for m in chosen if t in m[4]]))
        return red
    return MU.Hunt(judge=lambda row, m: judge(row, m, root), cost=lambda m: sum(secs.get(t, 1.0) for t in m[4]) + 0.2,
                   baseline=baseline)


# ---------------------------------------------------------------- the report

def load_equivalent(path=EQUIVALENT_FILE):
    """{id: reason}; SystemExit on a malformed file (an entry without a reason is not one)."""
    if not Path(path).exists():
        return {}
    doc = json.loads(Path(path).read_text())
    if doc.get("format") != EQUIVALENT or not isinstance(doc.get("mutants"), dict):
        raise SystemExit(f"EQUIVALENT_FORMAT {path}: not {EQUIVALENT}")
    out = {}
    for mid, e in doc["mutants"].items():
        if not (isinstance(e, dict) and isinstance(e.get("reason"), str) and e["reason"].strip()):
            raise SystemExit(f"EQUIVALENT_FORMAT {path}: {mid} has no reason")
        out[mid] = e["reason"]
    return out


def build_list(matrix, gen, equivalent, previous=None, audit=None):
    """The list document: outcomes by id, survivors with where they are, per-file counts, the
    blind (claim, mutant) pairs of `audit` (claims.py audit --json over full matrices of the
    curated mutants), and what changed since `previous`: BLIND, NEW and CLOSED mutants, and the
    pairs new since then (when the previous list had pairs)."""
    by_id = {m["id"]: m for m in gen}
    rows = matrix["mutants"]
    outcomes = {mid: rows[mid]["outcome"] for mid in sorted(rows)}
    per = {}
    for mid, o in outcomes.items():
        f = by_id[mid]["file"] if mid in by_id else rows[mid]["file"]
        c = per.setdefault(f, dict.fromkeys(OUTCOMES + ("EQUIVALENT",), 0))
        if o == "SURVIVED" and mid in equivalent:
            c["EQUIVALENT"] += 1
        else:
            c[o] += 1
    survivors = {}
    for mid, o in outcomes.items():
        if o == "SURVIVED" and mid not in equivalent:
            m = by_id.get(mid, {})
            survivors[mid] = {k: m.get(k) for k in ("file", "line", "scope", "function", "operator", "what")}
            survivors[mid]["tests"] = list(rows[mid].get("test") or [])
    findings = []
    for mid in sorted(equivalent):
        if mid not in outcomes:
            findings.append(("EQUIVALENT_STALE", mid, "no longer generated"))
        elif outcomes[mid] in NOTICED:
            findings.append(("EQUIVALENT_NOTICED", mid, f"marked equivalent but {outcomes[mid]}: "
                             f"{rows[mid].get('detail', '')}"))
    doc = {"format": LIST, "source": matrix["source"], "generated": len(outcomes), "outcomes": outcomes,
           "per_file": per, "survivors": survivors, "equivalent": sorted(set(equivalent) & set(outcomes)),
           "findings": [list(f) for f in findings]}
    if audit is not None:
        doc["audit_source"] = audit["source"]
        doc["pairs"] = [[b["claim"], b["mutant"], b["tier"], b["confined"]] for b in audit["blind"]]
        doc["unknown_pairs"] = len(audit["unknown"])
    if previous is not None:
        before = previous.get("outcomes", {})
        doc["since"] = {"source": previous.get("source"),
                        "blind": sorted(mid for mid in survivors if before.get(mid) in SURELY_NOTICED),
                        "new": sorted(mid for mid in survivors if mid not in before),
                        "closed": sorted(mid for mid, o in outcomes.items()
                                         if o in SURELY_NOTICED and before.get(mid) == "SURVIVED")}
        if "pairs" in doc and "pairs" in previous:
            had = {(c, m) for c, m, *_ in previous["pairs"]}
            doc["since"]["new_pairs"] = [p for p in doc["pairs"] if (p[0], p[1]) not in had]
    return doc


def render(doc):
    total = collections.Counter()
    for c in doc["per_file"].values():
        total.update(c)
    out = ["# Generated mutants: survivor report", "",
           f"Source `{doc['source']}`; {doc['generated']} generated. A survivor is a candidate blind spot, "
           "not a defect: it may be equivalent (tests/equivalent_mutants.json). Generated mutants never back a claim.", ""]
    if "since" in doc:
        s = doc["since"]
        out += [f"## Since `{s['source']}`", "",
                f"- BLIND (KILLED or CRASHED before, surviving now): {len(s['blind'])}",
                f"- NEW (a survivor the previous run did not generate): {len(s['new'])}",
                f"- CLOSED (surviving before, KILLED or CRASHED now): {len(s['closed'])}"]
        if "new_pairs" in s:
            out.append(f"- new blind pairs (claims.py audit): {len(s['new_pairs'])}")
            out += [f"  - {c} blind to {m} [{t}{', confined' if k else ''}]" for c, m, t, k in s["new_pairs"]]
        out.append("")
        for mid in s["blind"] + s["new"]:
            m = doc["survivors"][mid]
            out.append(f"- {'BLIND' if mid in s['blind'] else 'NEW'} `{mid}` {m['file']}:{m['line']} "
                       f"({m['function'] or m['scope']}) {m['what']}")
        out.append("")
    if "pairs" in doc:
        out += ["## Blind pairs (claims.py audit, full matrices of the curated mutants)", "",
                f"{len(doc['pairs'])} pairs: a BACKED claim, and a curated mutant of its code that some case kills while "
                f"every witness of the claim passes; {doc['unknown_pairs']} unknown (a witness file not run).", ""]
        out += [f"- {c} blind to {m} [{t}{', confined: its counter would replay' if k else ''}]"
                for c, m, t, k in doc["pairs"]] + [""]
    cols = OUTCOMES + ("EQUIVALENT",)
    out += ["## Outcomes per file", "", "| file | " + " | ".join(cols) + " |", "| --- |" + " --- |" * len(cols)]
    for f, c in sorted(doc["per_file"].items()):
        out.append(f"| {f} | " + " | ".join(str(c[k]) for k in cols) + " |")
    out.append("| **total** | " + " | ".join(str(total[k]) for k in cols) + " |")
    out += ["", "## Findings about the equivalence list", ""]
    out += [f"- {code} `{mid}`: {why}" for code, mid, why in doc["findings"]] or ["- none"]
    byfn = collections.Counter((m["file"], m["function"] or m["scope"]) for m in doc["survivors"].values())
    out += ["", "## Survivors by function, most first", ""]
    out += [f"- {n} `{f}` {fn}" for (f, fn), n in byfn.most_common(40)] or ["- none"]
    out += ["", f"## Survivors ({len(doc['survivors'])})", ""]
    for mid, m in sorted(doc["survivors"].items(), key=lambda x: (x[1]["file"], x[1]["line"], x[0])):
        out.append(f"- `{mid}` {m['file']}:{m['line']} ({m['function'] or m['scope']}) {m['what']}")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- commands

def _opt(argv, name, default=None):
    if name in argv:
        k = argv.index(name)
        if k + 1 >= len(argv):
            raise SystemExit(f"{name} needs a value")
        return argv[k + 1], argv[:k] + argv[k + 2:]
    return default, argv


def cmd_list(argv):
    js = "--json" in argv
    files = [a for a in argv if a != "--json"] or None
    gen = generate(files=files)
    if js:
        print(json.dumps(gen, indent=1))
        return 0
    c = collections.Counter(m["operator"].split(":")[0] for m in gen)
    for m in gen:
        print(f"{m['id']} {m['file']}:{m['line']} {m['what']}")
    print(f"GENERATED: {len(gen)} mutants in {len({m['file'] for m in gen})} files; "
          + ", ".join(f"{k} {v}" for k, v in sorted(c.items())))
    return 0


def cmd_coverage(argv):
    out, argv = _opt(argv, "--out")
    jobs, argv = _opt(argv, "--jobs", str(os.cpu_count() or 2))
    if not out or argv:
        raise SystemExit("usage: generated_mutants.py coverage --out MAP.json [--jobs N]")
    try:
        before = MU.source_digest(ROOT)
    except MU.SourceUnknown as e:
        print(f"SOURCE_UNKNOWN {e}")
        return 2
    t0 = time.monotonic()
    tests, red = coverage_map(int(jobs))
    for t, failing in red:
        print(f"BASELINE_RED {t} unmutated " + ("gave no results" if failing is None else f"fails {','.join(failing)}"))
    if red:
        print("COVERAGE: BASELINE_RED, no map written: a case that fails unmutated would read as a kill")
        return 2
    if MU.source_digest(ROOT) != before:
        print("COVERAGE: SOURCE_CHANGED during the run, no map written")
        return 2
    doc = {"format": COVERAGE, "source": before, "python": sys.version.split()[0], "tests": tests}
    Path(out).write_text(json.dumps(doc, sort_keys=True) + "\n")
    n = sum(len(v) for d in tests.values() for v in d["lines"].values())
    print(f"COVERAGE: {len(tests)} test files, {n} (file, line) hits, {time.monotonic() - t0:.0f} s; map written to {out}")
    return 0


def cmd_run(argv):
    path, argv = _opt(argv, "--coverage")
    if not path:
        raise SystemExit("run needs --coverage MAP.json (generated_mutants.py coverage --out MAP.json)")
    cmap = load_map(path)
    gen = generate()
    return MU.run_all(as_tuples(gen, cmap), "GENERATED MUTANTS", argv, make_runner(cmap), prog=PROG, hunt=hunt(cmap))


def cmd_merge(argv):
    path, argv = _opt(argv, "--coverage")
    if not path or len(argv) < 2:
        raise SystemExit("usage: generated_mutants.py merge --coverage MAP.json OUT PART.json ...")
    cmap = load_map(path)
    return MU.run_all(as_tuples(generate(), cmap), "GENERATED MUTANTS", ["--merge", *argv], None, prog=PROG,
                      hunt=hunt(cmap))


def cmd_report(argv):
    out, argv = _opt(argv, "--out")
    prev, argv = _opt(argv, "--previous")
    aud, argv = _opt(argv, "--audit")
    if not out or len(argv) != 1:
        raise SystemExit("usage: generated_mutants.py report MATRIX.json --out DIR [--previous LIST.json] [--audit AUDIT.json]")
    matrix = json.loads(Path(argv[0]).read_text())
    if matrix.get("matrix") != MU.MATRIX or matrix.get("harness") != PROG or "shard" in matrix:
        raise SystemExit(f"REPORT_MATRIX {argv[0]}: not a merged matrix of {PROG}")
    gen = generate()
    if set(matrix["mutants"]) != {m["id"] for m in gen}:
        raise SystemExit(f"REPORT_MATRIX {argv[0]}: its ids are not this checkout's generated mutants")
    previous = None
    if prev:
        previous = json.loads(Path(prev).read_text())
        if previous.get("format") != LIST:
            raise SystemExit(f"REPORT_PREVIOUS {prev}: not {LIST}")
    audit = None
    if aud:
        audit = json.loads(Path(aud).read_text())
        if audit.get("format") != "warrant-claims/audit@1" or audit.get("source") != matrix["source"]:
            raise SystemExit(f"REPORT_AUDIT {aud}: not an audit of the tree the matrix ran over")
    doc = build_list(matrix, gen, load_equivalent(), previous, audit)
    d = Path(out)
    d.mkdir(parents=True, exist_ok=True)
    (d / "survivors.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    (d / "report.md").write_text(render(doc))
    c = collections.Counter(doc["outcomes"].values())
    print(f"REPORT: {doc['generated']} generated; " + ", ".join(f"{k} {c[k]}" for k in OUTCOMES)
          + f"; {len(doc['equivalent'])} marked equivalent; {len(doc['survivors'])} survivors listed"
          + (f"; since {doc['since']['source']}: {len(doc['since']['blind'])} BLIND, {len(doc['since']['new'])} NEW"
             if "since" in doc else "; no previous list")
          + (f"; {len(doc['pairs'])} blind pairs" if "pairs" in doc else "")
          + (f", {len(doc['since']['new_pairs'])} new" if "new_pairs" in doc.get("since", {}) else ""))
    for code, mid, why in doc["findings"]:
        print(f"{code} {mid}: {why}")
    return 0


def main(argv):
    if argv[:1] == ["--selftest"]:
        return selftest()
    cmds = {"list": cmd_list, "coverage": cmd_coverage, "run": cmd_run, "merge": cmd_merge, "report": cmd_report}
    if not argv or argv[0] not in cmds:
        print(__doc__)
        return 2
    return cmds[argv[0]](argv[1:])


TOY = """\
LIMIT = 3
assert LIMIT > 2


def double(x):
    return x * 2


def sign(x):
    if x < 0:
        return -1
    return 1


def spin(n):
    while n > 0:
        n -= 1
    return n


def child():
    return "ok"


def serve():
    mark = 1
    import time
    time.sleep(60)
    return mark


def unused(x, flag=True):
    return x + 1 if flag and x else [x]
"""

TOY_TEST = """\
import json, os, subprocess, sys, time
sys.path.insert(0, os.environ["WARRANT_IMPL"])
from warrant import toy
code = "import sys; sys.path.insert(0, %r); from warrant import toy; print(toy.%s())"
out = subprocess.run([sys.executable, "-c", code % (os.environ["WARRANT_IMPL"], "child")], capture_output=True, text=True).stdout
p = subprocess.Popen([sys.executable, "-c", code % (os.environ["WARRANT_IMPL"], "serve")])
time.sleep(float(os.environ.get("TOY_WAIT", "0")))
p.terminate()
p.wait()
r = {"T1": toy.double(3) == 6, "T2": toy.sign(-5) == -1, "T3": toy.spin(3) == 0, "T4": out.strip() == "ok"}
json.dump({k: "PASS" if v else "FAIL" for k, v in r.items()}, open(os.environ["WARRANT_RESULTS"], "w"))
"""

FIXTURE = """\
def f(a, b, *, c: int = 3) -> bool:
    if a < b and c:
        return True
    x = [i for i in a if i]
    y = 1 if b else 0
    z = f"{a < b}"
    return a == b or not c


def g(a, b):
    return "é…" if a < b else 2
"""


def selftest():
    """The generator, the tracer, the runner's outcomes on a fixture repository, the judge merge
    relies on, the report's comparison with a previous run, and the claims tool's refusal of a
    generated id as backing."""
    import contextlib
    import io

    def generator():
        checks = []

        def ids(src, path="warrant/x.py"):
            return {m["id"]: m for m in generate_file(path, src)}
        base = ids(FIXTURE)
        fams = {m["operator"].split(":")[0] for m in base.values()}
        shifted = ids("import os  # a new first line\n\n\ndef h():\n    return 0\n\n\n" + FIXTURE.replace("    x = [", "    # note\n    x = ["))
        edited = ids(FIXTURE.replace("if a < b and c:", "if a < b and not c:"))
        header = {i for i, m in base.items() if m["line"] == 2}
        valid = [mutated(FIXTURE, m) for m in base.values()]
        g_cmp = next(m for m in base.values() if m["operator"] == "COMPARE:Lt->LtE" and m["scope"] == "g")
        g_new = mutated(FIXTURE, g_cmp)[0] or ""
        twice = generate_file("warrant/x.py", "def f():\n    a = 1\n    a = 1\n")
        checks += [
            ("every operator family is generated", fams == {"NEGATE", "COMPARE", "BOOLOP", "DELETE", "RETURN", "BOOL", "INT"}),
            ("an edit elsewhere in the file keeps every id, and what it changes",
             set(base) <= set(shifted) and all(shifted[i]["what"] == m["what"] for i, m in base.items())),
            ("an edit to a statement renews its ids and only its ids",
             set(base) - set(edited) == header and header and set(base) - header <= set(edited)),
            ("equal statements in one scope get distinct ids",
             len({m["id"] for m in twice}) == len(twice) and sum(m["operator"] == "DELETE:pass" for m in twice) == 2),
            ("every fixture mutant compiles and changes the syntax", all(t is not None and bad is None for t, bad in valid)),
            ("columns are UTF-8 bytes: a mutant after a non-ASCII literal lands on its node",
             "a <= b" in g_new and "é…" in g_new),
            ("nothing inside an f-string or an annotation is mutated",
             not any(m["line"] == 6 and m["operator"].startswith("COMPARE") for m in base.values())
             and sum(m["operator"].startswith("INT") for m in base.values() if m["line"] == 1) == 2),
            ("a span that does not compile is INVALID", mutated(FIXTURE, dict(g_cmp, new="(a <=)"))[0] is None),
            ("a replacement with the same syntax is INVALID",
             mutated(FIXTURE, dict(g_cmp, new="(a < b)"))[1] == "no syntax change"),
            ("the same source generates the same list", generate_file("warrant/x.py", FIXTURE) == generate_file("warrant/x.py", FIXTURE)),
        ]
        return checks

    def outcomes():
        checks = []
        # classify(): the first test file that notices decides; none run is NOT_RUN
        checks += [
            ("classify: no covering test file is NOT_RUN", classify({}, ())[0] == "NOT_RUN"),
            ("classify: a failing case is KILLED and named", classify({"a": {"x": "PASS"}, "b": {"y": "FAIL"}}, ("a", "b"))
             == ("KILLED", "b:y")),
            ("classify: no results is CRASHED, a timeout TIMEOUT",
             classify({"a": None}, ("a", "b"))[0] == "CRASHED" and classify({"a": "TIMEOUT"}, ("a",))[0] == "TIMEOUT"),
            ("classify: SURVIVED only when every covering file ran and passed",
             classify({"a": {"x": "PASS"}}, ("a", "b"))[0] == "INVALID"
             and classify({"a": {"x": "PASS"}, "b": {}}, ("a", "b"))[0] == "SURVIVED"),
        ]
        return checks

    def fixture():
        checks = []
        # A fixture repository: the tracer (with a subprocess and a SIGTERM), the runner, the judge
        fx = Path(tempfile.mkdtemp(prefix="generated-selftest-"))
        git = ["git", "-c", "user.name=selftest", "-c", "user.email=selftest@invalid", "-c", "commit.gpgsign=false"]
        global TIMEOUT_MIN, TIMEOUT_FACTOR
        saved = TIMEOUT_MIN, TIMEOUT_FACTOR
        try:
            for d in COPIED + ("tests",):
                (fx / d).mkdir()
            (fx / "warrant" / "__init__.py").write_text("")
            (fx / "warrant" / "toy.py").write_text(TOY)
            (fx / "warrant_agent" / "__init__.py").write_text("")
            (fx / "tools" / "README").write_text("fixture\n")
            (fx / "tests" / "toy_test.py").write_text(TOY_TEST)
            (fx / ".gitignore").write_text("__pycache__/\n")
            subprocess.run(["git", "init", "-q", str(fx)], check=True)
            subprocess.run([*git, "-C", str(fx), "add", "-A"], check=True)
            subprocess.run([*git, "-C", str(fx), "commit", "-qm", "fixture"], check=True)
            os.environ["TOY_WAIT"] = "1"
            tests, red = coverage_map(1, root=fx)
            os.environ.pop("TOY_WAIT")
            cmap = {"format": COVERAGE, "source": MU.source_digest(fx), "tests": tests}
            hit = set(tests["toy_test"]["lines"].get("warrant/toy.py", ()))
            src = TOY.splitlines()
            line = {name: src.index(text) + 1 for name, text in (("child", '    return "ok"'), ("mark", "    mark = 1"),
                                                                  ("unused", "    return x + 1 if flag and x else [x]"),
                                                                  ("sign", "    if x < 0:"))}
            checks += [
                ("the unmutated fixture is green", red == [] and tests["toy_test"]["results"] == dict.fromkeys(["T1", "T2", "T3", "T4"], "PASS")),
                ("the tracer records the test's own process", line["sign"] in hit and line["unused"] not in hit),
                ("the tracer records a Python subprocess", line["child"] in hit),
                ("the tracer records a subprocess ended by SIGTERM", line["mark"] in hit),
            ]
            gen = generate(fx, ["warrant/toy.py"])
            tuples = as_tuples(gen, cmap)
            pick = {"killed": ("DELETE", line["sign"] + 1), "survived": ("COMPARE", line["sign"]),
                    "crashed": ("DELETE", 1), "timeout": ("DELETE", src.index("        n -= 1") + 1),
                    "not_run": ("RETURN", line["unused"]), "subprocess": ("DELETE", line["child"])}
            chosen = {k: next(t for t, m in zip(tuples, gen) if m["operator"].startswith(op) and m["line"] == ln)
                      for k, (op, ln) in pick.items()}
            TIMEOUT_MIN, TIMEOUT_FACTOR = 3, 1
            runner = make_runner(cmap, fx)
            got = {k: runner(*t) for k, t in chosen.items()}
            invalid = chosen["killed"][:3] + ([["1:0-1:4", "("]],) + chosen["killed"][4:]
            got["invalid"] = runner(*invalid)
            checks += [
                ("a mutant a case notices is KILLED, with the case", got["killed"][:2] == ("KILLED", "toy_test:T2")),
                ("a mutant every covering test passes is SURVIVED", got["survived"][0] == "SURVIVED"),
                ("a mutant that breaks the import is CRASHED", got["crashed"][0] == "CRASHED"),
                ("a mutant that loops is stopped as TIMEOUT", got["timeout"][0] == "TIMEOUT"),
                ("a statement no test executes is NOT_RUN, without a run", got["not_run"][:1] == ("NOT_RUN",) and got["not_run"][2] == {}),
                ("a statement only a subprocess executes is run and KILLED", got["subprocess"][:2] == ("KILLED", "toy_test:T4")),
                ("a mutant that does not compile is INVALID", got["invalid"][0] == "INVALID"),
                ("the judge merge uses recomputes every outcome from its row",
                 all(judge({"outcome": o, "runs": r}, t, fx) == o for t, (o, _, r) in ((chosen[k], got[k]) for k in chosen))
                 and judge({"outcome": "INVALID", "runs": {}}, invalid, fx) == "INVALID"
                 and judge({"outcome": "INVALID", "runs": {}}, chosen["killed"], fx) != "INVALID"),
            ]
            Path(fx / "map.json").write_text(json.dumps(dict(cmap, source="tree:" + "0" * 40)))
            try:
                load_map(fx / "map.json", fx)
                stale = None
            except SystemExit as e:
                stale = str(e)
            checks.append(("a map of another tree is refused COVERAGE_STALE", (stale or "").startswith("COVERAGE_STALE")))
        finally:
            TIMEOUT_MIN, TIMEOUT_FACTOR = saved
            shutil.rmtree(fx, ignore_errors=True)
        return checks

    def report():
        checks = []
        # The report: equivalents apart, and what changed since the previous list
        rows = {k: {"outcome": o, "file": "warrant/x.py", "test": ["t"], "detail": "t:c"} for k, o in
                (("GA", "SURVIVED"), ("GB", "KILLED"), ("GC", "SURVIVED"), ("GD", "SURVIVED"), ("GE", "SURVIVED"), ("GF", "KILLED"), ("GT", "SURVIVED"))}
        gen_ = [{"id": k, "file": "warrant/x.py", "line": 1, "scope": "f", "function": "f", "operator": "DELETE:pass", "what": k}
                for k in rows]
        prev = {"format": LIST, "source": "tree:before", "outcomes": {"GA": "KILLED", "GB": "SURVIVED", "GC": "SURVIVED", "GT": "TIMEOUT"},
                "pairs": [["SPEC-1-1", "M01", "line", True]]}
        aud = {"source": "tree:now", "unknown": [], "blind": [{"claim": "SPEC-1-1", "mutant": "M01", "tier": "line", "confined": True},
                                                              {"claim": "SPEC-2-1", "mutant": "M02", "tier": "function", "confined": False}]}
        doc = build_list({"source": "tree:now", "mutants": rows}, gen_, {"GE": "x", "GF": "y", "GZ": "z"}, prev, aud)
        checks += [
            ("a survivor some test KILLED before is BLIND; one that timed out before is not", doc["since"]["blind"] == ["GA"]),
            ("a survivor the previous run did not have is NEW; an equivalent one is not", doc["since"]["new"] == ["GD"]),
            ("a survivor noticed now is CLOSED", doc["since"]["closed"] == ["GB"]),
            ("equivalent ids are counted apart, not listed as survivors",
             sorted(doc["survivors"]) == ["GA", "GC", "GD", "GT"] and doc["per_file"]["warrant/x.py"]["EQUIVALENT"] == 1),
            ("an equivalent id a test notices, and one no longer generated, are named",
             [f[:2] for f in doc["findings"]] == [["EQUIVALENT_NOTICED", "GF"], ["EQUIVALENT_STALE", "GZ"]]),
            ("the audit's pairs are listed, and only a pair the previous list lacked is new",
             len(doc["pairs"]) == 2 and doc["since"]["new_pairs"] == [["SPEC-2-1", "M02", "function", False]]),
            ("the report renders the new pairs", "SPEC-2-1 blind to M02" in render(doc)),
        ]
        eq = Path(tempfile.mkdtemp(prefix="generated-selftest-eq-")) / "e.json"
        eq.write_text(json.dumps({"format": EQUIVALENT, "mutants": {"GA": {"reason": " "}}}))
        try:
            load_equivalent(eq)
            refused = False
        except SystemExit:
            refused = True
        shutil.rmtree(eq.parent, ignore_errors=True)
        checks.append(("an equivalence without a reason is refused", refused))
        checks.append(("the repository's equivalence list is well formed", isinstance(load_equivalent(), dict)))
        return checks

    def claims():
        checks = []
        # A generated id never backs a claim: the claims tool knows the curated harnesses only
        sys.path.insert(0, str(ROOT / "tools"))
        with contextlib.redirect_stdout(io.StringIO()):
            from claimslib.repo import Repo, witness_problems
        repo = Repo(ROOT)
        some = generate(files=["warrant/engine.py"])[0]["id"]
        checks.append(("the claims tool refuses a generated id as a claim's mutant; a curated one passes",
                       [p[0] for p in witness_problems(repo, ["contract_test:U2"], [some])] == ["UNKNOWN_MUTANT"]
                       and witness_problems(repo, ["contract_test:U2"], ["M03"]) == []))
        return checks

    checks = []
    for section in (generator, outcomes, fixture, report, claims):
        try:
            checks += section()
        except Exception:     # noqa: BLE001  a section that raises fails by name, not as a crash of the selftest
            import traceback
            traceback.print_exc()
            checks.append((f"the {section.__name__} section ran to its end", False))
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok  " if ok else "FAIL") + f"  {name}")
    print(f"GENERATED-SELFTEST: {'ALL PASS' if not bad else f'{len(bad)} FAILURES'} ({len(checks)} checks)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
