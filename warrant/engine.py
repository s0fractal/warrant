"""Assessment (docs/V3.md §§3-7, 10): one pure pass over a snapshot under the receiver's trust and
profile. Authentication, actor chains, schemas, lineages with FORK, guards, challenges, reliance
and the graph come out of the same View."""
import hashlib
from pathlib import Path

from warrant import jcs as C
from warrant import keys as K
from warrant import shapes as S

from . import records as R
from .store import LIMITS

NONE, MET, PENDING = "NONE", "MET", "PENDING"
# Every word a report answers with, for the agent's glossary (warrant_agent/glossary.py is held to these).
GUARDS = (NONE, MET, PENDING)
RELIANCE = ("ELIGIBLE", "PENDING", "CHALLENGED", "FORK")
BASES = ("SIGNED", "MIGRATED")
PROBLEMS = ("INVALID", "LINEAGE_BACKDATED", "LINEAGE_BROKEN", "LINEAGE_NOT_AUTHOR", "MIGRATION_MAP", "SCHEMA_CONFLICT",
            "SCHEMA_NOT_COUNTED")
REJECTIONS = ("line", "BAD_SIGNATURE", "UNSIGNED", "INVALID")
REPLAY = ("reproduces", "does_not_reproduce", "no_result", "does_not_apply")
_CODE = []


def code_identity():
    """The digest of every file that decides a verdict: this package, whole (the core imports nothing
    outside it but the standard library and the signature library), with that library's version."""
    if not _CODE:
        import cryptography
        files = sorted(Path(__file__).resolve().parent.glob("*.py"))
        h = {f"warrant/{p.name}": hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        _CODE.append(C.doc_id({"files": h, "cryptography": cryptography.__version__}))
    return _CODE[0]


def trust_problem(t):
    ok = isinstance(t, dict) and set(t) == {"warrant", "keys"} and t["warrant"] == "trust/3" and isinstance(t["keys"], dict) \
        and all(S.is_actor(a) and R.is_list(ks, S.hex64, True) for a, ks in t["keys"].items())
    return None if ok else "trust is {warrant: trust/3, keys: {actor: [sorted public hex]}}"


def profile_problem(p):
    ok = isinstance(p, dict) and {"warrant", "roles"} <= set(p) <= {"warrant", "roles", "quorum"} and p["warrant"] == "profile/3" \
        and isinstance(p["roles"], dict) and all(isinstance(k, str) and R.is_list(v, S.is_actor, True) for k, v in p["roles"].items()) \
        and isinstance(p.get("quorum", {}), dict) and all(R.is_int(k) and k >= 1 for k in p.get("quorum", {}).values())
    return None if ok else "profile is {warrant: profile/3, roles: {role: [sorted actors]}, quorum?: {role: k >= 1}}"


def _authentic(snap, trust, as_of, only=None):
    """({id: record}, {id: basis}, {id: why}, later): SIGNED by a trusted key of the actor, or
    UNSIGNED pending a migration voucher; records after as_of are left out (counted). `only`: read
    one actor's records alone (a writer's head verifies no other signature)."""
    recs, basis, bad, later = {}, {}, {}, 0
    for i, envs in snap.lines.items():
        r = envs[0]["record"]
        if only is not None and r["actor"] != only:
            continue
        if as_of is not None and r["at"] > as_of:
            later += 1
            continue
        sigs = [e["sig"] for e in envs if e["sig"] is not None]
        keys = trust["keys"].get(r["actor"], [])
        if any(R.verifies(i, s, k) for s in sigs for k in keys):
            recs[i], basis[i] = r, "SIGNED"
        elif any(e["sig"] is None for e in envs):          # a bad signature beside it never revokes the unsigned line's basis
            recs[i], basis[i] = r, "UNSIGNED"
        else:
            bad[i] = "BAD_SIGNATURE: no signature verifies under a key the trust binds to the actor"
    return recs, basis, bad, later


def head(snap, trust, actor):
    """The writer's head (§7): the latest of the actor's chained signed records no other names."""
    recs, basis, _, _ = _authentic(snap, trust, None, only=actor)
    mine = {i: r for i, r in recs.items() if basis[i] == "SIGNED"}
    named = {r["prev"] for r in mine.values()}
    # Chained as §7 says, by the links themselves: records of one second follow their chain, never their time.
    chained = {i for i, r in mine.items() if r["prev"] is None or (r["prev"] in mine and mine[r["prev"]]["at"] <= r["at"])}
    tips = sorted((mine[i]["at"], i) for i in chained if i not in named)
    return {"id": tips[-1][1], "at": tips[-1][0]} if tips else {"id": None, "at": None}


class View:
    def __init__(self, snap, trust, profile, as_of=None):
        for why in (trust_problem(trust), profile_problem(profile)):
            if why:
                raise R.Invalid(why)
        self.snap, self.trust, self.profile = snap, trust, profile
        self.as_of = as_of if as_of is not None else max((e[0]["record"]["at"] for e in snap.lines.values()), default=0)
        self.recs, self.basis, self.bad, self.later = _authentic(snap, trust, self.as_of)
        self.problems = []
        self._vouch()
        self._chains()
        self._index_attests()
        self._schemas()
        self._bodies()
        self._index_attests()
        ents = {i for i, r in self.recs.items() if r["kind"] == "entity"}
        self.root_of, self.lineages = self._lineages(ents, self._may_succeed)
        self._guards, self._effective = {}, {}
        self._requires_depth()

    def _index_attests(self):
        self.attests = {}
        for i, r in sorted(self.recs.items(), key=lambda kv: (kv[1]["at"], kv[0])):
            if r["kind"] == "attest":
                self.attests.setdefault(r["body"]["target"], []).append(i)

    def holds(self, actor, *roles):
        return any(actor in self.profile["roles"].get(x, []) for x in roles)

    def problem(self, code, rid, detail=""):
        self.problems.append([code, rid, detail])

    def drop(self, i, why):
        self.bad[i] = why
        self.recs.pop(i, None)
        self.basis.pop(i, None)

    # -- authentication of migrated records (§9)

    def _vouch(self):
        vouched = {}
        for i, r in sorted(self.recs.items()):
            if not (r["kind"] == "attest" and r["schema"] == R.MIGRATION and self.basis[i] == "SIGNED"
                    and self.holds(r["actor"], "migrator")):
                continue
            doc = self.snap.json_blob(r["body"]["target"])
            rows = doc.get("map") if isinstance(doc, dict) else None
            if not (isinstance(rows, list) and all(isinstance(x, list) and len(x) == 3 and S.hex64(x[0]) for x in rows)):
                self.problem("MIGRATION_MAP", i, "its target is not a map blob in the view")
                continue
            for row in rows:
                vouched.setdefault(row[0], i)
        self.vouched_by = {}
        for i in [i for i, b in self.basis.items() if b == "UNSIGNED"]:
            by = vouched.get(i)
            if by is not None:
                self.basis[i], self.vouched_by[i] = "MIGRATED", by
            else:
                self.drop(i, "UNSIGNED: no signature, and no migration the profile accepts lists it")

    # -- actor chains (§7)

    def _chains(self):
        signed = {i: r for i, r in self.recs.items() if self.basis[i] == "SIGNED"}
        self.chain_forks, by_prev, self.unanchored = [], {}, []
        for i, r in sorted(signed.items()):
            by_prev.setdefault((r["actor"], r["prev"]), []).append(i)
            p = signed.get(r["prev"]) if r["prev"] else None
            if r["prev"] is not None and not (p and p["actor"] == r["actor"] and p["at"] <= r["at"]):
                self.unanchored.append(i)
        self.chain_forks = [[a, p, ids] for (a, p), ids in sorted(by_prev.items(), key=lambda kv: (kv[0][0], kv[0][1] or ""))
                            if len(ids) > 1]

    # -- schemas (§4)

    def _schemas(self):
        self.schemas, cand = {}, {}
        for i, r in self.recs.items():
            if r["kind"] == "schema":
                why = _schema_problem(r["body"])
                backers = self.backers(i)
                if why or len(backers) < self.quorum("schema/author"):
                    self.problem("SCHEMA_NOT_COUNTED", i, why or f"{len(backers)} of the {self.quorum('schema/author')} "
                                 f"schema/author actors stand behind it: {', '.join(backers) or 'none'}")
                    continue
                cand[i] = r
        _, lins = self._lineages(set(cand), lambda r, root: r["actor"] == root["actor"])
        by_name = {}
        for root, lin in lins.items():
            if lin["leaf"] is None:
                self.problem("SCHEMA_CONFLICT", root, "its lineage forks")
                continue
            by_name.setdefault(self.recs[lin["leaf"]]["body"]["name"], []).append(lin["leaf"])
        for name, leaves in sorted(by_name.items()):
            if len(leaves) > 1:
                self.problem("SCHEMA_CONFLICT", name, f"{len(leaves)} schema lineages name it")
            else:
                self.schemas[name] = {"id": leaves[0], **self.recs[leaves[0]]["body"]}

    def quorum(self, role):
        return self.profile.get("quorum", {}).get(role, 1)

    def backers(self, i):
        """The schema/author actors behind schema record i: its filer and each that attests it with accept."""
        out = {self.recs[a]["actor"] for a in self.attests.get(i, []) if self.recs[a]["body"].get("verdict") == "accept"}
        out.add(self.recs[i]["actor"])
        return sorted(a for a in out if self.holds(a, "schema/author"))

    def _bodies(self):
        for i, r in sorted(self.recs.items()):
            if r["kind"] == "schema" or (r["schema"] is None and r["kind"] != "entity") or r["schema"] == R.MIGRATION:
                continue
            s = self.schemas.get(r["schema"])
            why = f"schema {r['schema']!r} is not one this receiver counts" if s is None else _body_problem(r, s)
            if why:
                self.problem("INVALID", i, why)
                self.drop(i, f"INVALID: {why}")

    # -- lineages (§3)

    def _may_succeed(self, r, root):
        """A state the schema's successors name is entered only by those roles; any other by the root's actor."""
        roles = self.schemas[r["schema"]]["successors"].get(r["body"].get("state"))
        return r["actor"] == root["actor"] if roles is None else self.holds(r["actor"], *roles)

    def _lineages(self, ids, may_succeed):
        """({id: root}, {root: lineage}) over `ids`; successors that break the rules are excluded."""
        root_of = {}
        for i in sorted(ids):
            path, cur = [], i
            while cur not in root_of and cur in ids and self.recs[cur]["lineage"] is not None and len(path) < 4096:
                path.append(cur)
                cur = self.recs[cur]["lineage"]
            if cur not in root_of:
                root_of[cur] = cur if cur in ids and self.recs[cur]["lineage"] is None else None
            for x in reversed(path):
                p, r, rt = self.recs[x]["lineage"], self.recs[x], root_of[self.recs[x]["lineage"]]
                if rt is None or self.recs[p]["kind"] != r["kind"] or self.recs[p]["schema"] != r["schema"]:
                    root_of[x] = None
                    self.problem("LINEAGE_BROKEN", x, f"it succeeds {p[:12]}, which is no admitted version of its kind and schema")
                elif not may_succeed(r, self.recs[rt]):
                    root_of[x] = None
                    self.problem("LINEAGE_NOT_AUTHOR", x, f"filed by {r['actor']!r}; the lineage is {self.recs[rt]['actor']!r}'s")
                else:
                    root_of[x] = rt
                    if r["at"] < self.recs[p]["at"]:
                        self.problem("LINEAGE_BACKDATED", x, "dated before the version it succeeds")
        lins = {}
        for i in sorted(ids, key=lambda i: (self.recs[i]["at"], i)):
            rt = root_of.get(i)
            if rt is None:
                continue
            lin = lins.setdefault(rt, {"versions": [], "succ": {}})
            lin["versions"].append(i)
            if i != rt:
                lin["succ"].setdefault(self.recs[i]["lineage"], []).append(i)
        for rt, lin in lins.items():
            forks = {p: c for p, c in lin["succ"].items() if len(c) > 1}
            lin["forks"] = [[p, c] for p, c in sorted(forks.items())]
            if forks:
                lin["path"], lin["leaf"] = [], None
                continue
            path = [rt]
            while path[-1] in lin["succ"]:
                path.append(lin["succ"][path[-1]][0])
            lin["path"], lin["leaf"] = path, path[-1]
        return {i: rt for i, rt in root_of.items() if rt is not None and i in ids}, lins

    # -- guards (§6)

    def _requires_depth(self):
        """Refuse the store (§8) when a chain of lineages requiring lineages is longer than LIMITS["requires"]:
        guards are resolved depth first, in process, and the bound keeps that off the interpreter's stack. The
        depth is the structure's (every version's requires, cycles cut), so it does not depend on the order in
        which versions are evaluated. Computed without recursion."""
        deps = {L: sorted({x for v in lin["versions"] for x in (self.recs[v]["guard"] or {}).get("requires", [])
                           if x in self.lineages}) for L, lin in self.lineages.items()}
        depth = {}
        for start in sorted(deps):
            if start in depth:
                continue
            stack, on = [(start, iter(deps[start]))], {start}
            while stack:
                node, it = stack[-1]
                nxt = next(it, None)
                if nxt is None:
                    stack.pop()
                    on.discard(node)
                    depth[node] = 1 + max((depth[c] for c in deps[node] if c in depth), default=0)
                elif nxt not in depth and nxt not in on:
                    on.add(nxt)
                    stack.append((nxt, iter(deps[nxt])))
        if max(depth.values(), default=0) > LIMITS["requires"]:
            raise R.Invalid(f"store beyond limits: lineages require lineages {max(depth.values())} deep, "
                            f"more than {LIMITS['requires']}")

    def schema_of(self, i):
        return self.schemas[self.recs[i]["schema"]]

    def guard(self, v):
        if v in self._guards:
            return self._guards[v]
        self._guards[v] = {"guard": PENDING, "waiting": ["a requires cycle"], "accepted_by": [], "roles": [], "short": 0,
                           "open": [v]}         # while in progress
        r, g = self.recs[v], self.recs[v]["guard"]
        acc, waiting, still_open = [], [], []
        if g is not None:
            acc = sorted({self.recs[a]["actor"] for a in self.attests.get(v, [])
                          if self.recs[a]["actor"] != r["actor"] and self.holds(self.recs[a]["actor"], *g["roles"])
                          and all(self.recs[a]["body"].get(k) == x for k, x in g["match"].items())})
            if len(acc) < g["quorum"]:
                waiting.append(f"{g['quorum'] - len(acc)} attest(s) by {', '.join(g['roles'])} matching {C.canon(g['match']).decode()}")
        if r["body"].get("state") in self.schema_of(v).get("closed", []):       # with or without a guard (Codex #3)
            for L in self.requires(v):
                eff = self.effective(L) if L in self.lineages else None
                if eff is None or self.recs[eff]["body"].get("state") not in self.schema_of(L).get("closed", []):
                    waiting.append(f"requires {L} closed")
                    still_open.append(L)
        out = {"guard": PENDING if waiting else NONE if g is None else MET, "waiting": waiting, "accepted_by": acc,
               "roles": g["roles"] if g else [], "short": max(0, g["quorum"] - len(acc)) if g else 0, "open": still_open}
        self._guards[v] = out
        return out

    def requires(self, v):
        out, cur = set(), v
        while cur is not None:
            out.update((self.recs[cur]["guard"] or {}).get("requires", []))
            cur = self.recs[cur]["lineage"]
        return sorted(out)

    def effective(self, L):
        if L not in self._effective:
            self._effective[L] = None
            path = self.lineages[L]["path"]
            self._effective[L] = next((v for v in reversed(path) if self.guard(v)["guard"] in (NONE, MET)), None)
        return self._effective[L]

    # -- challenges (§5)

    def challenge(self, c):
        r = self.recs[c]
        x = r["body"]["target"]
        t = self.recs.get(x)
        replays = [[self.recs[a]["body"].get("on"), self.recs[a]["body"].get("verdict"), self.recs[a]["actor"]]
                   for a in self.attests.get(c, []) if self.holds(self.recs[a]["actor"], "replayer")
                   and self.recs[a]["body"].get("verdict") in REPLAY]
        why = None
        if t is not None and r["actor"] == t["actor"]:
            why = "its target's actor"
        elif t is not None and t["guard"] and self.holds(r["actor"], *t["guard"]["roles"]):
            why = "holds a role of its target's guard"
        elif self.holds(r["actor"], "challenger"):
            why = "holds the challenger role"
        elif any(on == x and v == "reproduces" for on, v, _ in replays):
            why = "reproduced by a replayer"
        stands = why is not None and t is not None
        if stands and x in self.root_of:
            lin = self.lineages[self.root_of[x]]
            eff = self.effective(self.root_of[x])
            stands = x in lin["path"] and (eff is None or lin["path"].index(eff) <= lin["path"].index(x))
        return {"target": x, "counted": why is not None, "why": why or "thesis: its actor's challenge does not count here",
                "replays": sorted(replays, key=lambda z: (str(z[0]), str(z[1]), z[2])), "stands": stands}

    # -- the report (§10)

    def report(self):
        challenges = {c: self.challenge(c) for c, r in sorted(self.recs.items()) if r["kind"] == "challenge"}
        standing = {}
        for c, x in challenges.items():
            if x["stands"]:
                standing.setdefault(x["target"], []).append(c)
        versions = {v: dict(self.guard(v), challenged_by=standing.get(v, [])) for v in sorted(self.root_of)}
        lineages = {}
        for L, lin in sorted(self.lineages.items()):
            eff = self.effective(L)
            reliance = "FORK" if lin["leaf"] is None else "PENDING" if eff is None else \
                "CHALLENGED" if standing.get(eff) else "ELIGIBLE"
            lineages[L] = {"schema": self.recs[L]["schema"], "actor": self.recs[L]["actor"], "versions": lin["versions"],
                           "path": lin["path"], "leaf": lin["leaf"], "effective": eff,
                           "state": self.recs[eff]["body"].get("state") if eff else None,
                           "verdict": "FORK" if lin["forks"] else "OK", "forks": lin["forks"], "reliance": reliance}
        operands = {"snapshot": self.snap.digest, "trust": C.doc_id(self.trust), "profile": C.doc_id(self.profile),
                    "as_of": self.as_of, "code": code_identity()}
        return {"warrant": "3", "assessment": C.doc_id(operands), **operands, "completeness": "UNATTESTED",
                "canonical": self.snap.canonical, "later": self.later,
                "basis": {b: sum(1 for x in self.basis.values() if x == b) for b in ("SIGNED", "MIGRATED")},
                "rejected": dict(sorted({**self.snap.rejected, **self.bad}.items())),
                "duplicates": sorted(i for i, e in self.snap.lines.items() if len(e) > 1 and i in self.recs),
                "chains": {"forks": self.chain_forks, "unanchored": self.unanchored},
                "schemas": {n: s["id"] for n, s in sorted(self.schemas.items())},
                "schemas_pending": {i: {"name": r["body"].get("name"), "backed_by": self.backers(i), "need": self.quorum("schema/author")}
                                    for i, r in sorted(self.recs.items()) if r["kind"] == "schema"
                                    and len(self.backers(i)) < self.quorum("schema/author")},
                "lineages": lineages, "versions": versions, "challenges": challenges,
                "problems": sorted(self.problems), "graph": self.graph()}

    def graph(self):
        nodes, edges = [], []
        for i, r in sorted(self.recs.items()):
            nodes.append([i, r["kind"], r["schema"], r["actor"], r["at"], self.basis[i]])
            t = r["body"].get("target") if r["kind"] in ("attest", "challenge") else None
            edges += [[i, "lineage", r["lineage"]]] if r["lineage"] else []
            edges += [[i, "prev", r["prev"]]] if r["prev"] else []
            edges += [[i, r["kind"], t]] if t else []
            edges += [[i, "requires", x] for x in (r["guard"] or {}).get("requires", [])]
            edges += [[i, "ref", x] for x in r["refs"] if x != t]
        return {"nodes": nodes, "edges": sorted(edges)}


def _schema_problem(b):
    ok = isinstance(b, dict) and set(b) == {"name", "fields", "states", "closed", "successors"} \
        and isinstance(b["name"], str) and 0 < len(b["name"]) <= 100 and b["name"] != R.MIGRATION \
        and isinstance(b["fields"], dict) and all(isinstance(t, str) and t.rstrip("?") in R.TYPES for t in b["fields"].values()) \
        and (b["states"] is None or (isinstance(b["states"], dict) and b["fields"].get("state") == "str"
                                     and all(g is None or R.guard_problem(g) is None for g in b["states"].values()))) \
        and R.is_list(b["closed"], lambda s: isinstance(b["states"], dict) and s in b["states"], True) \
        and isinstance(b["successors"], dict) and all(isinstance(b["states"], dict) and st in b["states"]
                                                      and R.is_list(rs, S.is_actor, True) for st, rs in b["successors"].items())
    return None if ok else ("a schema body is {name, fields: {member: type}, states: {state: guard|null}|null, closed, "
                            "successors: {state: [roles]}}")


def _body_problem(r, s):
    b, f = r["body"], s["fields"]
    if r["kind"] in ("attest", "challenge") and "target" not in f:
        f = dict(f, target="ref")
    extra, missing = set(b) - set(f), {k for k, t in f.items() if not t.endswith("?")} - set(b)
    if extra or missing:
        return f"members {sorted(extra)} are not in {s['name']}, or {sorted(missing)} are missing"
    bad = [k for k, v in b.items() if not R.type_ok(f[k], v)]
    if bad:
        return f"members {bad} do not have their types in {s['name']}"
    if not R.body_refs(f, b) <= set(r["refs"]):
        return "a reference in the body is not in refs"
    if r["kind"] != "entity":
        return None
    if not isinstance(s["states"], dict) or b.get("state") not in s["states"]:
        return f"state {b.get('state')!r} is not a state of {s['name']}"
    need = s["states"][b["state"]]
    if need is not None and _weaker(r["guard"], need):
        return f"its guard is weaker than {s['name']}'s for state {b['state']!r}"
    return None


def _weaker(g, need):
    if g is None:
        return True
    return (g["quorum"] < need["quorum"] or (need["quorum"] > 0 and not set(g["roles"]) <= set(need["roles"]))
            or any(g["match"].get(k, object()) != v for k, v in need["match"].items())
            or not set(need["requires"]) <= set(g["requires"]))


def assess(snap, trust, profile, as_of=None):
    return View(snap, trust, profile, as_of).report()
