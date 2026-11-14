"""`warrant verify PACKAGE`: may this receiver rely on what it was handed? (docs/VERIFY.md)

One party hands another a `package/3` (the agent interface's `handoff export`, docs/V3.md §13): the records a result
rests on and the verdicts on them. This assesses the package alone, under the receiver's own trust and profile, with
no store, no workspace and no agent configuration, and writes nothing.

    warrant verify PACKAGE (--trust T --profile P | --config V3JSON) [--as-of N] [--checkout DIR]
                           [--require ROOT ...] [--max-bytes N]

The answer is one line of canonical JSON on standard output, and the exit status is the gate:

    0   every root asked for is one this receiver may rely on now;
    1   otherwise: a root is not relied on, or the package was refused (the answer says which);
    2   the command line, or a file of the receiver's own that it names, cannot be read;
    3   an error of this verifier itself, never the code of a refusal;
    4   with --witness: the witness showed two histories (two of its snapshots after the same one).

With --witness FILE (a `witness/1`: snapshot@1 lines of one witness and warrant.merkle proofs, warrant.snapshot
prove), the answer has `absence`: against the reverse index root R of the snapshot it uses, signed by an actor this
receiver's trust binds and its profile names `witness`, every attest and challenge that store held against an id of the
asked roots' frame (graph.frame) is in the package, or what is missing. `completeness` stays UNATTESTED: `absence`
says what was not in that root, never that it is nowhere. A package that leaves out what the witnessed store holds is
not relied on. With --extends HELD (a snapshot id the receiver accepted before), the snapshot used must descend from
it in the witness's lineage: an older one, or one on another branch, is a rollback, refused.

A root is a record id. It is relied on when it is the effective version of its lineage (docs/V3.md §3: a lineage
that forks has none, and a version whose guard waits is not it), no counted challenge in the package stands against
it, and, with --checkout, the files its acceptances name are still those bytes in that checkout's HEAD (warrant.pins;
without a checkout they are listed, not checked). The roots are --require's, else the ones the package names.

The answer keeps five things apart and never folds them into one word: `integrity` (the bytes are the bytes their
names hash), `authenticity` (whose signatures verify under the receiver's trust), `completeness` (what the slice
does not hold: always something, since its sender chose it), `execution` (the schemas and rules as this receiver
counts them) and, per root, the right to rely. `established` and `not_established` say the same in sentences,
built from what this run found.

The agent interface's `handoff` reads a package through `unpack`, `snapshot` and `describe` here, so there is one
reader of the format. warrant_verify.py at the repository's root is this module and the ones it imports as one
standard-library file (tools/build_verify.py)."""
import argparse
import base64
import re
import hashlib
import json
import subprocess
import sys

from . import engine as E
from . import graph as G
from . import jcs as C
from . import merkle as M
from . import pins as P
from . import records as R
from . import shapes as S
from .store import Refused, Snapshot

PACKAGE = "package/3"
ANSWER = "verify/3"
MAX_BYTES = 64 << 20
MEMBERS = {"warrant", "roots", "lines", "blobs"}
# Why a root is not relied on: it is relied on only when none holds. A reliance the engine gives an effective version
# other than ELIGIBLE is passed on under the engine's own word (today CHALLENGED), so a new one fails the gate too.
WHY_NOT = ("UNAVAILABLE", "NOT_A_VERSION", "NOT_EFFECTIVE", "CHALLENGED", "STALE", "PINS_NOT_CHECKED")
# Why a package is refused before anything is assessed, each with its one sentence (no reader's own wording: another
# implementation gives the same bytes).
REFUSALS = {
    "TOO_LARGE": "the package is larger than {limit} bytes",
    "NOT_JSON": "the package is not UTF-8 JSON, or an object in it names a member twice",
    "NOT_A_PACKAGE": "a package is {{warrant: " + PACKAGE + ", roots, lines, blobs}}",
    "BAD_BASE64": "a blob is not base64",
    "BAD_BLOB": "a blob is not named by its hash",
    "BAD_LINE": "{n} line(s) of the package are not records",
    "LIMITS": "the package is beyond the engine's limits",
}


# A blob in a package: base64 of RFC 4648 §4 in its one padded form, read by this rule and not by binascii, whose strict mode
# takes and words otherwise from one Python version to the next (R-INTERPRETER: 3.11 decoded "YWJj=", 3.13 refuses it).
_BASE64 = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?")


class Refusal(ValueError):
    """A package that is not read: `code` (REFUSALS), its sentence, and `detail`, a reader's own words for a caller
    that wants them (never in an answer)."""

    def __init__(self, code, detail="", **words):
        super().__init__(REFUSALS[code].format(**words))
        self.code, self.detail = code, detail


class Usage(Exception):
    """The command line, or a file of the receiver's own, cannot be read: exit 2."""


# ---------------------------------------------------------------- the format

def read_json(raw):
    """The JSON value in `raw`, read one way or refused: an object naming a member twice has two readings (Python
    keeps the last value, other readers the first). A float, NaN or Infinity is read and then fits no shape a
    package, a trust or a profile has; a record's line is read by the canonical reader (warrant.jcs), which takes
    neither."""
    def one(pairs):
        d = dict(pairs)
        if len(d) != len(pairs):
            raise ValueError("a member is named twice")
        return d
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=one)
    except (ValueError, RecursionError) as e:
        raise Refusal("NOT_JSON", f"{type(e).__name__}: {e}") from None


def unpack(pkg, limit=None):
    """(lines, blobs) of a package object: each line's bytes with its newline, {hash: bytes}. Refused: another shape,
    a blob that is not base64 or not named by its hash, more than `limit` bytes of lines and blobs (None: the caller
    bounded the package's own bytes already)."""
    if not (isinstance(pkg, dict) and pkg.get("warrant") == PACKAGE and set(pkg) == MEMBERS
            and isinstance(pkg["lines"], list) and all(isinstance(x, str) for x in pkg["lines"])
            and isinstance(pkg["blobs"], dict) and isinstance(pkg["roots"], list) and all(S.hex64(r) for r in pkg["roots"])):
        raise Refusal("NOT_A_PACKAGE")
    if not all(isinstance(b, str) and _BASE64.fullmatch(b) for b in pkg["blobs"].values()):
        raise Refusal("BAD_BASE64")
    blobs = {h: base64.b64decode(b) for h, b in pkg["blobs"].items()}
    # A lone surrogate is not UTF-8: its bytes stay what no reader takes for a record (snapshot counts the line).
    lines = [x.encode("utf-8", "surrogatepass") + b"\n" for x in pkg["lines"]]
    if limit is not None and sum(map(len, lines)) + sum(map(len, blobs.values())) > limit:
        raise Refusal("TOO_LARGE", limit=limit)
    if not all(S.hex64(h) and C.digest(b) == h for h, b in blobs.items()):
        raise Refusal("BAD_BLOB")
    return lines, blobs


def snapshot(lines, blobs):
    """The package as one read (store.Snapshot), refused when a line is not a record. A line holds one newline, its
    last byte: a second one would be the same record under another digest."""
    snap = Snapshot(lines, blobs)
    extra = [x for x in snap.raw if x.count(b"\n") != 1 and hashlib.sha256(x).hexdigest() not in snap.rejected]
    if snap.rejected or extra:
        raise Refusal("BAD_LINE", n=len(snap.rejected) + len(extra))
    return snap


def describe(rep, ids):
    """{id: its node, lineage, guard and challenge in report `rep`} (graph.describe); an id the report has no record
    of reads `unavailable`, never as absent from the world."""
    nodes, _, _ = G.index(rep)
    return {i: G.describe(rep, nodes, i) for i in ids}


# ---------------------------------------------------------------- the answer

def verify(raw, trust, profile, as_of=None, require=(), checkout=None, limit=MAX_BYTES, witness=None, extends=None):
    """The answer (a JSON object, module docstring) for the bytes of a package file. `require`: the roots the receiver
    asks about (none: the package's own); `checkout`: what read_checkout gave, or None."""
    for why in (E.trust_problem(trust), E.profile_problem(profile)):
        if why:
            raise Usage(why)
    receiver = {"trust": C.doc_id(trust), "profile": C.doc_id(profile), "as_of": as_of}
    asked = {"by": "receiver" if require else "package", "roots": sorted(set(require))}
    try:
        if len(raw) > limit:
            raise Refusal("TOO_LARGE", limit=limit)
        pkg = read_json(raw)
        lines, blobs = unpack(pkg)                       # what a package holds is smaller than its file
        snap = snapshot(lines, blobs)
        try:
            view = E.View(snap, trust, profile, as_of)
        except (Refused, R.Invalid) as e:
            raise Refusal("LIMITS", str(e)) from None
    except Refusal as e:
        return _refused(e, receiver, asked)
    except Refused as e:                                 # the snapshot beyond the engine's limits
        return _refused(Refusal("LIMITS", str(e)), receiver, asked)
    if not require:
        asked["roots"] = sorted(set(pkg["roots"]))
    rep = view.report()
    ans = _answer(snap, view, rep, dict(receiver, as_of=view.as_of), asked, checkout)
    if witness is not None:
        ans["absence"] = absence(witness, snap, rep, asked["roots"], trust, profile, extends)
        ans["rely"] = ans["rely"] and ans["absence"]["holds"]
        ans["established"], ans["not_established"] = _sentences(ans)
    return ans


WITNESS, WITNESS_ROLE, SNAPSHOT = "witness/1", "witness", "snapshot@1"


def _witness_lines(doc):
    """{id: record} of a witness/1 document's lines, or a Refusal."""
    if not (isinstance(doc, dict) and set(doc) == {"warrant", "lines", "use", "said"} and doc["warrant"] == WITNESS
            and isinstance(doc["lines"], list) and S.hex64(doc["use"]) and isinstance(doc["said"], dict)):
        raise Refusal("WITNESS_SHAPE", "a witness/1 is {warrant, lines, use, said}")
    out = {}
    for ln in doc["lines"]:
        if not (isinstance(ln, dict) and set(ln) == {"record", "sig"}):
            raise Refusal("WITNESS_SHAPE", "a line is {record, sig}")
        try:
            R.check(ln["record"])
        except R.Invalid as e:
            raise Refusal("WITNESS_SHAPE", f"a line's record: {e}") from None
        out[R.rid(ln["record"])] = ln
    return out


def absence(doc, snap, rep, roots, trust, profile, extends=None):
    """The `absence` of an answer (module docstring): {holds, in, records, snapshot, witnessed_by, commit, frame,
    missing, unproved, equivocation, why}."""
    out = {"holds": False, "in": None, "records": None, "snapshot": None, "witnessed_by": None, "commit": None,
           "frame": 0, "missing": [], "uncounted": [], "unproved": [], "equivocation": [], "why": None}
    try:
        lines = _witness_lines(doc)
    except Refusal as e:
        return dict(out, why=f"{e.code}: {e}")
    use = lines.get(doc["use"])
    if use is None:
        return dict(out, why="the snapshot it uses is not among its lines")
    r = use["record"]
    actor, b = r["actor"], r["body"]
    signed = lambda ln: bool(ln["sig"]) and any(R.verifies(R.rid(ln["record"]), ln["sig"], k)
                                                for k in trust.get("keys", {}).get(ln["record"]["actor"], []))
    if not (r["kind"] == "entity" and r["schema"] == SNAPSHOT and signed(use)):
        return dict(out, why=f"{doc['use'][:12]} is no snapshot@1 signed with a key this receiver binds to {actor!r}")
    if actor not in (profile.get("roles", {}).get(WITNESS_ROLE) or []):
        return dict(out, why=f"{actor!r} holds no `{WITNESS_ROLE}` role in this receiver's profile")
    if not (isinstance(b, dict) and S.hex64(b.get("records")) and S.hex64(b.get("index"))):
        return dict(out, why="the snapshot names no records and index roots")
    out.update(**{"in": b["index"], "records": b["records"], "snapshot": doc["use"], "witnessed_by": actor,
                  "commit": b.get("commit")})
    mine = {i: ln["record"] for i, ln in lines.items() if ln["record"]["actor"] == actor
            and ln["record"]["schema"] == SNAPSHOT and ln["record"]["kind"] == "entity" and signed(ln)}
    after = {}
    for i, x in mine.items():
        after.setdefault(x.get("lineage"), []).append(i)
    out["equivocation"] = sorted(sorted(v) for v in after.values() if len(v) > 1)
    if out["equivocation"]:
        return dict(out, why=f"{actor} showed two histories: two of its snapshots follow the same one")
    if extends is not None:
        chain, x = [], doc["use"]
        while x in mine:
            chain.append(x)
            x = mine[x].get("lineage")
        if extends not in chain:
            return dict(out, why=f"ROLLBACK: {doc['use'][:12]} does not descend from {extends[:12]}, the snapshot "
                                 "held: an older one, or one on another branch")
    root_of = {v: L for L, lin in rep["lineages"].items() for v in lin["versions"]}
    ids = G.frame(rep, sorted({root_of.get(i, i) for i in roots}))
    ids = sorted(set(ids) | {i for i in roots if i in snap.lines})
    out["frame"] = len(ids)
    size = (b.get("size") or {}).get("index")
    # In the package is what its assessment admitted, not a line with that id: a line whose signature does not verify is
    # left out by the engine, and counted here as missing (the analysis session on #393: a challenge kept in the
    # package with its signature spoiled read as present). A line signed under a key this receiver's trust does not bind
    # is in the package and counted for nothing here: `uncounted`, said, never folded into either answer.
    # The split is by the actor: one this receiver binds keys to (or a challenge's own named key), whose line it did not
    # admit, is missing: its signature was not delivered, and a line signed again under another key is no less missing.
    # A line of an actor it binds no key to is uncounted: present, and a signature this receiver cannot check (a line
    # names its key by id, not the key).
    admitted = {n[0] for n in rep["graph"]["nodes"]}
    def own_key(x):
        envs = snap.lines.get(x, [])
        return bool(envs) and envs[0]["record"]["actor"] not in trust.get("keys", {}) and not R.named_key(envs[0]["record"])
    for i in ids:
        # read at the witness's root and size, as signed: RFC 9162 binds the size through the root, not through a
        # leaf's path, and the neighbours of an absence are adjacent only in a tree of that size
        proof = M.unpack(doc["said"], i, b["index"], size) if type(size) is int else None
        holds, said = M.check(proof, b["index"], size) if proof else (False, None)
        if not holds:
            out["unproved"].append(i)
            continue
        out["missing"] += [x for _, x in said if x not in admitted and not own_key(x)]
        out["uncounted"] += [x for _, x in said if x not in admitted and own_key(x)]
    out["missing"], out["uncounted"] = sorted(set(out["missing"])), sorted(set(out["uncounted"]))
    out["holds"] = not out["unproved"] and not out["missing"]
    if not out["holds"]:
        out["why"] = (f"{len(out['missing'])} record(s) the witnessed store holds against the frame are not in the "
                      f"package" if out["missing"] else f"{len(out['unproved'])} id(s) of the frame have no proof against {b['index'][:12]}")
    return out


def _refused(e, receiver, asked):
    return {"warrant": ANSWER, "rely": False, "refused": {"code": e.code, "why": str(e)}, "package": None,
            "receiver": receiver, "asked": asked, "checkout": None, "integrity": None, "authenticity": None,
            "completeness": None, "execution": None, "roots": {}, "established": [],
            "not_established": [f"integrity: the package was refused and nothing in it was assessed: {e}"]}


def _answer(snap, view, rep, receiver, asked, checkout):
    nodes, out, _ = G.index(rep)
    roots = {i: _root(snap, view, rep, nodes, out, i, checkout) for i in asked["roots"]}
    code = {i: w.split(":")[0] for i, w in rep["rejected"].items()}
    by = {}
    for i, a in sorted(view.vouched_by.items()):
        by[a] = by.get(a, 0) + 1
    named = sum(1 for i, r in view.recs.items() if view.basis[i] == "SIGNED" and R.named_key(r))
    q = view.quorum(E.SCHEMA_AUTHOR)
    problems = sorted({(p[0], p[1]) for p in rep["problems"]})
    ans = {
        "warrant": ANSWER, "rely": bool(roots) and all(r["rely"] for r in roots.values()), "refused": None,
        "package": snap.digest, "receiver": receiver, "asked": asked,
        "checkout": None if checkout is None else {"tree": checkout["tree"]},
        "integrity": {"records": len(snap.lines), "blobs": len(snap.blobs),
                      "bytes": sum(map(len, snap.raw)) + sum(map(len, snap.blobs.values()))},
        "authenticity": {"signed": rep["basis"]["SIGNED"], "migrated": rep["basis"]["MIGRATED"], "named_keys": named,
                         "migrations": [{"attest": a, "actor": view.recs[a]["actor"], "records": n} for a, n in sorted(by.items())],
                         "rejected": {i: c for i, c in sorted(code.items()) if c != "INVALID"},
                         "duplicates": rep["duplicates"]},
        "completeness": {"attested": rep["completeness"], "later": rep["later"],
                         "unavailable": sorted({x for r in roots.values() for x in r["unavailable"]}),
                         "unanchored": len(rep["chains"]["unanchored"]), "chain_forks": len(rep["chains"]["forks"])},
        "execution": {"schemas": rep["schemas"], "quorum": q,
                      "schemas_pending": {i: p["name"] for i, p in sorted(rep["schemas_pending"].items())},
                      "invalid": sorted(i for i, c in code.items() if c == "INVALID"),
                      "problems": [list(p) for p in problems]},
        "roots": roots}
    ans["established"], ans["not_established"] = _sentences(ans)
    return ans


def _accepted(view, v, by):
    """The attests behind version v's met or waiting guard: those of the actors the engine counted (`by`, its
    accepted_by: docs/V3.md §6, rule 1) whose body has every member the guard matches, each with the roles of the
    guard its actor holds under the receiver's profile."""
    g = view.recs[v]["guard"]
    rows = []
    for a in view.attests.get(v, []) if g is not None else []:
        x = view.recs[a]
        if x["actor"] in by and all(x["body"].get(k) == w for k, w in g["match"].items()):
            rows.append({"attest": a, "actor": x["actor"], "roles": [role for role in g["roles"] if view.holds(x["actor"], role)]})
    return sorted(rows, key=lambda d: (d["actor"], d["attest"]))


def _rests(out, starts):
    """Every id reached from `starts` along the graph's dependency edges (graph.WALK), the starts left out."""
    seen, todo = set(starts), sorted(starts)
    while todo:
        for rel, nxt in out.get(todo.pop(), []):
            if rel in G.WALK and nxt not in seen:
                seen.add(nxt)
                todo.append(nxt)
    return seen - set(starts)


def _pins(view, v, accepted, checkout):
    """The files the acceptances behind version v name, each compared with the checkout's tree (warrant.pins):
    {verdict, acceptances}. NONE: no acceptance names files. NOT_CHECKED: some do and no tree was read. Else FRESH when
    the guard's quorum is still met by the actors that name no files or have an acceptance whose every file is those
    bytes (unchanged or moved), and STALE when it is not."""
    rows, fresh, pinning = [], set(), set()
    read = checkout is not None and checkout["tree"] is not None
    for a in accepted:
        b = view.recs[a["attest"]]["body"]
        files = b.get("files")
        if files is None:
            continue
        pinning.add(a["actor"])
        commit = b.get("commit") if S.hex_of(b.get("commit"), 40) or S.hex_of(b.get("commit"), 64) else None
        if P.unreadable(files):
            word, listed = "UNKNOWN", []
        elif not read:
            word, listed = "NOT_CHECKED", [{"path": p, "blob": x, "verdict": "NOT_CHECKED", "detail": ""} for p, x in sorted(files.items())]
        else:
            got = P.compare(checkout["root"], commit or "unknown", files, checkout["head"], checkout["where"], checkout["commit"])
            word, listed = P.verdict(got), [{"path": p, "blob": files[p], "verdict": w, "detail": d} for w, p, d in got]
        if word == "UNCHANGED":
            fresh.add(a["actor"])
        rows.append({"attest": a["attest"], "actor": a["actor"], "commit": commit, "verdict": word, "files": listed})
    if not rows:
        return {"verdict": "NONE", "acceptances": []}
    if not read:
        return {"verdict": "NOT_CHECKED", "acceptances": rows}
    still = fresh | ({a["actor"] for a in accepted} - pinning)
    return {"verdict": "FRESH" if len(still) >= view.recs[v]["guard"]["quorum"] else "STALE", "acceptances": rows}


def _root(snap, view, rep, nodes, out, i, checkout):
    n = G.describe(rep, nodes, i)
    kind = "blob" if n["kind"] == "unavailable" and i in snap.blobs else n["kind"]
    rejected = rep["rejected"].get(i)
    root = {"kind": kind, "schema": n.get("schema"), "actor": n.get("actor"), "at": n.get("at"), "basis": n.get("basis"),
            "rejected": rejected.split(":")[0] if rejected else None, "lineage": None, "guard": None, "accepted": [],
            "challenges": {}, "pins": {"verdict": "NONE", "acceptances": []}, "unavailable": []}
    why = []
    if kind == "unavailable":
        why.append("UNAVAILABLE")
    elif "lineage" not in n:
        why.append("NOT_A_VERSION")
        root["challenges"] = _challenges(view, rep, {i})
        root["unavailable"] = _missing(snap, view, out, {i})
    else:
        L = n["lineage"]["root"]
        lin, g = rep["lineages"][L], n["guard"]
        acc = _accepted(view, i, g["accepted_by"])
        pins = _pins(view, i, acc, checkout)
        root.update(guard=g, accepted=acc, pins=pins, challenges=_challenges(view, rep, set(lin["versions"])),
                    unavailable=_missing(snap, view, out, {i} | {a["attest"] for a in acc}),
                    lineage={"root": L, "state": lin["state"], "reliance": lin["reliance"], "verdict": lin["verdict"],
                             "leaf": lin["leaf"], "effective": lin["effective"], "forks": lin["forks"]})
        if lin["effective"] != i:
            why.append("NOT_EFFECTIVE")
        elif lin["reliance"] != "ELIGIBLE":
            why.append(lin["reliance"])
        if pins["verdict"] == "STALE":
            why.append("STALE")
            if not why[:-1]:
                root["lineage"]["reliance"] = "STALE"          # the receiver's tree read beside the package (docs/V3.md §15)
        if pins["verdict"] == "NOT_CHECKED" and checkout is not None:
            why.append("PINS_NOT_CHECKED")
    root["why_not"] = why
    root["rely"] = not why
    return root


def _challenges(view, rep, targets):
    return {c: dict(x, actor=view.recs[c]["actor"]) for c, x in sorted(rep["challenges"].items()) if x["target"] in targets}


def _missing(snap, view, out, starts):
    return sorted(x for x in _rests(out, starts) if x not in view.recs and x not in snap.blobs)


# ---------------------------------------------------------------- in sentences

def _n(n, one, many=None):
    return f"{n} {one if n == 1 else many or one + 's'}"


def _sentences(ans):
    """(established, not_established): each sentence names its dimension first and is built from what this run found.
    One sentence is always there: no package can show what its sender left out."""
    yes, no = [], []
    it, au, co, ex = ans["integrity"], ans["authenticity"], ans["completeness"], ans["execution"]
    tree = (ans["checkout"] or {}).get("tree")
    yes.append(f"integrity: {_n(it['records'], 'record')} and {_n(it['blobs'], 'blob')}, each named by the hash of its "
               f"bytes, checked here; together they are package {ans['package']}")
    bound = au["signed"] - au["named_keys"]
    if bound:
        yes.append(f"authenticity: {_n(bound, 'record')} signed with a key your trust binds to the record's actor; "
                   "each signature verified here")
    if au["named_keys"]:
        yes.append(f"authenticity: {_n(au['named_keys'], 'challenge')} signed with the key its actor names itself by; "
                   "the signature verified here, and no trust says whose key it is")
    for m in au["migrations"]:
        no.append(f"authenticity: {_n(m['records'], 'record')} unsigned, vouched for by migration {m['attest'][:12]} of "
                  f"{m['actor']}, a migrator in your profile: that actor's word, not the writers' signatures")
    if au["rejected"]:
        no.append(f"authenticity: {_n(len(au['rejected']), 'record')} with no signature that verifies under your trust "
                  "and no migration you accept: left out, counted for nothing")
    if ex["schemas"]:
        yes.append(f"execution: {_n(len(ex['schemas']), 'schema')} counted at your quorum of {ex['quorum']} "
                   f"schema/author: {', '.join(sorted(ex['schemas']))}")
    if ex["schemas_pending"]:
        no.append(f"execution: {_n(len(ex['schemas_pending']), 'schema')} short of your quorum of {ex['quorum']} "
                  f"schema/author, counted for nothing: {', '.join(sorted(ex['schemas_pending'].values()))}")
    if ex["invalid"]:
        no.append(f"execution: {_n(len(ex['invalid']), 'record')} that fit no schema you count: left out")
    if ex["problems"]:
        codes = sorted({p[0] for p in ex["problems"]})
        no.append(f"execution: the engine lists {_n(len(ex['problems']), 'problem')}: "
                  + ", ".join(f"{c} {sum(1 for p in ex['problems'] if p[0] == c)}" for c in codes))
    no.append("completeness: the package holds what its sender chose to include: a challenge or a later version it "
              "left out cannot be seen here")
    ab = ans.get("absence")
    if ab and ab["holds"]:
        yes.append(f"absence: every attest and challenge the store witnessed by {ab['witnessed_by']} at index root "
                   f"{ab['in'][:12]} (snapshot {ab['snapshot'][:12]}) holds against the {_n(ab['frame'], 'record')} of the "
                   "roots' frame is in the package; a statement about that root, not about every store")
    elif ab:
        no.append(f"absence: not shown: {ab['why']}")
    if ab and ab["uncounted"]:
        no.append(f"absence: {_n(len(ab['uncounted']), 'record')} the witness saw against the frame "
                  f"{'is' if len(ab['uncounted']) == 1 else 'are'} in the package, of an actor your trust binds no key "
                  "to: their signatures cannot be checked here and you count them for nothing; they are not hidden from you")
    if co["unavailable"]:
        no.append(f"completeness: {_n(len(co['unavailable']), 'record or blob', 'records or blobs')} that the roots rest "
                  "on, named and not in the package: " + ", ".join(x[:12] for x in co["unavailable"]))
    if co["unanchored"]:
        no.append(f"completeness: {_n(co['unanchored'], 'signed record')} naming an earlier record of its writer that "
                  "the package does not hold: the writers' own order is not witnessed here")
    if co["chain_forks"]:
        no.append(f"completeness: {_n(co['chain_forks'], 'writer')} with two records naming the same earlier one: that "
                  "writer's order forks")
    if co["later"]:
        no.append(f"completeness: {_n(co['later'], 'record')} dated after {ans['receiver']['as_of']}, left out of this view")
    if ans["asked"]["by"] == "package":
        no.append("reliance: the roots answered are the ones the package names; --require names the ones you ask about")
    if not ans["roots"]:
        no.append("reliance: no root is named, by --require or by the package: nothing was asked, nothing is relied on")
    for i, r in ans["roots"].items():
        _root_sentences(i, r, tree, ans["checkout"] is not None, yes, no)
    return yes, no


def _root_sentences(i, r, tree, asked_tree, yes, no):
    s, lin, pins = i[:12], r["lineage"], r["pins"]
    if lin and lin["effective"] == i:
        head = f"reliance: {s} ({r['schema']}, state {lin['state']}) is the effective version of its lineage"
        if r["guard"]["guard"] == E.MET:
            by = ", ".join(sorted({f"{a['actor']} ({', '.join(a['roles'])})" for a in r["accepted"]}))
            yes.append(f"{head}; its guard is met by {by}" if by else f"{head}; its guard asks for no attest")
        else:
            yes.append(f"{head}; it carries no guard and stands as filed by {r['actor']}"
                       + (", unsigned, on a migration's word" if r["basis"] == "MIGRATED" else ""))
        if not r["guard"]["challenged_by"]:
            yes.append(f"reliance: no challenge in the package stands against {s}")
    for a in pins["acceptances"]:
        files, who = _n(len(a["files"]), "file"), f"{a['attest'][:12]} by {a['actor']}"
        if a["verdict"] == "UNCHANGED":
            moved = sum(1 for f in a["files"] if f["verdict"] == "MOVED")
            yes.append(f"pins: {s}: the acceptance {who} names {files}, the same bytes in your tree {tree[:12]}"
                       + (f", {moved} at another path" if moved else ""))
        elif a["verdict"] == "CHANGED":
            other = _n(sum(1 for f in a["files"] if f["verdict"] not in P.FRESH), "file")
            no.append(f"pins: {s}: the acceptance {who} names {files}; {other} of them are other bytes in your tree {tree[:12]}")
        elif a["verdict"] == "UNKNOWN":
            no.append(f"pins: {s}: the acceptance {who} names its files in no form that can be compared")
        else:
            no.append(f"pins: {s}: the acceptance {who} names {files}; "
                      + ("git is not available here" if asked_tree else "no checkout was given")
                      + ", so whether they are still those bytes is not checked")
    if asked_tree and lin and pins["verdict"] == "NONE":
        no.append(f"pins: {s}: no acceptance behind it names files: nothing ties it to your tree")
    if r["rely"]:
        return
    cause = []
    if "NOT_EFFECTIVE" in r["why_not"]:
        if lin["verdict"] == "FORK":
            cause.append("its lineage forks and has no effective version")
        if r["guard"]["guard"] == E.PENDING:
            cause.append("its guard waits for " + " and ".join(r["guard"]["waiting"]))
        if lin["effective"]:
            cause.append(f"{lin['effective'][:12]} is the effective version of its lineage")
    words = {
        "UNAVAILABLE": "the package holds no admitted record of that id" + (f" (its line is {r['rejected']})" if r["rejected"] else ""),
        "NOT_A_VERSION": f"it is a record of kind {r['kind']} in no lineage",
        "NOT_EFFECTIVE": "; ".join(cause) or "its lineage has no effective version",
        "CHALLENGED": "a counted challenge stands against it: " + ", ".join(c[:12] for c in (r["guard"] or {}).get("challenged_by", [])),
        "STALE": "the files its acceptances name are no longer those bytes in your tree",
        "PINS_NOT_CHECKED": "the files its acceptances name were to be compared with your tree and could not be",
    }
    no.append(f"reliance: {s} is not relied on: " + "; ".join(words.get(w, f"its lineage reads {w}") for w in r["why_not"]))


# ---------------------------------------------------------------- the command

def read_checkout(d):
    """What the pins are compared with: HEAD's commit and tree in the Git checkout `d`, and {path: blob} of it; with no
    git to ask, a tree of None (the pins then read NOT_CHECKED, never fresh). A directory that is no checkout with a
    commit is the receiver's own mistake."""
    try:
        commit = P.git(d, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        head = P.blobs(d, commit)
        return {"root": d, "commit": commit, "tree": P.git(d, "rev-parse", f"{commit}^{{tree}}"), "head": head,
                "where": P.paths_of(head)}
    except subprocess.CalledProcessError:
        raise Usage(f"--checkout {d}: not a Git checkout with a commit") from None
    except OSError:
        return {"root": d, "commit": None, "tree": None, "head": None, "where": None}


def _own(path, flag):
    """A JSON file of the receiver's own."""
    try:
        with open(path, "rb") as f:  # NOSONAR S8707: a file of the receiver's own that its command line names, read as data
            return read_json(f.read())
    except OSError as e:
        raise Usage(f"{flag} {path}: {type(e).__name__}") from None
    except Refusal:
        raise Usage(f"{flag} {path}: not JSON that reads one way") from None


def _receiver(a):
    if a.config and not (a.trust or a.profile):
        doc = _own(a.config, "--config")
        if not (isinstance(doc, dict) and "trust" in doc and "profile" in doc):
            raise Usage(f"--config {a.config}: not a receiver configuration {{trust, profile}}")
        trust, profile = doc["trust"], doc["profile"]
    elif a.trust and a.profile and not a.config:
        trust, profile = _own(a.trust, "--trust"), _own(a.profile, "--profile")
    else:
        raise Usage("name the receiver: --trust T and --profile P, or --config V3JSON")
    return trust, profile                                # verify() holds them to their shapes


def _run(argv, prog):
    ap = argparse.ArgumentParser(prog=prog, allow_abbrev=False, description="May this receiver rely on what it was "
                                 "handed? Exit 0: yes, every root asked for. 1: no. 2: a wrong command line. 3: an "
                                 "error of the verifier.")
    ap.add_argument("package", help="a package/3 file (handoff export)")
    ap.add_argument("--trust", help="your trust/3 file: which keys are whose")
    ap.add_argument("--profile", help="your profile/3 file: who holds which role")
    ap.add_argument("--config", help="a file holding both, {trust, profile} (a repository's .warrant/v3.json)")
    ap.add_argument("--as-of", type=int, help="leave out records dated after this Unix time")
    ap.add_argument("--checkout", help="a Git checkout: compare the files the acceptances name with its HEAD")
    ap.add_argument("--require", nargs="+", action="extend", default=[], metavar="ROOT",
                    help="the record ids you ask about (default: the ones the package names)")
    ap.add_argument("--max-bytes", type=int, default=MAX_BYTES, help=f"refuse a larger package (default {MAX_BYTES})")
    ap.add_argument("--witness", help="a witness/1 file: a witness's snapshots and proofs against its roots (absence)")
    ap.add_argument("--extends", help="with --witness: a snapshot id accepted before; the one used must descend from it")
    a = ap.parse_args(argv)
    if a.extends is not None and (a.witness is None or not S.hex64(a.extends)):
        raise Usage("--extends names a snapshot id (64 lowercase hex digits), with --witness")
    if a.max_bytes < 1 or (a.as_of is not None and a.as_of < 0):
        raise Usage("--max-bytes is at least 1 and --as-of is not negative")
    if not all(S.hex64(r) for r in a.require):
        raise Usage("--require names record ids: 64 lowercase hex digits each")
    trust, profile = _receiver(a)
    try:
        with open(a.package, "rb") as f:  # NOSONAR S8707: the package its command line names, read as data within --max-bytes
            raw = f.read(a.max_bytes + 1)
    except OSError as e:
        raise Usage(f"the package {a.package}: {type(e).__name__}") from None
    wit = None if a.witness is None else _own(a.witness, "--witness")
    ans = verify(raw, trust, profile, a.as_of, a.require, None if a.checkout is None else read_checkout(a.checkout), a.max_bytes,
                 wit, a.extends)
    line = C.canon(ans) + b"\n"
    out = getattr(sys.stdout, "buffer", None)            # the bytes, whatever encoding the terminal has
    if out is None:
        sys.stdout.write(line.decode("utf-8"))
    else:
        out.write(line)
        out.flush()
    if (ans.get("absence") or {}).get("equivocation"):
        return 4
    return 0 if ans["rely"] else 1


def main(argv=None, prog="warrant verify"):
    """The command: the exit status is the gate (module docstring). An error of this file exits 3: an uncaught Python
    error would exit 1, the code of a negative answer."""
    try:
        return _run(sys.argv[1:] if argv is None else list(argv), prog)
    except Usage as e:
        print(f"{prog}: {e}", file=sys.stderr)
        return 2
    except Exception as e:                       # NOSONAR: every error of the verifier itself is exit 3
        print(f"{prog}: error of the verifier: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
