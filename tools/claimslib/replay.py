"""The replay checker (G4): a rule that accepts a BACKED claim's closure by replaying it.

The checker is an actor whose id names the bytes of this file: `checker sha256:<H>`, where H is
SHA-256 over canon({"checker": "warrant-claims/replay@1", "files": {"tools/claimslib/replay.py":
sha256(bytes)}}), the form of the Sigma provider identity (SPEC §7). A change of one byte here is
another actor, with another key to pin. The checker imports nothing else of the claims tool:
whatever it accepts, it reads from the signed records itself.

For each claim transition it is asked to accept, at HEAD of a clean checkout:

  1. The transition is a BACKED claim: ATTESTED, with one discharge item on one claim blob
     (warrant-claims/claim@1, normative, with witnesses and mutants). The duty has an attest
     condition and names this checker in accept_by.
  2. No transition supersedes it, no challenge targets it, and this checker has not accepted it
     already.
  3. The exact tree of HEAD is extracted (`git archive`). Every cited witness test file runs
     once on it, unmutated, and every cited witness case PASSES.
  4. Every cited mutant is KILLED. Its edits are applied to a copy of the packages, its own
     test file runs, and a case of that file **cited by the claim** fails. A failure of a case
     the claim does not cite is not a kill for this claim.

Only then does it file an `accept` of item 0, with that item's evidence and `support` = [the
report blob, warrant-claims/replay-report@1]. The acceptance says exactly this: these witness
cases passed and these mutants were killed by them, at this commit and tree, under this
checker. It says nothing about whether the sentence is true, and it is not a review.

Custody: whoever holds the checker's seed can sign as the checker without running it.
`claims.py check` reads every acceptance's report against the claim. For acceptances new since
the base, it also reads the reported commit: its tree and the checker's bytes there.
`claims.py replay --verify` re-runs the reported commit's own replay.py and refuses a report it
does not reproduce.
"""
import concurrent.futures
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

from warrant import jcs as C
from warrant import records as R

CHECKER = "warrant-claims/replay@1"
REPORT = "warrant-claims/replay-report@1"
REPORT_FIELDS = ("replay", "checker", "commit", "tree", "claim", "transition", "duty", "witnesses", "mutants")
SELF = "tools/claimslib/replay.py"           # the path the identity names
PREFIX = "checker sha256:"
CLAIM = "warrant-claims/claim@1"
# A mutant id's prefix names its harness and the package its file is relative to.
HARNESSES = {"M": ("mutants.py", "warrant"), "A": ("agent_mutants.py", "warrant_agent")}
TEST = re.compile(r"[a-z][a-z0-9_]*_test")
MUTANT = re.compile(r"[MA][0-9]+")
PACKAGES = ("warrant", "warrant_agent", "tools")


class Refusal(Exception):
    """Nothing is accepted for this claim; `code` names why."""

    def __init__(self, code, why):
        super().__init__(why)
        self.code = code


def identity(data):
    """H for the bytes `data` of this file."""
    files = {SELF: hashlib.sha256(data).hexdigest()}
    return hashlib.sha256(C.canon({"checker": CHECKER, "files": files})).hexdigest()


def actor(data=None):
    """The actor id of the checker whose code is `data` (default: this file as it is on disk)."""
    return PREFIX + identity(Path(__file__).read_bytes() if data is None else data)


def claim_of(recs, snap, tid, me):
    """The claim blob of transition `tid` if checker `me` may accept its closure; Refusal if not."""
    t = recs.get(tid)
    if t is None or t["type"] != "transition":
        raise Refusal("REPLAY_NOT_A_CLAIM", f"{tid[:12]} is not an authentic transition")
    b = t["body"]
    closes = b["closes"]
    if b["basis"] != "ATTESTED" or len(closes) != 1 or closes[0]["act"] != "discharge" or len(closes[0]["evidence"]) != 1:
        raise Refusal("REPLAY_NOT_A_CLAIM", f"{tid[:12]} does not discharge one duty on one blob")
    doc = snap.json_blob(closes[0]["evidence"][0])
    if not (isinstance(doc, dict) and doc.get("schema") == CLAIM and doc.get("kind") == "normative"
            and doc.get("duty") == closes[0]["duty"] and doc.get("witnesses") and doc.get("mutants")):
        raise Refusal("REPLAY_NOT_A_CLAIM", f"{tid[:12]} is not a BACKED claim (normative, witnesses and mutants)")
    bad = [w for w in doc["witnesses"] if not (isinstance(w, str) and TEST.fullmatch(w.partition(":")[0]) and w.partition(":")[2])]
    bad += [m for m in doc["mutants"] if not (isinstance(m, str) and MUTANT.fullmatch(m))]
    if bad:
        raise Refusal("REPLAY_NOT_A_CLAIM", f"{doc['id']}: {bad[:3]} are not <test>:<case> or mutant ids")
    d = recs.get(doc["duty"])
    if d is None or d["type"] != "duty" or d["body"]["condition"] != {"attest": {}} or me not in d["body"]["accept_by"]:
        raise Refusal("REPLAY_NOT_ACCEPTOR", f"{doc['id']}: its duty does not name {me} in accept_by")
    if any(r["type"] == "transition" and tid in r["body"]["supersedes"] for r in recs.values()):
        raise Refusal("REPLAY_SUPERSEDED", f"{doc['id']}: {tid[:12]} is superseded; only a claim's current "
                      "transition is replayed")
    if any(r["type"] == "challenge" and r["body"]["target"] == tid for r in recs.values()):
        raise Refusal("REPLAY_CHALLENGED", f"{doc['id']}: a challenge targets {tid[:12]}; a challenged claim is "
                      "left to its author and its acceptors")
    if any(r["type"] == "accept" and r["actor"] == me and r["body"]["transition"] == tid for r in recs.values()):
        raise Refusal("REPLAY_ACCEPTED", f"{doc['id']}: {me[:24]}… accepted {tid[:12]} already")
    return doc


def _run(tree, impl, test, out):
    """{case: PASS|FAIL} of tests/<test>.py of `tree` against the packages in `impl`, or None
    when it wrote no results. `out` is a directory of this run's own."""
    res = out / f"results-{test}.json"
    env = dict(os.environ, WARRANT_IMPL=str(impl), WARRANT_RESULTS=str(res), PYTHONDONTWRITEBYTECODE="1")
    subprocess.run([sys.executable, str(tree / "tests" / f"{test}.py")], cwd=tree / "tests", env=env,
                   capture_output=True, timeout=1800, check=False)
    return json.loads(res.read_text()) if res.is_file() else None


def _mutants(tree):
    """{id: (file relative to the repository, edits, test)} of the harnesses in `tree`."""
    out = {}
    for prefix, (name, pkg) in HARNESSES.items():
        path = tree / "tests" / name
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location(f"replay_{path.stem}_{time.monotonic_ns()}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for m in mod.MUTANTS:
            if m[0].startswith(prefix):
                out.setdefault(m[0], (os.path.normpath(f"{pkg}/{m[1]}"), list(m[3]), m[4]))
    return out


def _mutant(tree, defs, mid, out):
    """(outcome, {case: result} or None) of mutant `mid` applied to a copy of `tree`'s packages."""
    if mid not in defs:
        return "UNKNOWN_MUTANT", None
    path, edits, test = defs[mid]
    work = Path(tempfile.mkdtemp(prefix=f"replay-{mid}-", dir=out))
    try:
        for pkg in PACKAGES:
            if (tree / pkg).is_dir():
                shutil.copytree(tree / pkg, work / pkg, ignore=shutil.ignore_patterns("__pycache__"))
        f = (work / path).resolve()
        if work.resolve() not in f.parents or not f.is_file():
            return "BAD_MUTANT", None
        src = f.read_text()
        for old, new in edits:
            if src.count(old) != 1:
                return "BAD_MUTANT", None
            src = src.replace(old, new)
        f.write_text(src)
        runs = _run(tree, work, test, work)
        return ("RAN" if runs is not None else "CRASH"), runs
    finally:
        shutil.rmtree(work, ignore_errors=True)


def replay(tree, claims, jobs=4):
    """{transition: (witnesses, mutants)} for `claims` ({transition: claim blob}) at the
    extracted tree `tree`: witnesses {case: PASS | FAIL | ABSENT}; mutants {id: {"outcome":
    KILLED | SURVIVED | CRASH | BAD_MUTANT | UNKNOWN_MUTANT, "fails": [cited cases that fail]}}.
    Each test file runs once unmutated and each mutant once, whatever claims cite them."""
    tree = Path(tree)
    out = Path(tempfile.mkdtemp(prefix="replay-runs-"))
    try:
        defs = _mutants(tree)
        tests = sorted({w.partition(":")[0] for d in claims.values() for w in d["witnesses"]})
        mids = sorted({m for d in claims.values() for m in d["mutants"]})
        with concurrent.futures.ThreadPoolExecutor(max(1, jobs)) as ex:
            plain = dict(zip(tests, ex.map(lambda t: _run(tree, tree, t, out), tests)))
            mutated = dict(zip(mids, ex.map(lambda m: _mutant(tree, defs, m, out), mids)))
        result = {}
        for tid, d in claims.items():
            wit = {}
            for w in d["witnesses"]:
                test, _, case = w.partition(":")
                wit[w] = (plain.get(test) or {}).get(case, "ABSENT")
            mut = {}
            for mid in d["mutants"]:
                outcome, runs = mutated[mid]
                test = defs[mid][2] if mid in defs else None
                fails = sorted(w for w in d["witnesses"] if w.partition(":")[0] == test
                               and (runs or {}).get(w.partition(":")[2]) == "FAIL")
                if outcome == "RAN":
                    outcome = "KILLED" if fails else "SURVIVED"
                mut[mid] = {"outcome": outcome, "fails": fails}
            result[tid] = (wit, mut)
        return result
    finally:
        shutil.rmtree(out, ignore_errors=True)


def _git(root, *args, data=False):
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True).stdout
    return out if data else out.decode().strip()


def extract(root, commit, into):
    """Extract `commit` of the repository at `root` into the empty directory `into`."""
    with tarfile.open(fileobj=io.BytesIO(_git(root, "archive", "--format=tar", commit, data=True))) as t:
        t.extractall(into, filter="data")


def run(root, store, trust, key, tids, jobs=4):
    """Replay the claims of transitions `tids` at HEAD of the clean checkout `root` and accept
    each one whose witnesses all pass and whose mutants are all killed. `store` is the
    repository's Store, `trust` the trust its records are read under, and `key` the checker's
    key: it must be bound to this file's actor id. Returns ([(transition, accept id)],
    [(transition, Refusal)])."""
    me = actor()
    if trust.keys.get(key.id, (None,))[0] != me:
        raise Refusal("REPLAY_KEY", f"key {key.id[:12]} is not bound to {me}: this code is that actor, "
                      "and another byte of it would be another actor")
    if _git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise Refusal("REPLAY_DIRTY", "the working tree differs from HEAD: a replay is of a commit's exact tree")
    commit, tree = _git(root, "rev-parse", "HEAD"), _git(root, "rev-parse", "HEAD^{tree}")
    from warrant.store import Snapshot
    snap = Snapshot.read(store.root)
    recs, _ = snap.authentic(trust)
    claims, refused = {}, []
    for tid in tids:
        try:
            claims[tid] = claim_of(recs, snap, tid, me)
        except Refusal as e:
            refused.append((tid, e))
    if not claims:
        return [], refused
    work = Path(tempfile.mkdtemp(prefix="replay-tree-"))
    try:
        extract(root, commit, work)
        results = replay(work, claims, jobs)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    filed = []
    for tid, d in claims.items():
        wit, mut = results[tid]
        failed = [w for w, v in wit.items() if v != "PASS"]
        survived = [m for m, v in mut.items() if v["outcome"] != "KILLED"]
        if failed or survived:
            code = "REPLAY_WITNESS_FAILS" if failed else "REPLAY_MUTANT_SURVIVES"
            refused.append((tid, Refusal(code, f"{d['id']}: witnesses not passing {failed}; mutants not killed by a "
                                               f"cited case {[(m, mut[m]['outcome']) for m in survived]}")))
            continue
        report = {"replay": REPORT, "checker": me[len(PREFIX):], "commit": commit, "tree": tree, "claim": d["id"],
                  "transition": tid, "duty": d["duty"], "witnesses": wit, "mutants": mut}
        h = store.put_json(report)
        item = recs[tid]["body"]["closes"][0]
        at = max([int(time.time())] + [r["at"] for r in recs.values()])
        filed.append((tid, store.append("accept", me, at, R.accept(tid, 0, item["evidence"], [h]), key, trust)))
    return filed, refused
