#!/usr/bin/env python3
"""`warrant verify PACKAGE` (warrant/verify.py, docs/VERIFY.md): a receiver with no store asks whether it may rely on
what it was handed. Each case builds a package with the package's own writer (the agent's `handoff export`), runs the
command in this process and reads its exit status and its answer. Every run is kept, and at the end the one-file
verifier (warrant_verify.py) repeats each of them twice, with the `cryptography` library and without it, and must
give the same bytes and the same exit status.

    python3 tests/verify_test.py
"""
import base64
import contextlib
import hashlib
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

from world import KEYS, ROLES, ROOT, Repo, check, finish, git

from warrant import engine as E
from warrant import jcs as C
from warrant import keys as K
from warrant import merkle as M
from warrant import pins as P
from warrant import repo as RP
from warrant import records as R
from warrant import shapes as S
from warrant import snapshot as SN
from warrant import verify as V
from warrant_agent import api
from warrant_agent.config import Config

sys.path.insert(0, str(ROOT / "tools"))
import build_verify as BUILD            # noqa: E402
import verify_single as SINGLE_SOURCE   # noqa: E402

SINGLE = ROOT / "warrant_verify.py"
TMP = Path(tempfile.mkdtemp(prefix="warrant-verify-"))
RUNS = []           # [argv, exit status, standard output, environment] of every run the one-file verifier repeats
Receiver = namedtuple("Receiver", "trust profile")
ACCEPT = {"verdict": "accept"}
COMPLETENESS = ("completeness: the package holds what its sender chose to include: a challenge or a later version it "
                "left out cannot be seen here")
SENDERS_ROOTS = "reliance: the roots answered are the ones the package names; --require names the ones you ask about"
TOP = {"warrant", "rely", "refused", "package", "receiver", "asked", "checkout", "integrity", "authenticity",
       "completeness", "execution", "roots", "established", "not_established"}
ROOT_MEMBERS = {"kind", "schema", "actor", "at", "basis", "rejected", "lineage", "guard", "accepted", "challenges",
                "pins", "unavailable", "why_not", "rely"}


def export(repo, *targets):
    cfg = Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {"repo": str(repo.root)}}})
    return api.call(cfg, "handoff", {"workspace": "w", "op": "export", "targets": list(targets)}).get("ok", {})


def put(name, data):
    """A file of this run, by name, in a directory of its own."""
    d = Path(tempfile.mkdtemp(dir=TMP))
    (d / name).write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode())
    return str(d / name)


def run(argv, env=None, keep=True, patch=None):
    """(exit status, answer) of `warrant verify ARGV` in this process. `patch`: (object, name, value) set for the run."""
    out = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    old = getattr(patch[0], patch[1]) if patch else None
    if patch:
        setattr(patch[0], patch[1], patch[2])
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = V.main(list(argv))
            except SystemExit as e:
                code = e.code
    finally:
        if patch:
            setattr(patch[0], patch[1], old)
    out.flush()
    text = out.buffer.getvalue()
    if keep:
        RUNS.append([list(argv), code, text, env or {}])
    try:
        return code, json.loads(text) if text else {}
    except ValueError:
        return code, {}


def ask(pkg, receiver, *more, **how):
    return run([put("package.json", pkg), "--trust", put("trust.json", receiver.trust), "--profile",
                put("profile.json", receiver.profile), *more], **how)


def root(ans, i):
    return ans.get("roots", {}).get(i, {})


def base(roles=None):
    """A store with one obligation closed and accepted, resting on one evidence blob."""
    src = Repo(roles=roles)
    h = src.blob(b"evidence bytes")
    o = src.entity("alice", "obligation@1", {"state": "open", "statement": "task", "serves": []})
    d = src.entity("alice", "obligation@1", {"state": "done", "statement": "task", "serves": [], "evidence": [h]}, lineage=o)
    a = src.attest("bob", d)
    return src, h, o, d, a


def with_line(pkg, rid, change):
    """The package with the line of record `rid` changed by `change(envelope)`."""
    lines = []
    for x in pkg["lines"]:
        env = json.loads(x)
        if R.rid(env["record"]) == rid:
            change(env)
            x = C.canon(env).decode()
        lines.append(x)
    return dict(pkg, lines=lines)


def flip(env):
    sig = env["sig"]["ed25519"]
    env["sig"]["ed25519"] = ("1" if sig[0] == "0" else "0") + sig[1:]


def waits(n=1):
    return f"{n} attest(s) by roadmap/acceptor matching {{\"verdict\":\"accept\"}}"


# ---------------------------------------------------------------- the right to rely

def reliance_cases():
    src, h, o, d, a = base()
    exp = export(src, d)
    pkg = exp.get("package", {})
    code, ans = ask(pkg, src)
    r = root(ans, d)
    size = sum(len(x) + 1 for x in pkg["lines"]) + len(b"evidence bytes")
    check("U01", code == 0 and ans.get("rely") is True and ans.get("refused") is None and r.get("rely") is True
          and r.get("why_not") == [] and ans.get("asked") == {"by": "package", "roots": [d]} and ans.get("package") == exp.get("digest")
          and r.get("lineage") == {"root": o, "state": "done", "reliance": "ELIGIBLE", "verdict": "OK", "leaf": d, "effective": d, "forks": []}
          and r.get("guard", {}).get("guard") == "MET" and r.get("accepted") == [{"attest": a, "actor": "bob", "roles": ["roadmap/acceptor"]}]
          and ans.get("integrity") == {"records": 8, "blobs": 1, "bytes": size} and ans.get("checkout") is None
          and ans.get("established") == [
              f"integrity: 8 records and 1 blob, each named by the hash of its bytes, checked here; together they are package {exp.get('digest')}",
              "authenticity: 8 records signed with a key your trust binds to the record's actor; each signature verified here",
              "execution: 5 schemas counted at your quorum of 1 schema/author: claim@1, finding@1, goal@1, obligation@1, pr-head@1",
              f"reliance: {d[:12]} (obligation@1, state done) is the effective version of its lineage; its guard is met by bob (roadmap/acceptor)",
              f"reliance: no challenge in the package stands against {d[:12]}"]
          and ans.get("not_established") == [COMPLETENESS, SENDERS_ROOTS],
          "a good package: exit 0, the root is the effective version of its lineage, its guard met by an actor holding a role "
          "of the receiver's profile; the answer says what was checked here and what no package can show", (code, ans))

    code, ans = ask(with_line(pkg, a, flip), src)
    r = root(ans, d)
    check("U02", code == 1 and ans.get("rely") is False and r.get("why_not") == ["NOT_EFFECTIVE"] and r.get("guard", {}).get("guard") == "PENDING"
          and ans.get("authenticity", {}).get("rejected") == {a: "BAD_SIGNATURE"} and ans.get("authenticity", {}).get("signed") == 7
          and "authenticity: 1 record with no signature that verifies under your trust and no migration you accept: left out, "
              "counted for nothing" in ans.get("not_established", [])
          and f"reliance: {d[:12]} is not relied on: its guard waits for {waits()}; {o[:12]} is the effective version of its lineage"
          in ans.get("not_established", []),
          "one byte of the acceptance's signature flipped: exit 1, the acceptance counts for nothing and the root's guard waits", (code, ans))
    code, ans = ask(with_line(pkg, d, flip), src)
    r = root(ans, d)
    check("U03", code == 1 and r.get("why_not") == ["UNAVAILABLE"] and r.get("kind") == "unavailable" and r.get("rejected") == "BAD_SIGNATURE"
          and f"reliance: {d[:12]} is not relied on: the package holds no admitted record of that id (its line is BAD_SIGNATURE)"
          in ans.get("not_established", []),
          "one byte of the root's own signature flipped: exit 1, the root is no admitted record", (code, ans))

    other = Receiver(src.trust, {"warrant": "profile/3", "roles": dict(src.profile["roles"], **{"roadmap/acceptor": ["carol"]})})
    code, ans = ask(pkg, other)
    r = root(ans, d)
    check("U04", code == 1 and r.get("rely") is False and r.get("why_not") == ["NOT_EFFECTIVE"] and r.get("accepted") == []
          and r.get("guard", {}).get("waiting") == [waits()] and r.get("lineage", {}).get("state") == "open"
          and r.get("lineage", {}).get("reliance") == "ELIGIBLE" and r.get("lineage", {}).get("effective") == o,
          "a guard met under the sender's profile and not under the receiver's: exit 1, though the lineage's earlier version "
          "still reads ELIGIBLE", (code, ans))

    c = src.put("bob", "challenge", {"target": d, "statement": "it fails on Tuesdays"}, refs=[d])
    challenged = export(src, d).get("package", {})
    code, ans = ask(challenged, src)
    r = root(ans, d)
    check("U05", code == 1 and r.get("why_not") == ["CHALLENGED"] and r.get("lineage", {}).get("reliance") == "CHALLENGED"
          and r.get("guard", {}).get("guard") == "MET" and r.get("challenges", {}).get(c, {}).get("stands") is True
          and r.get("challenges", {}).get(c, {}).get("actor") == "bob"
          and f"reliance: {d[:12]} is not relied on: a counted challenge stands against it: {c[:12]}" in ans.get("not_established", []),
          "a counted challenge standing against the root: exit 1, the guard's verdict unchanged", (code, ans))
    left_out = dict(challenged, lines=[x for x in challenged["lines"] if R.rid(json.loads(x)["record"]) != c])
    code, ans = ask(left_out, src)
    check("U06", code == 0 and root(ans, d).get("rely") is True and root(ans, d).get("challenges") == {}
          and COMPLETENESS in ans.get("not_established", []) and ans.get("completeness", {}).get("attested") == "UNATTESTED",
          "the same package with the challenge left out by its sender: exit 0, and the answer says a package cannot show "
          "what its sender left out", (code, ans))

    f = Repo()
    fo = f.entity("alice", "obligation@1", {"state": "open", "statement": "task", "serves": []})
    d1 = f.entity("alice", "obligation@1", {"state": "done", "statement": "task", "serves": []}, lineage=fo)
    d2 = f.entity("alice", "obligation@1", {"state": "done", "statement": "task, again", "serves": []}, lineage=fo)
    f.attest("bob", d1)
    code, ans = ask(export(f, d1).get("package", {}), f)
    r = root(ans, d1)
    check("U07", code == 1 and r.get("why_not") == ["NOT_EFFECTIVE"] and r.get("lineage", {}).get("verdict") == "FORK"
          and r.get("lineage", {}).get("forks") == [[fo, sorted([d1, d2])]] and r.get("guard", {}).get("guard") == "MET"
          and f"reliance: {d1[:12]} is not relied on: its lineage forks and has no effective version" in ans.get("not_established", []),
          "a forked lineage: exit 1 for a branch whose own guard is met", (code, ans))

    code, ans = ask(dict(pkg, blobs={}), src)
    r = root(ans, d)
    whole = root(ask(pkg, src)[1], d)
    check("U08", code == 0 and r.get("rely") is True and r.get("unavailable") == [h] and ans.get("completeness", {}).get("unavailable") == [h]
          and f"completeness: 1 record or blob that the roots rest on, named and not in the package: {h[:12]}" in ans.get("not_established", [])
          and whole.get("unavailable") == [] and ans.get("integrity", {}).get("blobs") == 0,
          "an evidence blob the root names and the package does not hold: listed as not established, by its hash; the "
          "version's acceptance covers its id, not the blob's presence", (code, ans))

    code, ans = ask(dict(pkg, roots=sorted([d, "ab" * 32])), src)
    check("U09", code == 1 and ans.get("rely") is False and root(ans, d).get("rely") is True
          and root(ans, "ab" * 32).get("why_not") == ["UNAVAILABLE"] and root(ans, "ab" * 32).get("rejected") is None
          and f"reliance: {'ab' * 6} is not relied on: the package holds no admitted record of that id" in ans.get("not_established", []),
          "a package naming a root it does not carry: exit 1, though its other root is relied on", (code, ans))

    code, ans = ask(pkg, src, "--require", o)
    r = root(ans, o)
    again, mine = ask(pkg, src, "--require", d)
    check("U10", code == 1 and ans.get("asked") == {"by": "receiver", "roots": [o]} and list(ans.get("roots", {})) == [o]
          and r.get("why_not") == ["NOT_EFFECTIVE"] and r.get("guard", {}).get("guard") == "NONE"
          and f"reliance: {o[:12]} is not relied on: {d[:12]} is the effective version of its lineage" in ans.get("not_established", [])
          and SENDERS_ROOTS not in ans.get("not_established", []) and again == 0 and mine.get("not_established") == [COMPLETENESS],
          "--require: the receiver's roots are answered, not the package's; an earlier version of a lineage is not the one "
          "to rely on once a later one is effective", (code, ans, again, mine))

    code, ans = ask(dict(pkg, roots=[]), src)
    check("U11", code == 1 and ans.get("rely") is False and ans.get("roots") == {} and ans.get("refused") is None
          and "reliance: no root is named, by --require or by the package: nothing was asked, nothing is relied on" in ans.get("not_established", []),
          "a package that names no root, and no --require: exit 1, never a yes to nothing", (code, ans))

    code, ans = ask(pkg, src, "--require", a)
    check("U12", code == 1 and root(ans, a).get("why_not") == ["NOT_A_VERSION"] and root(ans, a).get("kind") == "attest"
          and f"reliance: {a[:12]} is not relied on: it is a record of kind attest in no lineage" in ans.get("not_established", []),
          "a root that is an attest, not a version of a lineage: exit 1", (code, ans))

    at = json.loads(next(x for x in pkg["lines"] if R.rid(json.loads(x)["record"]) == d))["record"]["at"]
    code, ans = ask(pkg, src, "--as-of", str(at))
    check("U13", code == 1 and root(ans, d).get("why_not") == ["NOT_EFFECTIVE"] and ans.get("completeness", {}).get("later") == 1
          and ans.get("receiver", {}).get("as_of") == at
          and f"completeness: 1 record dated after {at}, left out of this view" in ans.get("not_established", []),
          "--as-of before the acceptance: it is left out, counted, and the root's guard waits", (code, ans))

    v3 = put("v3.json", {"warrant": "repository/3", "repository": "s0fractal/warrant", "trust": src.trust, "profile": src.profile})
    p = put("package.json", pkg)
    code, ans = run([p, "--config", v3])
    check("U14", code == 0 and ans == ask(pkg, src)[1], "--config: a file holding the trust and the profile gives the answer the two files give", (code, ans))

    same = []
    for recv in (src, other):
        ins = api.call(Config({"agent_api": "warrant-agent/3", "workspaces": {"w": {"store": str(Repo().dot), "trust": put("t.json", recv.trust),
                                                                                    "profile": put("p.json", recv.profile)}}}),
                       "handoff", {"workspace": "w", "op": "inspect", "package": dict(challenged, roots=sorted([d, "ab" * 32])), "alone": True}).get("ok", {})
        ans = ask(challenged, recv)[1]
        cap, r = ins.get("roots", {}).get(d, {}), root(ans, d)
        same.append(bool(cap) and ins.get("roots", {}).get("ab" * 32) == {"id": "ab" * 32, "kind": "unavailable"} and cap.get("guard") == r.get("guard") and cap.get("lineage") == {k: (r.get("lineage") or {}).get(k) for k in cap.get("lineage", {})}
                    and all(cap.get(k) == r.get(k) for k in ("kind", "schema", "actor", "at", "basis")) and ins.get("package") == ans.get("package"))
    check("U15", same == [True, True], "the agent's `handoff inspect` of a package alone and `warrant verify` read it through one reader: "
          "the same digest, node, guard and lineage, under the sender's profile and under another; a root the package does not "
          "carry reads unavailable there too", same)
    return src, pkg, d


def more_reliance_cases():
    w = Repo(roles=dict(ROLES, migrator=["carol"]))
    r = R.record("entity", "bob", w.t, {"state": "open", "statement": "carried over", "serves": []}, "obligation@1")
    mid, line = R.line(r, None)
    w.store.add_lines([line])
    hm = w.blob(C.canon({"map": [[mid, ["11" * 32], []]]}))
    m = w.put("carol", "attest", {"target": hm, "verdict": "migrated"}, R.MIGRATION, refs=[hm])
    pkg = export(w, mid).get("package", {})
    code, ans = ask(pkg, w)
    plain = Receiver(w.trust, {"warrant": "profile/3", "roles": {k: v for k, v in w.profile["roles"].items() if k != "migrator"}})
    code2, ans2 = ask(pkg, plain)
    check("U16", code == 0 and root(ans, mid).get("basis") == "MIGRATED" and ans.get("authenticity", {}).get("migrated") == 1
          and ans.get("authenticity", {}).get("migrations") == [{"attest": m, "actor": "carol", "records": 1}]
          and f"authenticity: 1 record unsigned, vouched for by migration {m[:12]} of carol, a migrator in your profile: that "
              "actor's word, not the writers' signatures" in ans.get("not_established", [])
          and f"reliance: {mid[:12]} (obligation@1, state open) is the effective version of its lineage; it carries no guard and stands "
              "as filed by bob, unsigned, on a migration's word" in ans.get("established", [])
          and code2 == 1 and root(ans2, mid).get("why_not") == ["UNAVAILABLE"] and root(ans2, mid).get("rejected") == "UNSIGNED"
          and ans2.get("authenticity", {}).get("rejected") == {mid: "UNSIGNED"},
          "a record a migration vouches for: relied on by a receiver whose profile has that migrator, and said to be the "
          "migrator's word, not a signature; for another receiver it is no admitted record", (code, ans, code2, ans2))

    done = w.entity("alice", "obligation@1", {"state": "open", "statement": "signed work beside it", "serves": []})
    exp = export(w, done)
    light = exp.get("package", {})
    heavy = dict(light, lines=sorted(light["lines"] + [x for x in pkg["lines"] if R.rid(json.loads(x)["record"]) == m]), blobs=pkg["blobs"])
    (c1, a1), (c2, a2) = ask(light, w), ask(heavy, w)
    kinds = {json.loads(x)["record"]["schema"] for x in light["lines"]}
    check("U46", R.MIGRATION not in kinds and light["blobs"] == {} and len(heavy["lines"]) == len(light["lines"]) + 1 and hm in heavy["blobs"]
          and c1 == c2 == 0 and a1.get("roots") == a2.get("roots") and bool(a1.get("roots")) and a1.get("execution") == a2.get("execution")
          and a2.get("integrity", {}).get("bytes", 0) - a1.get("integrity", {}).get("bytes", 0) > len(C.canon({"map": [[mid, ["11" * 32], []]]})),
          "a migration travels with the records it vouches for: a package of signed records alone carries neither its attest nor "
          "its map, and reads the same, root for root, as the package with both put back", (kinds, c1, c2, a1.get("roots") == a2.get("roots")))

    q = Repo()
    first = q.entity("alice", "obligation@1", {"state": "open", "statement": "first", "serves": []})
    q.attest("bob", q.entity("alice", "obligation@1", {"state": "done", "statement": "first", "serves": []}, lineage=first))
    second = q.entity("alice", "obligation@1", {"state": "open", "statement": "second", "serves": []})
    q.attest("bob", q.entity("alice", "obligation@1", {"state": "done", "statement": "second", "serves": []}, lineage=second, requires=[first]))
    third = q.entity("alice", "obligation@1", {"state": "open", "statement": "third", "serves": []})
    d3 = q.entity("alice", "obligation@1", {"state": "done", "statement": "third", "serves": []}, lineage=third, requires=[second])
    q.attest("bob", d3)
    home = q.report()
    code, ans = ask(export(q, d3).get("package", {}), q)
    check("U47", home["lineages"][third]["state"] == "done" and home["versions"][d3]["guard"] == "MET"
          and code == 0 and root(ans, d3).get("guard", {}).get("guard") == "MET" and root(ans, d3).get("guard", {}).get("waiting") == []
          and root(ans, d3).get("lineage", {}).get("state") == "done" and ans.get("integrity", {}).get("records") == 5 + 9,
          "a closure that requires other lineages closed travels with their closing versions and the acceptances of those, "
          "through every lineage they require in turn: handed over alone it reads as at home (observed on 9509b865: 8 of this "
          "repository's 35 accepted obligations read PENDING from their own package, the requirement's root carried and its "
          "closure left behind)", (code, root(ans, d3).get("guard"), ans.get("integrity")))

    u = Repo()
    u.entity("alice", "obligation@1", {"state": "open", "statement": "another matter", "serves": []})
    o = u.entity("alice", "obligation@1", {"state": "open", "statement": "task", "serves": []})
    code, ans = ask(export(u, o).get("package", {}), u)
    check("U17", code == 0 and ans.get("completeness", {}).get("unanchored") == 1 and root(ans, o).get("guard", {}).get("guard") == "NONE"
          and "completeness: 1 signed record naming an earlier record of its writer that the package does not hold: the writers' "
              "own order is not witnessed here" in ans.get("not_established", []),
          "a record whose writer's previous record the package does not hold: the writers' own order is not established", (code, ans))

    src, h, o, d, a = base()
    pkg = export(src, d).get("package", {})
    two = Receiver(src.trust, {"warrant": "profile/3", "roles": dict(src.profile["roles"], **{"schema/author": ["alice", "carol"]}),
                               "quorum": {"schema/author": 2}})
    code, ans = ask(pkg, two)
    ex = ans.get("execution", {})
    check("U18", code == 1 and root(ans, d).get("why_not") == ["UNAVAILABLE"] and root(ans, d).get("rejected") == "INVALID"
          and ex.get("schemas") == {} and ex.get("quorum") == 2 and sorted(ex.get("schemas_pending", {}).values()) ==
          ["claim@1", "finding@1", "goal@1", "obligation@1", "pr-head@1"] and sorted(ex.get("invalid", [])) == sorted([o, d])
          and ans.get("authenticity", {}).get("rejected") == {}
          and "execution: 5 schemas short of your quorum of 2 schema/author, counted for nothing: claim@1, finding@1, goal@1, "
              "obligation@1, pr-head@1" in ans.get("not_established", [])
          and "execution: 2 records that fit no schema you count: left out" in ans.get("not_established", []),
          "a receiver whose quorum of schema authors the package's schemas do not reach: they count for nothing, and so does "
          "the root; a record that fits no counted schema is not listed as a bad signature", (code, ans))

    stranger = K.Key.from_seed_hex("a7" * 32)
    cr = R.record("challenge", f"key:{stranger.public}", src.t + 1, {"target": d, "statement": "a stranger's thesis"}, refs=[d])
    cid, line = R.line(cr, stranger)
    src.store.add_lines([line])
    code, ans = ask(export(src, d).get("package", {}), src)
    ch = root(ans, d).get("challenges", {}).get(cid, {})
    check("U19", code == 0 and ans.get("authenticity", {}).get("named_keys") == 1 and ans.get("authenticity", {}).get("signed") == 9
          and ch.get("counted") is False and ch.get("stands") is False and ch.get("actor") == f"key:{stranger.public}"
          and "authenticity: 8 records signed with a key your trust binds to the record's actor; each signature verified here" in ans.get("established", [])
          and "authenticity: 1 challenge signed with the key its actor names itself by; the signature verified here, and no "
              "trust says whose key it is" in ans.get("established", []),
          "a stranger's challenge under its own key: authentic as that key's and counted apart from the records your trust "
          "binds; a thesis, it does not stand", (code, ans))


# ---------------------------------------------------------------- pins

def pinned(roles=None, quorum=1):
    """A checkout with lib/code.py committed, and an obligation closed by a version waiting for `quorum` acceptors."""
    r = Repo(roles=roles, git_init=True)
    (r.root / "lib").mkdir()
    (r.root / "lib" / "code.py").write_text("X = 1\n")
    x = r.commit("code")
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "task", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "task", "serves": []}, lineage=o,
                 guard={"quorum": quorum, "roles": ["roadmap/acceptor"], "match": ACCEPT, "requires": []})
    return r, x, git(r.root, "rev-parse", f"{x}:lib/code.py"), d


def at(r):
    """A copy of the checkout as it is now: what a kept run is repeated on."""
    d = Path(tempfile.mkdtemp(dir=TMP)) / "checkout"
    shutil.copytree(r.root, d, symlinks=True)
    return str(d)


def pins_of(ans, d):
    return root(ans, d).get("pins", {})


def pin_cases():
    r, x, blob, d = pinned()
    a = r.attest("bob", d, commit=x, files={"lib/code.py": blob})
    pkg = export(r, d).get("package", {})
    fresh = at(r)
    tree = git(r.root, "rev-parse", f"{x}^{{tree}}")
    (r.root / "lib" / "code.py").write_text("X = 2\n")
    y = r.commit("the file changes")
    stale = at(r)
    tree_y = git(r.root, "rev-parse", f"{y}^{{tree}}")
    code0, ans0 = ask(pkg, r, "--checkout", fresh)
    code1, ans1 = ask(pkg, r, "--checkout", stale)
    row = {"attest": a, "actor": "bob", "commit": x}
    check("U20", code0 == 0 and ans0.get("checkout") == {"tree": tree} and pins_of(ans0, d) == {"verdict": "FRESH", "acceptances": [
              dict(row, verdict="UNCHANGED", files=[{"path": "lib/code.py", "blob": blob, "verdict": "UNCHANGED", "detail": ""}])]}
          and f"pins: {d[:12]}: the acceptance {a[:12]} by bob names 1 file, the same bytes in your tree {tree[:12]}" in ans0.get("established", [])
          and code1 == 1 and root(ans1, d).get("why_not") == ["STALE"] and root(ans1, d).get("lineage", {}).get("reliance") == "STALE"
          and root(ans1, d).get("guard", {}).get("guard") == "MET" and ans1.get("checkout") == {"tree": tree_y}
          and pins_of(ans1, d) == {"verdict": "STALE", "acceptances": [
              dict(row, verdict="CHANGED", files=[{"path": "lib/code.py", "blob": blob, "verdict": "CHANGED", "detail": f"since {y[:12]}"}])]}
          and f"pins: {d[:12]}: the acceptance {a[:12]} by bob names 1 file; 1 file of them are other bytes in your tree {tree_y[:12]}"
          in ans1.get("not_established", [])
          and f"reliance: {d[:12]} is not relied on: the files its acceptances name are no longer those bytes in your tree" in ans1.get("not_established", []),
          "a pin compared with the receiver's checkout: the same bytes, exit 0; other bytes at the path, the root reads STALE "
          "and exit 1, with the first commit that changed the file", (code0, ans0, code1, ans1))

    code, ans = ask(pkg, r)
    check("U21", code == 0 and ans.get("checkout") is None and pins_of(ans, d) == {"verdict": "NOT_CHECKED", "acceptances": [
              dict(row, verdict="NOT_CHECKED", files=[{"path": "lib/code.py", "blob": blob, "verdict": "NOT_CHECKED", "detail": ""}])]}
          and f"pins: {d[:12]}: the acceptance {a[:12]} by bob names 1 file; no checkout was given, so whether they are still "
              "those bytes is not checked" in ans.get("not_established", []),
          "a pin and no checkout: listed with its path and blob as not checked, and said so; the gate is the rest", (code, ans))

    def no_git(*_a, **_k):
        raise FileNotFoundError("git")
    empty = tempfile.mkdtemp(dir=TMP)
    code, ans = ask(pkg, r, "--checkout", stale, env={"PATH": empty}, patch=(P, "git", no_git))
    check("U22", code == 1 and root(ans, d).get("why_not") == ["PINS_NOT_CHECKED"] and ans.get("checkout") == {"tree": None}
          and pins_of(ans, d).get("verdict") == "NOT_CHECKED" and root(ans, d).get("lineage", {}).get("reliance") == "ELIGIBLE"
          and f"pins: {d[:12]}: the acceptance {a[:12]} by bob names 1 file; git is not available here, so whether they are still "
              "those bytes is not checked" in ans.get("not_established", []),
          "a checkout asked for and no git to read it: the pins read not checked, never fresh, and exit 1", (code, ans))

    a2 = r.attest("bob", d, commit=y, files={"lib/code.py": git(r.root, "rev-parse", f"{y}:lib/code.py")})
    code, ans = ask(export(r, d).get("package", {}), r, "--checkout", stale)
    words = {x["attest"]: x["verdict"] for x in pins_of(ans, d).get("acceptances", [])}
    check("U23", code == 0 and pins_of(ans, d).get("verdict") == "FRESH" and words == {a: "CHANGED", a2: "UNCHANGED"},
          "accepted again at the new bytes: the earlier acceptance stays stale in the package and the root is fresh", (code, ans))

    m, mx, mblob, md = pinned()
    ma = m.attest("bob", md, commit=mx, files={"lib/code.py": mblob})
    git(m.root, "mv", "lib/code.py", "lib/перенесено.py")
    m.commit("the file moves, its bytes unchanged")
    code, ans = ask(export(m, md).get("package", {}), m, "--checkout", at(m))
    files = (pins_of(ans, md).get("acceptances") or [{}])[0].get("files")
    check("U24", code == 0 and pins_of(ans, md).get("verdict") == "FRESH"
          and files == [{"path": "lib/code.py", "blob": mblob, "verdict": "MOVED", "detail": "now at lib/перенесено.py"}]
          and any(s.startswith(f"pins: {md[:12]}: the acceptance {ma[:12]} by bob names 1 file, the same bytes in your tree ")
                  and s.endswith(", 1 at another path") for s in ans.get("established", [])),
          "a file moved with its bytes unchanged: fresh, at its new path, exit 0", (code, ans))

    both = dict(ROLES, **{"roadmap/acceptor": ["bob", "carol"]})
    got = {}
    for quorum in (1, 2):
        q, qx, qblob, qd = pinned(roles=both, quorum=quorum)
        q.attest("bob", qd, commit=qx, files={"lib/code.py": qblob})
        q.attest("carol", qd)
        (q.root / "lib" / "code.py").write_text("X = 3\n")
        q.commit("the file changes")
        code, ans = ask(export(q, qd).get("package", {}), q, "--checkout", at(q))
        got[quorum] = (code, pins_of(ans, qd).get("verdict"), root(ans, qd).get("why_not"), root(ans, qd).get("guard", {}).get("accepted_by"),
                       len(pins_of(ans, qd).get("acceptances", [])))
    check("U25", got[1] == (0, "FRESH", [], ["bob", "carol"], 1),
          "a stale pin beside an acceptance that names no files, quorum 1: the guard is still met by the one who named none, exit 0", got[1])
    check("U26", got[2] == (1, "STALE", ["STALE"], ["bob", "carol"], 1),
          "a stale pin beside an acceptance that names no files, quorum 2: the guard is no longer met by two, exit 1", got[2])

    e, ex, _, ed = pinned()
    ea = e.attest("bob", ed, commit=ex, files={})
    epkg = export(e, ed).get("package", {})
    code, ans = ask(epkg, e, "--checkout", at(e))
    code2, ans2 = ask(epkg, e)
    check("U27", code == 1 and root(ans, ed).get("why_not") == ["STALE"]
          and pins_of(ans, ed) == {"verdict": "STALE", "acceptances": [{"attest": ea, "actor": "bob", "commit": ex, "verdict": "UNKNOWN", "files": []}]}
          and f"pins: {ed[:12]}: the acceptance {ea[:12]} by bob names its files in no form that can be compared" in ans.get("not_established", [])
          and code2 == 0 and pins_of(ans2, ed).get("verdict") == "NOT_CHECKED",
          "an acceptance whose `files` names nothing that can be compared: with a checkout it is not fresh, exit 1", (code, ans, code2))

    s, sx, _, sd = pinned()
    sa = s.attest("bob", sd)
    s.attest("bob", sd, verdict="seen", commit=sx, files={"lib/code.py": "0" * 40})
    code, ans = ask(export(s, sd).get("package", {}), s, "--checkout", at(s))
    check("U43", code == 0 and root(ans, sd).get("accepted") == [{"attest": sa, "actor": "bob", "roles": ["roadmap/acceptor"]}]
          and pins_of(ans, sd) == {"verdict": "NONE", "acceptances": []},
          "an attest by the acceptor that does not match the guard is not behind the root: not listed as an acceptance, and the "
          "files it names are no pin", (code, ans))

    n = Repo(git_init=True)
    no = n.entity("alice", "obligation@1", {"state": "open", "statement": "task", "serves": []})
    code, ans = ask(export(n, no).get("package", {}), n, "--checkout", at(n))
    check("U28", code == 0 and pins_of(ans, no) == {"verdict": "NONE", "acceptances": []}
          and f"pins: {no[:12]}: no acceptance behind it names files: nothing ties it to your tree" in ans.get("not_established", []),
          "a checkout given and no acceptance that names files: nothing was compared, and the answer says so", (code, ans))


# ---------------------------------------------------------------- refusals, and the command line

def refusal_cases(src, pkg, d):
    def refused(data, *more):
        code, ans = ask(data, src, *more)
        return code, (ans.get("refused") or {}).get("code"), ans

    def text(**members):
        return json.dumps(dict(pkg, **members)).encode()
    hb = next(iter(pkg["blobs"]))
    got = {"not JSON": refused(b"{not json"), "not UTF-8": refused(b"\xff\xfe{}"), "an array": refused(b"[]"), "empty": refused(b""),
           "another version": refused(text(warrant="package/2")), "a member more": refused(text(note="x")),
           "a member less": refused(json.dumps({k: v for k, v in pkg.items() if k != "blobs"}).encode()),
           "a root that is no id": refused(text(roots=["zz"])), "a root with a newline": refused(text(roots=[d + "\n"])),
           "lines not a list": refused(text(lines="x")), "a line not a string": refused(text(lines=[1])),
           "a float": refused(text(roots=[1.5])), "NaN": refused(json.dumps(pkg).encode().replace(b'"roots": [', b'"roots": [NaN, ', 1)),
           "not base64": refused(text(blobs={hb: "@@@"})), "a blob that is no string": refused(text(blobs={hb: 5})),
           "a blob with a newline after it": refused(text(blobs={hb: pkg["blobs"][hb] + "\n"})),
           "a blob with text after it": refused(text(blobs={hb: pkg["blobs"][hb] + "!"})),
           "a blob padded once more": refused(text(blobs={hb: pkg["blobs"][hb] + "="})),
           "a blob under another name": refused(text(blobs={"00" * 32: pkg["blobs"][hb]})),
           "a blob under no hash": refused(text(blobs={"x": base64.b64encode(b"x").decode()})),
           "a line that is no record": refused(text(lines=pkg["lines"] + ["{}"])),
           "two lines that are no records": refused(text(lines=pkg["lines"] + ["{}", "x"]))}
    want = {"not JSON": "NOT_JSON", "not UTF-8": "NOT_JSON", "an array": "NOT_A_PACKAGE", "empty": "NOT_JSON",
            "another version": "NOT_A_PACKAGE", "a member more": "NOT_A_PACKAGE", "a member less": "NOT_A_PACKAGE",
            "a root that is no id": "NOT_A_PACKAGE", "a root with a newline": "NOT_A_PACKAGE", "lines not a list": "NOT_A_PACKAGE",
            "a line not a string": "NOT_A_PACKAGE", "a float": "NOT_A_PACKAGE", "NaN": "NOT_A_PACKAGE", "not base64": "BAD_BASE64",
            "a blob that is no string": "BAD_BASE64", "a blob with a newline after it": "BAD_BASE64", "a blob with text after it": "BAD_BASE64",
            "a blob padded once more": "BAD_BASE64", "a blob under another name": "BAD_BLOB", "a blob under no hash": "BAD_BLOB",
            "a line that is no record": "BAD_LINE", "two lines that are no records": "BAD_LINE"}
    shaped = all(c == 1 and a.get("rely") is False and a.get("roots") == {} and a.get("package") is None and a.get("established") == []
                 and a.get("not_established") == [f"integrity: the package was refused and nothing in it was assessed: {a['refused']['why']}"]
                 for c, _, a in got.values() if a.get("refused"))
    check("U29", {k: v[1] for k, v in got.items()} == want and shaped
          and got["two lines that are no records"][2]["refused"]["why"] == "2 line(s) of the package are not records"
          and got["a member more"][2]["refused"]["why"] == "a package is {warrant: package/3, roots, lines, blobs}",
          "a malformed package is refused whole, exit 1, with the code of what is wrong and nothing assessed",
          {k: v[:2] for k, v in got.items() if v[1] != want[k]} or got)

    twice = json.dumps(pkg).encode().replace(b'"roots": [', b'"roots": [], "roots": [', 1)
    first = json.dumps(pkg).encode().replace(b'"roots": [', b'"roots": ["' + ("cd" * 32).encode() + b'"], "roots": [', 1)
    env = json.loads(pkg["lines"][0])
    inner = C.canon(env).decode().replace('"at":', '"at":0,"at":', 1)
    floated = C.canon(env).decode().replace(f'"at":{env["record"]["at"]}', f'"at":{env["record"]["at"]}.0', 1)
    got = {"a member twice": refused(twice), "a member twice, the first another": refused(first),
           "a record's member twice": refused(text(lines=pkg["lines"] + [inner])),
           "a float in a record": refused(text(lines=pkg["lines"] + [floated])),
           "a lone surrogate in a line": refused(json.dumps(pkg).encode().replace(b'"lines": [', b'"lines": ["\\ud800", ', 1))}
    check("U30", {k: v[:2] for k, v in got.items()} == {"a member twice": (1, "NOT_JSON"), "a member twice, the first another": (1, "NOT_JSON"),
                                                         "a record's member twice": (1, "BAD_LINE"), "a float in a record": (1, "BAD_LINE"),
                                                         "a lone surrogate in a line": (1, "BAD_LINE")}
          and inner != C.canon(env).decode() and floated != C.canon(env).decode(),
          "a package reads one way or not at all: a member named twice (in the package or in a record), a float in a record "
          "and a line that is not UTF-8 are refused, never read by one reader's convention", {k: v[:2] for k, v in got.items()})

    code, why, ans = refused(text(lines=[pkg["lines"][0] + "\n"] + pkg["lines"][1:]))
    check("U31", (code, why) == (1, "BAD_LINE") and ans["refused"]["why"] == "1 line(s) of the package are not records",
          "a line with a second newline is refused: it would be the same record under another package digest", (code, why))

    raw = json.dumps(pkg).encode()
    fits, _, a_fits = refused(raw, "--max-bytes", str(len(raw)))
    over, why, a_over = refused(raw, "--max-bytes", str(len(raw) - 1))
    inner = V.verify(raw, src.trust, src.profile, limit=len(raw) - 1)
    check("U32", fits == 0 and a_fits.get("refused") is None and (over, why) == (1, "TOO_LARGE")
          and a_over["refused"]["why"] == f"the package is larger than {len(raw) - 1} bytes"
          and (inner.get("refused") or {}).get("code") == "TOO_LARGE" and inner.get("rely") is False,
          "a package larger than --max-bytes is refused, exit 1; one of exactly that size is read", (fits, over, why, inner.get("refused")))

    t, p, k = put("trust.json", src.trust), put("profile.json", src.profile), put("package.json", pkg)
    bare = tempfile.mkdtemp(dir=TMP)
    git(bare, "init", "-q")
    lines = {"no receiver": [k], "a trust and no profile": [k, "--trust", t], "a configuration and a trust": [k, "--config", t, "--trust", t, "--profile", p],
             "a configuration and a profile": [k, "--config", put("v3.json", {"trust": src.trust, "profile": src.profile}), "--profile", p],
             "no package": ["--trust", t, "--profile", p], "a package that is not there": [k + ".none", "--trust", t, "--profile", p],
             "a trust that is not there": [k, "--trust", t + ".none", "--profile", p], "a trust that is no trust": [k, "--trust", p, "--profile", p],
             "a profile that is no JSON": [k, "--trust", t, "--profile", put("p.json", b"{")],
             "a trust naming a member twice": [k, "--trust", put("t.json", json.dumps(src.trust).encode().replace(b'"keys": {', b'"keys": {}, "keys": {', 1)), "--profile", p],
             "a configuration with no profile": [k, "--config", t], "a root that is no id": [k, "--trust", t, "--profile", p, "--require", "abc"],
             "a root in capitals": [k, "--trust", t, "--profile", p, "--require", d.upper()],
             "a checkout with no commit": [k, "--trust", t, "--profile", p, "--checkout", bare],
             "a checkout that is not there": [k, "--trust", t, "--profile", p, "--checkout", bare + ".none"],
             "an option it does not have": [k, "--trust", t, "--profile", p, "--store", "x"],
             "a limit of nothing": [k, "--trust", t, "--profile", p, "--max-bytes", "0"],
             "a time before time": [k, "--trust", t, "--profile", p, "--as-of", "-1"]}
    got = {n: (run(argv)[0], RUNS[-1][2]) for n, argv in lines.items()}
    check("U33", all(v == (2, b"") for v in got.values()),
          "a command line or a file of the receiver's own that cannot be read: exit 2 and no answer, never the code of a verdict",
          {n: v for n, v in got.items() if v != (2, b"")})

    def agent(package, **limits):
        cfg = Config({"agent_api": "warrant-agent/3", "workspaces": {"w": dict({"repo": str(src.root)}, **({"limits": limits} if limits else {}))}})
        out = api.call(cfg, "handoff", {"workspace": "w", "op": "inspect", "package": package, "alone": True})
        return out.get("error"), out.get("message")
    got = {"shape": agent(dict(pkg, note="x")), "base64": agent(dict(pkg, blobs={hb: "@@@"})), "name": agent(dict(pkg, blobs={"00" * 32: pkg["blobs"][hb]})),
           "line": agent(dict(pkg, lines=pkg["lines"] + ["{}"])), "size": agent(pkg, store_bytes=100)}
    check("U44", got["shape"] == ("BAD_REQUEST", "a package is {warrant: package/3, roots, lines, blobs}")
          and got["base64"][0] == "BAD_REQUEST" and got["base64"][1] == "a blob is not base64"
          and got["name"] == ("BAD_REQUEST", "a blob is not named by its hash") and got["line"] == ("BAD_REQUEST", "1 line(s) of the package are not records")
          and got["size"] == ("RESOURCE_LIMIT", "the package exceeds the workspace's store_bytes"),
          "the agent's handoff refuses a malformed package with the codes and words it had before the core read packages", got)

    deep = Repo()
    lines, prev, before = deep.store.lines(), E.head(deep.store.snapshot(), deep.trust, "alice")["id"], None
    for n in range(130):                   # signed lines made here, chained by hand: 260 appends would each rewrite the store
        r = R.record("entity", "alice", deep.t + n, {"state": "open", "statement": f"link {n}", "serves": []}, "obligation@1", None, (), None, prev)
        lo, line = R.line(r, KEYS["alice"])
        lines.append(line)
        g = R.guard(1, ["roadmap/acceptor"], ACCEPT, [before] if before else [])
        r = R.record("entity", "alice", deep.t + n, {"state": "done", "statement": f"link {n}", "serves": []}, "obligation@1", lo, (), g, lo)
        last, line = R.line(r, KEYS["alice"])
        lines.append(line)
        prev, before = last, lo
    chain = {"warrant": "package/3", "roots": [last], "lines": [x.decode().rstrip("\n") for x in lines], "blobs": {}}
    shallow = dict(chain, lines=chain["lines"][:5 + 2 * 128], roots=[R.rid(json.loads(chain["lines"][5 + 2 * 128 - 1])["record"])])
    fits = refused(shallow)
    code, why, ans = refused(chain)
    check("U45", (code, why) == (1, "LIMITS") and ans["refused"]["why"] == "the package is beyond the engine's limits"
          and fits[1] is None and fits[2].get("integrity", {}).get("records") == 5 + 2 * 128,
          "a package beyond the engine's limits (requirements nested 130 deep) is refused, exit 1: a refusal, not an error; "
          "one nested 128 deep is read", (code, why, fits[:2]))

    def broken(*_a, **_k):
        raise RuntimeError("the verifier's own defect")
    code, ans = run([k, "--trust", t, "--profile", p], keep=False, patch=(V, "verify", broken))
    check("U34", code == 3 and ans == {}, "an error of the verifier itself: exit 3 and no answer, never the 1 of a refusal", (code, ans))


# ---------------------------------------------------------------- one answer, by three doors

def shape_cases():
    bad = []
    for argv, code, text, _ in RUNS:
        if not text:
            if code not in (2,):
                bad.append((argv, "no answer and exit", code))
            continue
        ans = json.loads(text)
        ok = (text == C.canon(ans) + b"\n" and set(ans) == TOP and ans["warrant"] == "verify/3" and ans["rely"] is (code == 0) and code in (0, 1)
              and all(set(r) == ROOT_MEMBERS and r["rely"] is (not r["why_not"]) for r in ans["roots"].values())
              and ans["rely"] is (bool(ans["roots"]) and all(r["rely"] for r in ans["roots"].values()))
              and (ans["refused"] is None) is (ans["package"] is not None) and sorted(ans["roots"]) == ans["asked"]["roots"] or ans["refused"]
              and ans["rely"] is False and code == 1)
        if not ok:
            bad.append((argv, code))
    n = sum(1 for r in RUNS if r[2])
    check("U35", not bad and n >= 40, f"each of {n} answers is one canonical line with the same members, `rely` is the exit status, and a "
          "root is relied on exactly when nothing says why not", bad[:3])


def single_cases():
    built = BUILD.build()
    src, order = BUILD.closure()
    digest = {n: hashlib.sha256((ROOT / "warrant" / (n + ".py")).read_bytes()).hexdigest() for n in order}
    missing = [n for n in order if "SOURCES[\"" + n + "\"] = r'''" + src[n] + "'''" not in built
               or "\"warrant/" + n + ".py\": \"" + digest[n] + "\"" not in built]
    check("U36", SINGLE.read_text(encoding="utf-8") == built and {"engine", "jcs", "keys", "records", "store", "shapes", "verify"} <= set(order)
          and not missing,
          "warrant_verify.py is what tools/build_verify.py builds: every module `warrant verify` imports, byte for byte, with its digest", missing)

    def repeat(flags):
        out = []
        for argv, code, text, env in RUNS:
            p = subprocess.run([sys.executable, *flags, str(SINGLE), *argv], capture_output=True, check=False, env=dict(os.environ, **env))
            if (p.returncode, p.stdout) != (code, text):
                out.append((argv[-3:], code, p.returncode, p.stderr.decode()[-200:], p.stdout[:200]))
        return out
    probe = "import cryptography, sys; sys.stdout.write(cryptography.__name__)"
    has = {flags: subprocess.run([sys.executable, *flags.split(), "-c", probe], capture_output=True, check=False).stdout == b"cryptography"
           for flags in ("-I", "-I -S")}
    with_lib = repeat(["-I"])
    check("U37", has["-I"] and not with_lib and len(RUNS) >= 60,
          f"the one file, with the cryptography library: the same bytes and exit status as `warrant verify` on each of {len(RUNS)} runs", with_lib[:3])
    without = repeat(["-I", "-S"])
    check("U38", not has["-I -S"] and not without,
          f"the one file with the standard library alone (python3 -I -S: no cryptography to import): the same bytes and exit "
          f"status on each of {len(RUNS)} runs", without[:3])

    argv, code, text, env = RUNS[0]
    p = subprocess.run([sys.executable, "-m", "warrant", "verify", *argv], capture_output=True, check=False, cwd=ROOT)
    check("U39", (p.returncode, p.stdout) == (code, text) and code == 0, "`warrant verify` is the same command by the package's own door", p.stderr[-300:])

    work = Path(tempfile.mkdtemp(dir=TMP))
    held = Path(argv[0]).parent
    before = sorted(x.name for x in held.iterdir())
    for cmd in ([sys.executable, "-I", "-S", str(SINGLE)], [sys.executable, "-m", "warrant", "verify"]):
        subprocess.run([*cmd, *argv], capture_output=True, check=False, cwd=work, env=dict(os.environ, PYTHONPATH=str(ROOT)))
    check("U40", list(work.iterdir()) == [] and sorted(x.name for x in held.iterdir()) == before,
          "a run writes nothing: not where it runs, not beside the package", (list(work.iterdir()), before))


# ---------------------------------------------------------------- Ed25519 with the standard library alone

DRIVER = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("warrant_verify_file", sys.argv[1])
one = importlib.util.module_from_spec(spec)
spec.loader.exec_module(one)
one._signatures()
one._load()
import cryptography
keys = sys.modules["warrant.keys"]
rows = json.load(sys.stdin)
json.dump({"library": cryptography.__version__,
           "valid": [keys.verify(k, s, bytes.fromhex(m)) for k, s, m in rows]}, sys.stdout)
"""


def pure(public_hex, sig_hex, message):
    """warrant/keys.py's verify, over the one file's Ed25519 instead of the library's."""
    if not (S.hex64(public_hex) and S.hex128(sig_hex)):
        return False
    raw = bytes.fromhex(public_hex)
    return not K.weak_public_key(raw) and SINGLE_SOURCE.ed25519_verify(raw, bytes.fromhex(sig_hex), message)


def signature_cases():
    pack = json.loads((ROOT / "third_party" / "primitives" / "vectors" / "verify-sig.json").read_text())["vectors"]
    vectors = [(v["id"], v["input"]["key"], v["input"]["sig"], v["input"]["warrant_id"], v["expect"]["valid"])
               for v in pack if v["input"].get("alg", "ed25519") == "ed25519"]
    edge = json.loads((ROOT / "tests" / "vectors" / "ed25519-edge.json").read_text())["vectors"]
    vectors += [(v["why"][:40], v["key"], v["sig"], v["warrant_id"], v["valid"]) for v in edge]
    rows = [(k, s, K.sig_message(i).hex()) for _, k, s, i, _ in vectors]
    p = subprocess.run([sys.executable, "-I", "-S", "-c", DRIVER, str(SINGLE)], input=json.dumps(rows).encode(), capture_output=True, check=False)
    got = json.loads(p.stdout) if p.returncode == 0 else {}
    wrong = [v[0] for v, valid in zip(vectors, got.get("valid", [])) if valid != v[4]]
    here = [v[0] for v in vectors if pure(v[1], v[2], K.sig_message(v[3])) != v[4]]
    check("U41", got.get("library") == "none: the standard library" and len(got.get("valid", [])) == len(vectors) and len(edge) == 5
          and len(vectors) >= 30 and not wrong and not here and sum(v[4] for v in vectors) == 6,
          f"the one file's Ed25519, with no cryptography library: the {len(vectors) - 5} Ed25519 vectors of the primitives pack (the "
          "small-order and non-canonical keys among them) and the five cofactorless edge signatures", (wrong, here, p.stderr[-300:]))

    rng = random.Random(20261110)
    order = 2**252 + 27742317777372353535851937790883648493
    cases = []
    for n in range(48):
        seed = rng.randbytes(32)
        key = K.Key.from_seed_hex(seed.hex())
        msg = rng.randbytes(rng.randrange(0, 96))
        sig = bytes.fromhex(key.sign(msg))
        pub = bytes.fromhex(key.public)
        cases.append(("valid", pub, sig, msg))
        for part, data in (("sig", sig), ("key", pub), ("msg", msg or b"\0")):
            i = rng.randrange(len(data) * 8)
            bent = bytes(b ^ (1 << (i % 8)) if j == i // 8 else b for j, b in enumerate(data))
            cases.append((f"one bit of the {part}", bent if part == "key" else pub, bent if part == "sig" else sig,
                          bent if part == "msg" else msg))
        s = int.from_bytes(sig[32:], "little")
        if s + order < 2**256:
            cases.append(("S + L", pub, sig[:32] + (s + order).to_bytes(32, "little"), msg))
        cases.append(("a random signature", pub, rng.randbytes(64), msg))
        cases.append(("a random key", rng.randbytes(32), sig, msg))
        h = hashlib.sha512(seed).digest()
        a = (int.from_bytes(h[:32], "little") & ((1 << 254) - 8)) | (1 << 254)
        for name, r_bytes in (("R the identity, S = h*a", (1).to_bytes(32, "little")),
                              ("R the identity written as y = p + 1", (2**255 - 18).to_bytes(32, "little")),
                              ("R of order two, S = h*a", (2**255 - 20).to_bytes(32, "little"))):
            k = int.from_bytes(hashlib.sha512(r_bytes + pub + msg).digest(), "little") % order
            cases.append((name, pub, r_bytes + (k * a % order).to_bytes(32, "little"), msg))
    differ, yes = [], {}
    for name, pub, sig, msg in cases:
        lib, mine = K.verify(pub.hex(), sig.hex(), msg), pure(pub.hex(), sig.hex(), msg)
        yes[name] = yes.get(name, 0) + lib
        if lib != mine:
            differ.append((name, pub.hex(), sig.hex(), msg.hex(), lib, mine))
    check("U42", not differ and yes.get("valid") == 48 and yes.get("R the identity, S = h*a") == 48 and yes.get("S + L") == 0
          and yes.get("R the identity written as y = p + 1") == 0 and yes.get("one bit of the sig") == 0 and len(cases) >= 450,
          f"the one file's Ed25519 and the cryptography library agree on {len(cases)} signatures made here: valid ones, one bit "
          "changed in the signature, key or message, S + L, a small-order R that the cofactorless equation accepts and its "
          "non-canonical spelling that it refuses", (differ[:2], yes))


def merkle_cases():
    """warrant.merkle: the roots of a store and the proofs a reader checks against a root alone (stage 3)."""
    rnd = random.Random(7)
    ok = True
    for n in list(range(0, 18)) + [33, 64, 100]:
        leaves = [bytes(rnd.getrandbits(8) for _ in range(32)) for _ in range(n)]
        r = M.root(leaves)
        for i in range(n):
            ok &= M.included(r, n, i, leaves[i], M.path(leaves, i))
            ok &= not M.included(r, n, i, leaves[i][::-1], M.path(leaves, i)) or leaves[i] == leaves[i][::-1]
            ok &= n < 2 or not M.included(r, n, (i + 1) % n, leaves[i], M.path(leaves, i))
    one = [b"x" * 32]
    ok &= M.included(M.root(one), 1, 0, one[0], []) and not M.included(M.root(one), True, 0, one[0], [])   # a size is an int, not a bool
    check("WT1 every leaf of a tree of 0 to 100 leaves is proved at its index by its audit path, and the same path "
          "proves no other bytes and no other index (RFC 9162 hashing; the empty tree's root is SHA-256 of nothing)",
          ok and M.root([]) == hashlib.sha256(b"").hexdigest() and M.root([b""]) == hashlib.sha256(b"\x00").hexdigest())
    r = Repo()
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=o)
    a = r.attest("bob", d)
    c = r.put("bob", "challenge", {"target": d, "statement": "no"}, refs=[d])
    for k in range(6):                                   # more targets, so d's leaf has neighbours on both sides
        x = r.entity("alice", "obligation@1", {"state": "open", "statement": f"t{k}", "serves": []})
        r.attest("bob", x)
    snap = r.store.snapshot()
    roots = M.roots(snap)
    said = M.check(M.prove_said(snap, d), roots["index"])
    keys = [t for t, _ in M.index_entries(snap)]
    p = keys.index(d)
    near = lambda j: M.prove_said(snap, keys[j])["in"]
    skip = dict(M.prove_said(snap, d), **{"in": None, "before": near(p - 1) if p > 0 else None,
                                          "after": near(p + 1) if p + 1 < len(keys) else None})
    above = dict(M.prove_said(snap, d), **{"in": None, "before": near(p + 1), "after": near(p + 2)}) if p + 2 < len(keys) \
        else dict(M.prove_said(snap, d), **{"in": None, "before": near(p - 2), "after": near(p - 1)})
    none = M.check(M.prove_said(snap, o), roots["index"])
    rec_in, rec_out = M.check(M.prove_record(snap, d), roots["records"]), M.check(M.prove_record(snap, "f" * 64), roots["records"])
    forged = dict(M.prove_said(snap, d), **{"in": None, "before": None, "after": M.prove_said(snap, d)["in"]})
    other = M.check(M.prove_said(snap, d), "0" * 64)
    low, high = M.prove_said(snap, "0" * 64), M.prove_said(snap, "f" * 64)
    ends = (M.check(low, roots["index"]) == (True, []) and low["before"] is None and low["after"]["i"] == 0
            and M.check(high, roots["index"]) == (True, []) and high["after"] is None and high["before"]["i"] == len(keys) - 1)
    not_first = dict(low, after=near(1))                 # "below the first leaf", shown with the second one
    not_last = dict(high, before=near(len(keys) - 2))    # "above the last leaf", shown with the one before it
    lied = M.prove_said(snap, d)
    lied["in"]["said"] = [x for x in lied["in"]["said"] if x[1] != c]   # the leaf's bytes kept, its list edited
    check("WT2 the reverse index's leaf for a version says every attest and challenge against it; a version nothing "
          "targets is proved absent by its neighbours; a record is proved in or out of the records tree; a leaf passed "
          "off as a neighbour of itself, neighbours that skip its leaf (not adjacent), two on the same side of it, a list that is not the "
          "one the leaf's digest names, a key below the first leaf or above the last shown by a leaf that is not the "
          "first or the last, or a proof against another root, proves nothing; at the ends the one neighbour does",
          said == (True, sorted([["attest", a], ["challenge", c]])) and none == (True, []) and rec_in == (True, True)
          and rec_out == (True, False) and M.check(forged, roots["index"])[0] is False and other[0] is False
          and 0 < p < len(keys) - 1 and M.check(skip, roots["index"])[0] is False and M.check(above, roots["index"])[0] is False
          and M.check(lied, roots["index"])[0] is False and M.check(M.prove_said(snap, d), roots["index"], len(keys) + 1)[0] is False
          and ends and M.check(not_first, roots["index"])[0] is False and M.check(not_last, roots["index"])[0] is False,
          (said, none, rec_in, rec_out, other, p, len(keys)))


def witness_repo():
    """A repository whose profile names carol `witness`: the snapshot@1 schema, a closed obligation accepted by bob and
    challenged by him, carol's first snapshot. (repo, d, challenge, snapshot, trust, profile)."""
    r = Repo(roles=dict(ROLES, witness=["carol"]), base=TMP, git_init=True)
    r.put("alice", "schema", SN.SCHEMA)
    o = r.entity("alice", "obligation@1", {"state": "open", "statement": "s", "serves": []})
    d = r.entity("alice", "obligation@1", {"state": "done", "statement": "s", "serves": []}, lineage=o)
    r.attest("bob", d)
    c = r.put("bob", "challenge", {"target": d, "statement": "no"}, refs=[d])
    for k in range(5):                                   # other targets: the index has leaves on both sides of d's
        x = r.entity("alice", "obligation@1", {"state": "open", "statement": f"t{k}", "serves": []})
        r.attest("bob", x)
    r.commit("the store")
    s1 = SN.witness(RP.Repo(r.root), "carol", KEYS["carol"])
    r.commit("carol witnesses it")
    cfg = json.loads((r.dot / "v3.json").read_text())
    return r, d, c, s1, cfg["trust"], cfg["profile"]


def package_of(r, roots, drop=()):
    lines = [x for x in (r.dot / "records.jsonl").read_text().splitlines() if R.rid(json.loads(x)["record"]) not in drop]
    return json.dumps({"warrant": "package/3", "roots": roots, "lines": lines, "blobs": {}}).encode()


def witness_cases():
    r, d, c, s1, T, Pf = witness_repo()
    rp = RP.Repo(r.root)
    rep = rp.report()
    o2 = r.entity("alice", "obligation@1", {"state": "open", "statement": "t", "serves": []})
    r.commit("one more record")
    s2 = SN.witness(rp, "carol", KEYS["carol"])
    r.commit("carol again")
    rep = rp.report()
    lines = (r.dot / "records.jsonl").read_bytes().splitlines(True)
    (r.dot / "records.jsonl").write_bytes(b"".join(x for x in lines if R.rid(json.loads(x)["record"]) != o2))
    r.commit("a record dropped")
    shrank = refused_code(lambda: SN.witness(rp, "carol", KEYS["carol"]))
    spoil = lambda x: (lambda env: json.dumps(dict(env, sig=dict(env["sig"], ed25519=("0" if env["sig"]["ed25519"][0] != "0" else "1")
                                                               + env["sig"]["ed25519"][1:])), separators=(",", ":")).encode() + b"\n")(json.loads(x))
    (r.dot / "records.jsonl").write_bytes(b"".join(spoil(x) if R.rid(json.loads(x)["record"]) == o2 else x for x in lines))
    r.commit("a record's signature spoiled")
    spoiled = refused_code(lambda: SN.witness(rp, "carol", KEYS["carol"]))
    (r.dot / "records.jsonl").write_bytes(b"".join(lines))
    r.commit("restored")
    check("WT3 a witness files its snapshots as one lineage (each names the one before), and refuses to sign a store "
          "that lacks a line of the store it witnessed last, or holds it with its signature spoiled (SNAPSHOT_SHRANK, read "
          "at that snapshot's commit, compared as lines, not ids)",
          rep["_recs"][s2]["lineage"] == s1 and rep["lineages"][s1]["leaf"] == s2 and shrank == "SNAPSHOT_SHRANK"
          and spoiled == "SNAPSHOT_SHRANK", (shrank, spoiled))
    w = SN.prove(rp, s2, [d])
    full = V.verify(package_of(r, [d]), T, Pf, witness=w)
    omit = V.verify(package_of(r, [d], drop={c}), T, Pf, witness=w)
    nobody = V.verify(package_of(r, [d]), T, dict(Pf, roles={k: v for k, v in Pf["roles"].items() if k != "witness"}), witness=w)
    check("WT4 with a witness, the answer's `absence` holds when the package has every attest and challenge the "
          "witnessed store holds against the roots' frame, and names what it leaves out otherwise (that package is not "
          "relied on); a witness the receiver's profile does not name counts for nothing; completeness stays UNATTESTED",
          full["absence"]["holds"] and full["absence"]["in"] == rep["_recs"][s2]["body"]["index"]
          and omit["absence"]["missing"] == [c] and not omit["rely"] and not nobody["absence"]["holds"]
          and full["completeness"]["attested"] == "UNATTESTED", (full["absence"], omit["absence"], nobody["absence"]))
    pkg_lines = lambda edit: json.dumps({"warrant": "package/3", "roots": [d], "lines": [
        edit(x) for x in (r.dot / "records.jsonl").read_text().splitlines()], "blobs": {}}).encode()
    def spoil_sig(x):
        env = json.loads(x)
        if R.rid(env["record"]) != c:
            return x
        e = env["sig"]["ed25519"]
        return json.dumps(dict(env, sig=dict(env["sig"], ed25519=("0" if e[0] != "0" else "1") + e[1:])), separators=(",", ":"))
    def resign(x):
        env = json.loads(x)
        if R.rid(env["record"]) != c:
            return x
        k = K.Key.from_seed_hex("ab" * 32)
        return C.canon({"record": env["record"], "sig": {"key": K.key_id(k.public), "ed25519": k.sign(R.SIG_DOMAIN + bytes.fromhex(c))}}).decode()
    spoiled = V.verify(pkg_lines(spoil_sig), T, Pf, witness=w)
    resigned = V.verify(pkg_lines(resign), T, Pf, witness=w)
    narrow = dict(T, keys={k: v for k, v in T["keys"].items() if k != "bob"})
    unbound = V.verify(package_of(r, [d]), narrow, Pf, witness=w)
    check("WT7 in the package means admitted by its assessment: the challenge kept with its signature spoiled, or signed "
          "again under another key while this receiver binds its actor, is missing, and the package is not relied on; one "
          "of an actor this receiver binds no key to is `uncounted` (its signature cannot be checked here), said apart, never silent "
          "(the analysis session on #393: a spoiled signature read as present, and the package was relied on)",
          spoiled["absence"]["missing"] == [c] and not spoiled["rely"] and resigned["absence"]["missing"] == [c]
          and not resigned["rely"] and c in unbound["absence"]["uncounted"] and c not in unbound["absence"]["missing"]
          and any(x.startswith("absence:") and "binds no key" in x for x in unbound["not_established"]),
          (spoiled["absence"], resigned["absence"], unbound["absence"]))
    acc = next(i for i, x in rep["_recs"].items() if x["kind"] == "attest" and x["body"].get("target") == d and x["actor"] == "bob")
    on_acc = r.put("eve", "challenge", {"target": acc, "statement": "this acceptance is wrong"}, refs=[acc])
    r.commit("a challenge against the acceptance")
    s3 = SN.witness(rp, "carol", KEYS["carol"])
    r.commit("carol witnesses it")
    w3 = SN.prove(rp, s3, [d])
    left = V.verify(package_of(r, [d], drop={on_acc}), T, Pf, witness=w3)
    whole = V.verify(package_of(r, [d]), T, Pf, witness=w3)
    check("WT8 a challenge against an acceptance of the root (the frame's second step) left out of the package is missing "
          "too, and the package with it holds", left["absence"]["missing"] == [on_acc] and not left["absence"]["holds"]
          and whole["absence"]["holds"], (left["absence"], whole["absence"]))
    good = SN.check_snapshot(rp, s3)
    forged = r.put("carol", "entity", dict(rep["_recs"][s1]["body"], index="0" * 64, commit=git(r.root, "rev-parse", "HEAD")),
                   SN.NAME, lineage=s3)
    r.commit("a snapshot whose index root is not the store's")
    bad = SN.check_snapshot(rp, forged)
    check("WT9 `snapshot check` makes a snapshot's roots again from the store at its commit: a true one holds, one naming "
          "another index root does not (how a tree built out of order is caught: by anyone with the clone)",
          good == [] and any(k == "index" for k, _ in bad), (good, bad))
    hidden = json.loads(json.dumps(w))
    leaf = hidden["said"]["proofs"][d]["in"]
    leaf["said"] = [x for x in leaf["said"] if x[1] != c]                # the challenge taken out of d's leaf
    edited = V.verify(package_of(r, [d], drop={c}), T, Pf, witness=hidden)
    check("WT6 the proofs are read at the root and size the witness signed: a leaf edited to drop a challenge (so that "
          "a package leaving it out would pass) proves nothing, and the package is not relied on",
          d in edited["absence"]["unproved"] and not edited["absence"]["holds"] and not edited["rely"], edited["absence"])
    back = V.verify(package_of(r, [d]), T, Pf, witness=SN.prove(rp, s1, [d]), extends=s3)
    ahead = V.verify(package_of(r, [d]), T, Pf, witness=SN.prove(rp, s3, [d]), extends=s1)
    b = rep["_recs"][s2]["body"]
    r.put("carol", "entity", dict(b, commit=git(r.root, "rev-parse", "HEAD")), SN.NAME, lineage=s1)
    r.commit("a second snapshot after s1: two histories")
    w2 = SN.prove(rp, s2, [d])
    pkg = Path(TMP) / "wt.pkg.json"
    pkg.write_bytes(package_of(r, [d]))
    (Path(TMP) / "wt.witness.json").write_text(json.dumps(w2))
    (Path(TMP) / "wt.v3.json").write_text(json.dumps({"trust": T, "profile": Pf}))
    with contextlib.redirect_stdout(io.StringIO()):
        code = V.main([str(pkg), "--config", str(Path(TMP) / "wt.v3.json"), "--witness", str(Path(TMP) / "wt.witness.json")])
    check("WT5 --extends refuses a snapshot that does not descend from the one held (a rollback) and takes one that "
          "does; two snapshots of one witness after the same one are equivocation, exit 4",
          not back["absence"]["holds"] and "ROLLBACK" in back["absence"]["why"] and ahead["absence"]["holds"] and code == 4,
          (back["absence"]["why"], ahead["absence"]["why"], code))


def refused_code(fn):
    try:
        fn()
        return None
    except RP.Failed as e:
        return e.code


def main():
    try:
        src, pkg, d = reliance_cases()
        more_reliance_cases()
        pin_cases()
        refusal_cases(src, pkg, d)
        shape_cases()
        single_cases()
        signature_cases()
        merkle_cases()
        witness_cases()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    return finish("verify_test")


if __name__ == "__main__":
    sys.exit(main())
