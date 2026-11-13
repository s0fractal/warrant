"""A specification's claims as claim@1 records: a normative sentence of the repository's specification (its
`.warrant/claims.json` names it) is a lineage whose versions carry the sentence verbatim, the section, the witnesses
(test cases `file_test:CASE`) and the mutants (ids the repository's mutant harness lists) that back it. A `backed` version waits for a claim/verifier's
acceptance: the claims checker (`replay`) accepts it after it ran the witnesses and the mutants at one
commit, naming that commit, its tree, the checker's code and its environment. Claims of a retired source
(in this package's repository, the Warrant 2 claims of SPEC.md) are history: retired, never deleted.

    python3 -m warrant.claims [--root DIR] check        # the store, and every live claim against the spec and tests
    python3 -m warrant.claims view [--out FILE]         # CLAIMS.md, a build artifact
    python3 -m warrant.claims file --from FILE.json --actor A --key SEED     # file new claims or new versions
    python3 -m warrant.claims retire-v2 --actor A --key SEED                 # retire every live claim of a retired source
    python3 -m warrant.claims identity                  # the claims checker's actor, code and environment
    python3 -m warrant.claims replay --key -            # the checker: run, then accept what held (clean tree only)
    python3 -m warrant.claims verify --base M           # CI: re-execute the checker's acceptances new since M

The repository is the one `--root` names, else the Git checkout around the current directory. Its
`.warrant/claims.json` says where the claims live: {"warrant": "claims/1", "source": the specification's path (or a
list of them: each claim names its own, and its sentence must be in that one),
"retired": [paths of retired sources], "witnesses": [glob patterns of the test files that print cases],
"mutants": the mutant harness's path, and optionally "coverage": [RFC 2119 keywords, e.g. "MUST", "SHALL", "REQUIRED"]}. A witness `NAME:CASE` names the file tests/NAME.py, or DIR/P/test.py as
`P/test`; the harness lists `{id: [file, test file, cases]}` with `--list` and writes `{"rows": [{id, outcome}]}`
with `IDS --matrix OUT`.

`check` refuses (exit 1): a store that is not canonical, rejects a line or has a problem (a schema short of its
quorum is a proposal, not one); a live claim of a retired source (V2_CLAIM_LIVE), whose sentence is not in the
specification (CLAIM_TEXT_MISSING), that cites a witness case no test file prints (WITNESS_MISSING), a mutant the
harness does not list (UNKNOWN_MUTANT) or one whose cases are not among its witnesses (MUTANT_OFF_CLAIM); a
`backed` claim with no witness or no mutant (UNBURNED); one id in two live lineages (CLAIM_ID_TWICE). It
never parses the spec to find claims: the records say where they are, and the spec must hold their words.

With "coverage", the converse is checked too, which the records alone cannot show (Codex finding 5c401f4c on
sigma-glyph#78: the registry did not hold every MUST, and nothing said so). Every occurrence of a listed keyword
in a source, as a whole uppercase word (the words of `MUST NOT` across any whitespace, a line break included) outside a
heading line (`#`), must lie entirely inside the span of some live claim's
sentence in that source, whatever the claim's state; one that does not is UNCLAIMED_KEYWORD. A sentence that
states no rule (the RFC 2119 boilerplate, a scope remark) is filed as an `informative` claim with its reason: the
exemption is a record, not a list in the configuration."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from . import imports as IM
from . import records as R
from . import pins as P
from .pins import blobs
from .store import Snapshot
from .repo import Failed, Repo, checker_problem, code_tree, dump, emit, env_root, git, identity, inside, load_key, main, tree_id

CONFIG = "claims/1"
CLAIM = "claim@1"
CHECKER = "claims-checker"            # the claims checker's actor: one key, bound once; its code is in each attest
CLOSURE = "imports/1"                # an acceptance's `files` are the import closure of each file that ran (files_of)
CASE_LINE = re.compile(r"""check\(\s*f?["']([A-Za-z0-9-]+)[ "']""")
KEYWORD = re.compile(r"[A-Z]+(?: [A-Z]+)*\Z")


def _relative(x):
    return isinstance(x, str) and bool(x) and not PurePosixPath(x).is_absolute() and ".." not in PurePosixPath(x).parts


def confined(root, path):
    """`path` (under the repository `root`), refused (CONFIG) when its real path leaves the repository's: a link to a
    file outside it would make a claim's evidence, or the harness the check runs, bytes no commit holds (Codex
    finding 583d6f508840 on #226)."""
    base = Path(root).resolve()
    if not Path(path).resolve().is_relative_to(base):
        raise Failed("CONFIG", f"{Path(path).relative_to(root) if Path(path).is_relative_to(root) else path} leads outside "
                               "the repository")
    return Path(path)


def sources(cfg):
    """The configuration's current sources: `source` is one path or a list of distinct paths."""
    return [cfg["source"]] if isinstance(cfg["source"], str) else list(cfg["source"])


def config(root):
    """The repository's `.warrant/claims.json` ({warrant, source, retired, witnesses, mutants}), checked: relative paths
    whose real paths stay in the repository; `source` one path or a non-empty list of distinct ones."""
    try:
        doc = json.loads((Path(root) / ".warrant" / "claims.json").read_text())
    except (OSError, ValueError) as e:
        raise Failed("CONFIG", f".warrant/claims.json: {type(e).__name__} {e}") from None
    srcs = doc.get("source") if isinstance(doc, dict) else None
    srcs = [srcs] if isinstance(srcs, str) else srcs
    cover = doc.get("coverage", ["MUST"]) if isinstance(doc, dict) else None
    ok = (isinstance(doc, dict) and set(doc) - {"coverage"} == {"warrant", "source", "retired", "witnesses", "mutants"}
          and doc["warrant"] == CONFIG
          and isinstance(cover, list) and cover and all(isinstance(k, str) and KEYWORD.match(k) for k in cover)
          and len(set(cover)) == len(cover)
          and isinstance(srcs, list) and srcs and all(_relative(x) for x in srcs) and len(set(srcs)) == len(srcs)
          and _relative(doc["mutants"]) and isinstance(doc["retired"], list)
          and all(_relative(x) and x not in srcs for x in doc["retired"])
          and isinstance(doc["witnesses"], list) and doc["witnesses"] and all(_relative(x) for x in doc["witnesses"]))
    if not ok:
        raise Failed("CONFIG", f".warrant/claims.json is a {CONFIG} document {{warrant, source, retired, witnesses, mutants, "
                               "coverage?}} of relative paths, coverage a non-empty list of distinct uppercase keywords")
    for k in (*srcs, doc["mutants"]):
        confined(root, Path(root) / k)
    return doc


def harness(root):
    out = subprocess.run([sys.executable, str(Path(root) / config(root)["mutants"]), "--list"], capture_output=True, text=True,
                         check=True)
    return json.loads(out.stdout)


def witness_files(root):
    """{test file name: path} of the files the configuration's witness patterns match: tests/x_test.py is x_test,
    integrations/P/test_plugin.py is P/test_plugin."""
    out = {}
    for pattern in config(root)["witnesses"]:
        for p in sorted(Path(root).glob(pattern)):
            confined(root, p)
            out[p.stem if p.parent.name == "tests" else f"{p.parent.name}/{p.stem}"] = p
    return out


def cases(root):
    """{test file name: {case ids}} printed by check(...) calls in the witness files."""
    return {name: set(CASE_LINE.findall(p.read_text())) for name, p in witness_files(root).items()}


def live(rep):
    """{lineage: leaf body} of the claim@1 lineages not retired (a forked one under its root's body)."""
    recs = rep["_recs"]
    return {L: recs[lin["leaf"] or L]["body"] for L, lin in rep["lineages"].items()
            if lin["schema"] == CLAIM and (recs[lin["leaf"]]["body"]["state"] if lin["leaf"] else None) != "retired"}


def unclaimed(text, sentences, keywords):
    """[(line, keyword, context)]: each whole-word occurrence of a keyword outside a heading line that lies, whole, in
    no occurrence of any of the claims' sentences (a claim ending inside `MUST`, or covering `MUST` of `MUST NOT`,
    does not cover it)."""
    spans = []
    for t in sentences:
        i = text.find(t) if t else -1
        while i >= 0:
            spans.append((i, i + len(t)))
            i = text.find(t, i + 1)
    # the words of a keyword may be wrapped or spaced as prose is (Codex finding cceaee70 on #259)
    word = "|".join(r"\s+".join(map(re.escape, k.split(" "))) for k in sorted(keywords, key=len, reverse=True))
    out = []
    for m in re.finditer(rf"(?<![A-Za-z0-9_])(?:{word})(?![A-Za-z0-9_])", text):
        start = text.rfind("\n", 0, m.start()) + 1
        if text.startswith("#", start):
            continue
        if not any(a <= m.start() and m.end() <= b for a, b in spans):     # the whole keyword (Codex finding on #259)
            end = text.find("\n", m.end())
            line = text[start:len(text) if end < 0 else end].strip()
            out.append((text.count("\n", 0, m.start()) + 1, " ".join(m.group(0).split()), line[:100]))
    return out


def store_problems(rep):
    out = []
    if not rep["canonical"]:
        out.append(("NOT_CANONICAL", "records.jsonl is not in canonical order: `python3 -m warrant fmt`"))
    out += [("REJECTED", f"{i[:12]} {w[:120]}") for i, w in rep["rejected"].items()]
    out += [(c, f"{str(i)[:12]} {d[:120]}") for c, i, d in rep["problems"]]
    return out          # a schema awaiting backers (schemas_pending) is a proposal, not a problem: no claim rests on it


def check(repo):
    cfg = config(repo.root)
    srcs = sources(cfg)
    rep = repo.report()
    out = store_problems(rep)
    spec = {src: (repo.root / src).read_text() for src in srcs}
    known, printed = harness(repo.root), cases(repo.root)
    ids = {}
    for L, b in sorted(live(rep).items()):
        lin = rep["lineages"][L]
        tag = f"{b.get('id')} ({L[:12]})"
        if lin["verdict"] == "FORK":
            out.append(("CLAIM_FORK", tag))
        if b["source"] not in spec:
            out.append(("V2_CLAIM_LIVE" if b["source"] in cfg["retired"] else "CLAIM_SOURCE", f"{tag} is of {b['source']}"))
            continue
        ids.setdefault(b["id"], []).append(L)
        if b["text"] not in spec.get(b["source"], ""):     # total: a mutant dropping the source check is seen, not a crash
            out.append(("CLAIM_TEXT_MISSING", f"{tag}: its sentence is not in {b['source']}"))
        out += backing_problems(tag, b, printed, known)
    out += [("CLAIM_ID_TWICE", f"{i} in {len(Ls)} lineages") for i, Ls in sorted(ids.items()) if len(Ls) > 1]
    if "coverage" in cfg:
        claimed = live(rep).values()
        for src in srcs:
            said = [b["text"] for b in claimed if b["source"] == src and isinstance(b.get("text"), str)]
            out += [("UNCLAIMED_KEYWORD", f"{src}:{n}: {kw} in «{line}» is in no live claim's sentence")
                    for n, kw, line in unclaimed(spec[src], said, cfg["coverage"])]
    return rep, out


def backing_problems(tag, b, printed, known):
    """What keeps claim body `b` from being backed: a witness case no test file prints, a mutant the harness does not
    list or that fails none of its witnesses, a `backed` claim with no witness or no mutant."""
    out = []
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
    return out


def witness_of(m, known):
    """The name a witness gives a mutant's test file: tests/x_test.py is x_test, integrations/P/test_plugin.py is
    P/test_plugin."""
    f = Path(known.get(m, ["", "tests/none"])[1])           # total: an unknown id names no file
    return f.stem if f.parts[0] == "tests" else f"{f.parent.name}/{f.stem}"


def test_path(name, root):
    return witness_files(root).get(name, Path(root) / "tests" / f"{name}.py")


def checked(rep):
    """{version: [commits]} of the claims checker's signed acceptances."""
    out = {}
    for i, r in sorted(rep["_recs"].items()):
        if r["kind"] == "attest" and r["actor"] == CHECKER and rep["_basis"].get(i) == "SIGNED" and r["body"].get("verdict") == "accept":
            out.setdefault(r["body"]["target"], []).append(r["body"].get("commit"))
    return out


def acceptances(rep):
    """{version: [(commit, files, closure)]} of the claims checker's signed acceptances, `files` as each names them
    (None in one signed before they were named), `closure` the rule they were named by: CLOSURE when they are the
    import closure of what ran (warrant.imports), None in one signed before (its files are the test and mutated
    files only, so a shared module it ran is not among them)."""
    out = {}
    for i, r in sorted(rep["_recs"].items()):
        if r["kind"] == "attest" and r["actor"] == CHECKER and rep["_basis"].get(i) == "SIGNED" and r["body"].get("verdict") == "accept":
            out.setdefault(r["body"]["target"], []).append((r["body"].get("commit"), r["body"].get("files"),
                                                            r["body"].get("closure")))
    return out


def files_of(b, root, known, tree, memo=None):
    """What an acceptance of claim body `b` runs on, {path: blob} of `tree`: each witness's test file, each mutant's
    mutated file and test file, as `known` (this checkout's harness) and this checkout's witness patterns place them,
    and every file each of those loads (warrant.imports: the import closure, searched as the file runs: its own
    directory, then the checkout), with every link of a symlink chain and the file it ends at (Codex finding
    f4729a41b788): a link's blob is only its target's name. A shared module or test helper a witness imports is named
    (Codex counterexample on G14, 2026-11-13: a claim of engine.py named engine.py and its test, not the records.py,
    jcs.py, store.py and tests/world.py its witness runs). None when any of them cannot be named: a file of the closure
    that does not parse, a path reaching its file some other way (a linked directory, a link leaving the tree) or not
    in `tree`. A partial list is never signed (Codex finding f328c7477354): the checker accepts nothing on what it
    cannot name. `memo` keeps one closure per file across the claims of one run."""
    memo = {} if memo is None else memo
    tests, starts = witness_files(root), set()
    for w in b["witnesses"]:
        name = w.split(":")[0]
        if name in tests:
            starts.add(tests[name].relative_to(root).as_posix())
    for m in b["mutants"]:
        starts.update(known.get(m, [])[:2])
    paths = set()
    for f in sorted({os.path.normpath(p) for p in starts}):
        if f not in memo:
            try:
                memo[f] = IM.closure(root, f, ("", os.path.dirname(f))) if f.endswith(".py") else {f}
            except IM.Unreadable:
                memo[f] = None
        if memo[f] is None:
            return None
        paths |= {f} | {p for p in memo[f] if not p.endswith("/")}      # a directory without __init__ has no bytes
    chains = [_link_chain(root, p) for p in sorted(paths)]
    if None in chains or any(p not in tree for chain in chains for p in chain):
        return None
    return {p: tree[p] for chain in chains for p in chain}


def _link_chain(root, path):
    """[`path`, each link it passes through, the file it ends at], all repository paths; None for a cycle or a link
    leaving the tree."""
    base, chain = Path(root).resolve(), [path]
    while (base / chain[-1]).is_symlink():
        step = os.path.normpath(os.path.join(os.path.dirname(chain[-1]), os.readlink(base / chain[-1])))
        if step in chain or os.path.isabs(step) or step.startswith(".."):
            return None
        chain.append(step)
    return chain


def at_tree(root, commits, here):
    """Whether one of `commits` has the code `here` (a tree outside .warrant/); a commit not in this clone has not."""
    for x in commits:
        try:
            if code_tree(root, x) == here:
                return True
        except (subprocess.CalledProcessError, TypeError):
            continue
    return False


def view(rep, root):
    from . import drift
    drift.gate(rep, root)          # a claim whose acceptances name other bytes than HEAD's reads STALE (G14)
    recs, cfg = rep["_recs"], config(root)
    done, here = checked(rep), code_tree(root, "HEAD")
    srcs = sources(cfg)
    lines = [f"# Claims of {', '.join(srcs)}", "", f"Generated from `.warrant/records.jsonl` (snapshot `{rep['snapshot'][:12]}`, "
             f"assessment `{rep['assessment'][:12]}`); a build artifact, never committed.", ""]
    rows = sorted(((b["section"], b["id"], L, b) for L, b in live(rep).items() if b["source"] in srcs),
                  key=lambda r: (srcs.index(r[3]["source"]), [int(x) if x.isdigit() else x for x in r[0].split(".")], r[1]))
    for section, cid, L, b in rows:
        where = f"{b['source']} " if len(srcs) > 1 else ""
        lin = rep["lineages"][L]
        g = rep["versions"].get(lin["leaf"] or L, {})
        state = f"{lin['state'] or 'none effective'}, leaf {b['state']} {g.get('guard')}"
        if done.get(lin["leaf"]):
            xs = done[lin["leaf"]]
            state += ", checked at this tree" if at_tree(root, xs, here) else f", checked at {', '.join(str(x)[:12] for x in xs)}, not this tree"
        lines += [f"- **{cid}** ({where}§{section}; {state}; {lin['reliance']}; leaf `{lin['leaf'] or L}`) {b['text']}",
                  f"  witnesses: {', '.join(b['witnesses']) or 'none'}; mutants: {', '.join(b['mutants']) or 'none'}"
                  + (f"; why unbacked: {b['reason']}" if b.get("reason") else "")]
    for old in cfg["retired"]:
        n = sum(1 for L, lin in rep["lineages"].items() if lin["schema"] == CLAIM and recs[L]["body"]["source"] == old)
        lines += ["", f"Claims of the retired source {old} (history): {n} lineages."]
    return "\n".join(lines) + "\n"


def schema_guard(rep, state):
    return rep["_recs"][rep["schemas"][CLAIM]]["body"]["states"][state]


def file_claims(repo, actor, key, doc):
    """File each claim of `doc` ([{id, section, text, witnesses, mutants, source?, state?, reason?}]) as a new lineage,
    or a new version of the live lineage with its id when anything differs; unchanged ones are skipped. `source` is one
    of the configuration's, by default its first."""
    srcs = sources(config(repo.root))
    rep = repo.report()
    by_id = {b["id"]: L for L, b in live(rep).items() if b["source"] in srcs}
    recs = []
    for c in doc:
        state, source = c.get("state", "backed"), c.get("source", srcs[0])
        if source not in srcs:
            raise Failed("CLAIM_SOURCE", f"{c['id']} names {source}, not a source of .warrant/claims.json")
        body = {"state": state, "id": c["id"], "source": source, "section": c["section"], "text": c["text"],
                "witnesses": c["witnesses"], "mutants": c["mutants"], **({"reason": c["reason"]} if c.get("reason") else {})}
        L = by_id.get(c["id"])
        leaf = rep["lineages"][L]["leaf"] if L else None
        if leaf and rep["_recs"][leaf]["body"] == body:
            continue
        recs.append(R.record("entity", actor, 0, body, CLAIM, lineage=leaf, guard=schema_guard(rep, state)))
    return repo.file(actor, key, recs)


def retire_v2(repo, actor, key):
    cfg = config(repo.root)
    rep = repo.report()
    recs = []
    for L, b in sorted(live(rep).items()):
        lin = rep["lineages"][L]
        if b["source"] not in cfg["retired"] or lin["leaf"] is None or rep["_recs"][L]["actor"] != actor:
            continue
        body = dict(b, state="retired", reason=f"a claim of {b['source']}, a retired source: "
                    f"{', '.join(sources(cfg))}'s claims are the current ones")
        for k in ("established", "residual", "opened", "subject", "because", "counter", "challenge", "evidence"):
            body.pop(k, None)
        recs.append(R.record("entity", actor, 0, body, CLAIM, lineage=lin["leaf"], refs=R.body_refs({}, body)))
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
        subprocess.run([sys.executable, str(Path(root) / config(root)["mutants"]), *sorted(mutants), "--matrix", str(out)], cwd=root,
                       capture_output=True, text=True, timeout=7200)
        killed = {r["id"]: r for r in json.loads(out.read_text())["rows"]} if out.is_file() else {}
    return ran, killed


def held(b, ran, killed):
    return all(w.split(":")[1] in ran.get(w.split(":")[0], set()) for w in b["witnesses"]) and all(
        killed.get(m, {}).get("outcome") == "KILLED" for m in b["mutants"])


def replay(repo, key):
    """The claims checker at a clean commit: each live `backed` claim whose leaf waits, or none of whose acceptances
    by the checker names the bytes this commit holds for it (files_of: its tests, its mutated files and their import
    closure), is accepted when every witness case passes and every mutant it cites is killed on one of its cases, in
    this tree. A claim whose files did not change is not run again: its acceptance at another commit speaks of these
    bytes too. Each acceptance names the commit, its tree, the checker's code, its environment and its files."""
    root = repo.root
    me = identity(root)
    trust, _, _ = repo.config()
    if key.public not in trust["keys"].get(CHECKER, []):
        raise Failed("SIGNER", f"the seed's key is not one .warrant/v3.json binds to {CHECKER}")
    commit, tree = tree_id(root)
    rep, problems = check(repo)
    if problems:
        raise Failed("CHECK", f"{len(problems)} problem(s): the checker accepts nothing over a failing check")
    known, listed, memo = harness(root), blobs(root, commit), {}
    done = acceptances(rep)
    now = {L: files_of(b, root, known, listed, memo) for L, b in live(rep).items() if b["state"] == "backed"}

    def fresh(L):
        leaf = rep["lineages"][L]["leaf"]
        return (rep["versions"][leaf]["guard"] != "PENDING" and now[L] is not None
                and any(c == CLOSURE and files == now[L] for _, files, c in done.get(leaf, [])))
    todo = {L: b for L, b in live(rep).items() if L in now and not fresh(L)}
    ran, killed = run_checks(root, [w for b in todo.values() for w in b["witnesses"]], {m for b in todo.values() for m in b["mutants"]})
    recs = []
    for L, b in sorted(todo.items()):
        files = now[L]
        ok = held(b, ran, killed) and files is not None
        if ok:
            leaf = rep["lineages"][L]["leaf"]
            recs.append(R.record("attest", CHECKER, 0, {"target": leaf, "verdict": "accept", "commit": commit, "tree": tree, **me,
                                                        "witnesses": b["witnesses"], "mutants": b["mutants"],
                                                        "files": files, "closure": CLOSURE}, refs=[leaf]))
        print(f"{'ACCEPT' if ok else 'HELD  '} {b['id']} {L[:12]}")
    print(f"claims checker: {len(todo)} of {len(now)} backed claims run, {len(now) - len(todo)} fresh at this commit")
    return repo.file(CHECKER, key, recs)


def verify(repo, base, done=frozenset(), verified=None):
    """Re-execute every acceptance the claims checker signed since commit `base`, in a temporary worktree of the
    commit it names: its `code` must be the checker's code at that commit (CODE_DIFFERS), its witnesses and mutants
    those of the version it accepts, the claims check must pass there and that version be the leaf of a live
    `backed` claim there, as replay requires before it signs (CLAIM_PREFLIGHT), and every witness must pass and
    every mutant be killed there again (CLAIM_REPLAY_DIFFERS), and the `files` it names, when it names them, be what
    that commit's checkout lists for the claim (warrant.drift reads them). Acceptances by a person (codex) are trust
    decisions, not re-executed. An acceptance in `done` (ids a run on this branch re-executed and found holding: its
    result at the commit it names cannot change) is checked but not run again; `verified`, when given, receives every
    acceptance that held, so a later run of the same pull request after its base moved re-executes only what is new."""
    old = _records_at(repo.root, base)
    rep = repo.report()
    recs, bad, by_commit = rep["_recs"], [], {}
    for i, r in sorted(recs.items()):
        if r["kind"] != "attest" or r["actor"] != CHECKER or i in old or rep["_basis"].get(i) != "SIGNED":
            continue
        b, v = r["body"], recs.get(r["body"].get("target"))
        why = checker_problem(b, repo.root)
        if why is None and not (v and v["kind"] == "entity" and v["schema"] == CLAIM
                                and (b.get("witnesses"), b.get("mutants")) == (v["body"]["witnesses"], v["body"]["mutants"])):
            why = "lists other witnesses or mutants than the claim version it accepts"
        if why:
            bad.append(f"{i[:12]}: {why}")
        else:
            by_commit.setdefault(b["commit"], []).append((i, b["target"], v["body"]))
    held = [i for rows in by_commit.values() for i, _, _ in rows if i in done]
    by_commit = {x: kept for x, rows in by_commit.items() if (kept := [row for row in rows if row[0] not in done])}
    pins = {i: recs[i]["body"].get("files") for rows in by_commit.values() for i, _, _ in rows}
    for x, rows in sorted(by_commit.items()):
        bad += _reexecuted(repo, x, rows, pins)
    if bad:
        raise Failed("CLAIM_REPLAY_DIFFERS", "; ".join(bad))
    if verified is not None:
        verified.extend(held + [i for rows in by_commit.values() for i, _, _ in rows])
    return sum(len(rows) for rows in by_commit.values())


def _records_at(root, commit):
    """The record ids of the store at `commit`, from Git objects. Read here, not through the gate's reader: claims (and
    drift, which imports it) do not depend on the gate, the module that changes most (the import closure of every
    claim whose witness reads drift would hold it)."""
    x = P.git(root, "rev-parse", "--verify", "--end-of-options", f"{commit}^{{commit}}")
    try:
        raw = P.git(root, "show", f"{x}:.warrant/records.jsonl", raw=True)
    except subprocess.CalledProcessError:
        raw = b""
    return set(Snapshot([ln + b"\n" for ln in raw.split(b"\n") if ln], {}).lines)


def _reexecuted(repo, x, rows, pins):
    """What keeps the acceptances `rows` ([(attest, version, claim body)]) at commit x from holding when re-executed
    in a temporary worktree of it; `pins` is the `files` each names."""
    wt = Path(repo.root) / "build" / f"verify-claims-{os.getpid()}-{x[:12]}"      # the checkout's own scratch, ignored
    git(repo.root, "worktree", "add", "--detach", "--quiet", str(wt), x)
    try:
        at_x, problems_x = check(Repo(wt))
        if problems_x:
            return [f"{i[:12]}: CLAIM_PREFLIGHT the claims check at {x[:12]} has {len(problems_x)} problem(s), the first "
                    f"{' '.join(problems_x[0])[:100]}" for i, _, _ in rows]
        srcs = sources(config(wt))
        leaves = {at_x["lineages"][L]["leaf"] for L, b in live(at_x).items() if b["source"] in srcs and b["state"] == "backed"}
        off = [(i, t, b) for i, t, b in rows if t not in leaves]
        bad = [f"{i[:12]}: CLAIM_PREFLIGHT {b['id']} {t[:12]} is not the leaf of a live backed claim at {x[:12]}" for i, t, b in off]
        rows = [row for row in rows if row not in off]
        known, tree = harness(wt), blobs(wt, x)
        bad += [f"{i[:12]}: CLAIM_REPLAY_DIFFERS {b['id']} names other files than {x[:12]} lists for it" for i, _, b in rows
                if pins.get(i) is not None and pins[i] != files_of(b, wt, known, tree)]
        ran, killed = run_checks(wt, [w for _, _, b in rows for w in b["witnesses"]], {m for _, _, b in rows for m in b["mutants"]})
    finally:
        git(repo.root, "worktree", "remove", "--force", str(wt))
    return bad + [f"{i[:12]}: CLAIM_REPLAY_DIFFERS {b['id']} does not hold at {x[:12]}" for i, _, b in rows if not held(b, ran, killed)]


def closures(root, rep):
    """[(witness file, files in its import closure, live backed claims it witnesses)], the widest first: what one
    change to a module stales (a claim's acceptance names the closure of each file that runs, files_of)."""
    tests, by = witness_files(root), {}
    for b in live(rep).values():
        if b["state"] == "backed":
            for name in {w.split(":")[0] for w in b["witnesses"]}:
                by[name] = by.get(name, 0) + 1
    out = []
    for name, n in by.items():
        if name in tests:
            f = tests[name].relative_to(root).as_posix()
            try:
                size = len(IM.closure(root, f, ("", os.path.dirname(f))))
            except IM.Unreadable:
                size = None
            out.append((f, size, n))
    return sorted(out, key=lambda r: (-(r[1] or 0) * r[2], r[0]))


def _closures_cmd(repo, root):
    for f, size, n in closures(root, repo.report()):
        print(f"{f}: {size if size is not None else 'unreadable'} file(s) in its import closure, {n} backed claim(s)")
    return 0


def _parser():
    ap = argparse.ArgumentParser(prog="warrant.claims")
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
    sub.add_parser("closures")
    r = sub.add_parser("replay")
    r.add_argument("--key", required=True)
    vf = sub.add_parser("verify")
    vf.add_argument("--base", required=True)
    vf.add_argument("--done", help="a file of the checkout (build/...) of acceptance ids already re-executed and held on "
                                   "this branch; updated on success")
    return ap


def _done_file(path, root, code):
    """The acceptance ids FILE says held under this checker `code`, or a refusal. What is established: FILE is a file
    of the checkout (inside) that Git does not track (Codex on #367: a committed done file skipped the replay of the
    acceptances it named), and an entry counts only for the checker code that wrote it. It is written by an earlier run
    of the same branch, so it saves time, not trust against the branch's author: CI restores it for branches of this
    repository only and reads it before any code of the branch's findings runs."""
    if path.is_symlink():
        raise Failed("PATH", f"{path}: the done file is a file, not a link")
    try:
        P.git(root, "ls-files", "--error-unmatch", "--", os.path.relpath(path, Path(root).resolve()))
        tracked = True
    except subprocess.CalledProcessError:
        tracked = False
    if tracked:
        raise Failed("PATH", f"{path}: the done file is the runner's own, never a file the tree holds")
    rows = [ln.split() for ln in path.read_text().splitlines()] if path.is_file() else []
    return frozenset(r[0] for r in rows if len(r) == 2 and r[1] == code)


def _verify_cmd(repo, a, root):
    """`verify --base M [--done FILE]`: FILE is a file of the checkout (inside), as every path a tool reads or writes,
    that Git does not track; each line `<acceptance id> <checker code>`."""
    path = inside(a.done, root) if a.done else None
    code = identity(root)["code"] if path else None
    done = _done_file(path, root, code) if path else frozenset()
    held = []
    n = verify(repo, a.base, done, held)
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"{i} {code}\n" for i in sorted(set(held) | done)))
    print(f"claims checker acceptances new since {a.base[:12]}: {n} re-executed, {len(set(held) & done)} held before, all held")
    return 0


def _check_cmd(repo, root):
    rep, out = check(repo)
    for c, d in out:
        print(f"{c} {d}")
    srcs = sources(config(root))
    n = len([1 for b in live(rep).values() if b["source"] in srcs])
    print(f"claims: {n} live of {', '.join(srcs)}; {len(out)} problem(s)")
    return 1 if out else 0


def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    a = _parser().parse_args(argv)
    repo = Repo(root)
    if a.cmd == "closures":
        return _closures_cmd(repo, root)
    if a.cmd == "identity":
        dump({"actor": CHECKER, **identity(root)})
        return 0
    if a.cmd == "verify":
        return _verify_cmd(repo, a, root)
    if a.cmd == "check":
        return _check_cmd(repo, root)
    if a.cmd == "view":
        emit(view(repo.report(), repo.root), a.out, root)
        return 0
    key = load_key(a.key, root)
    if a.cmd == "replay":
        dump({"filed": replay(repo, key)})
    elif a.cmd == "file":
        dump({"filed": file_claims(repo, a.actor, key, json.loads(inside(a.src, root).read_text()))})
    else:
        dump({"filed": retire_v2(repo, a.actor, key)})
    return 0


def entry():
    """The console script `warrant-claims`."""
    return main(run)


if __name__ == "__main__":
    sys.exit(main(run))
