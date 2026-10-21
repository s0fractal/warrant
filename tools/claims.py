#!/usr/bin/env python3
"""SPEC claims as Warrant 2 records (pilot W).

The normative sentences of SPEC.md are claims filed as ordinary Warrant 2 records
in this repository's own store, `.warrant/store/` (records/<id>.json, blobs/<sha256>).
The records are the source. SPEC-CLAIMS.md is a view generated from them, and
`check` refuses it when it says anything else.

A claim is a `duty` (holder: the author; owed_to: readers; condition: attest;
accept_by: the reviewer) whose statement is the sentence, with an ATTESTED
`transition` that discharges it. The transition's evidence is one claim blob
carrying the sentence, its witness cases (tests/<file>_test.py) and its mutants
(tests/mutants.py); its `established` repeats the sentence. A sentence with no
witness or no mutant is filed UNBACKED: the transition closes nothing and opens
the question. An informative sentence is a transition with no duty, its reason
in the blob. A supersession is a transition whose `supersedes` names the claim it
replaces. A retirement is a `challenge` carrying the counter-evidence plus a
transition superseding the claim. Nothing is ever deleted.

    python3 tools/claims.py keygen --out SEED            # once per author; the seed stays out of git
    python3 tools/claims.py add --key SEED --stanza STANZAS.json
    python3 tools/claims.py add --key SEED --id SPEC-4.2-3 --text '...' --witness contract_test:H1 --mutant M01
    python3 tools/claims.py supersede --key SEED --id SPEC-4.2-3 --text '...' --because '...'
    python3 tools/claims.py retire --key SEED --id SPEC-4.2-3 --because '...' --counter HEX
    python3 tools/claims.py project                      # regenerate SPEC-CLAIMS.md
    python3 tools/claims.py check [--base REV | --no-base]
    python3 tools/claims.py --selftest                   # every refusal of `check`, burned on a copy

A sentence is quoted verbatim modulo line wrapping: runs of whitespace compare as
one space. Refusals are printed one per line as `REFUSED <CODE> <detail>`.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(ROOT))

import warrant as W                          # noqa: E402
from warrant import engine as E              # noqa: E402
from warrant import jcs as C                 # noqa: E402
from warrant import records as R             # noqa: E402
from warrant.store import Snapshot, Store, Trust   # noqa: E402

AUTHOR = "claude"
CLAIM, RETIRE = "warrant-claims/claim@1", "warrant-claims/retire@1"
PINS_VERSION = "warrant-claims/pins@1"
ID_RE = re.compile(r"^SPEC-([0-9]+(?:\.[0-9]+)*)-([1-9][0-9]*)$")
TEST_RE = re.compile(r"^[a-z][a-z0-9_]*_test$")
HEADING = re.compile(r"^#+ ([0-9]+(?:\.[0-9]+)*)\.? ")
RESIDUE_OK = set(" |-.0123456789")
BACKED_RESIDUAL = ("this record cites its witness cases and mutants and does not run them; "
                   "CI runs the suites and tests/mutants.py before tools/claims.py check")
UNBACKED_RESIDUAL = "UNBACKED: no witness case or no mutant cites this sentence yet"
CLAIM_FIELDS = ("schema", "id", "source", "section", "text", "kind", "duty", "witnesses", "mutants",
                "reason", "because", "previous")
RETIRE_FIELDS = ("schema", "id", "because", "counter", "challenge", "previous")
PREVIOUS_FIELDS = ("transition", "duty", "statement_sha256")


class Refused(Exception):
    """An authoring command that cannot be carried out; nothing was written."""


def norm(s):
    return " ".join(s.split())


def replace_wrapped(s, old, new):
    """Replace the first occurrence of `old` in `s`, however `s` wraps it across lines."""
    pattern = r"\s+".join(re.escape(w) for w in old.split())
    out, n = re.subn(pattern, lambda m: new, s, count=1)
    if n != 1:
        raise ValueError(f"not found: {old[:60]!r}")
    return out


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def id_key(cid):
    m = ID_RE.match(cid)
    return (tuple(int(x) for x in m.group(1).split(".")), int(m.group(2))) if m else ((99999,), 0)


def statement_for(cid, text):
    """The duty statement: the id and the sentence, within SPEC §3.1's 400 code points.
    A longer sentence is cut here; the duty's subject blob and the transition carry it whole."""
    s = f"{cid}: {text}"
    return s if len(s) <= 400 else s[:399] + "…"


# ---------------------------------------------------------------- the repository

class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.spec = self.root / "SPEC.md"
        self.store_dir = self.root / ".warrant" / "store"
        self.trust_path = self.root / ".warrant" / "trust.json"
        self.pins_path = self.root / ".warrant" / "claims.json"
        self.projection = self.root / "SPEC-CLAIMS.md"
        self.tests = self.root / "tests"
        self._mutants = None

    def pins(self):
        return json.loads(self.pins_path.read_text())

    def write_pins(self, pins):
        pins["sentences"] = dict(sorted(pins["sentences"].items(), key=lambda kv: id_key(kv[0])))
        self.pins_path.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n")

    def trust(self):
        return Trust.load(self.trust_path)

    def snapshot(self):
        return Snapshot.read(self.store_dir)

    def section_lines(self, n):
        """The lines of section `n` of SPEC.md, headings excluded, up to the next heading."""
        out = None
        for line in self.spec.read_text().split("\n"):
            if line.startswith("#"):
                if out is not None:
                    break
                m = HEADING.match(line)
                if m and m.group(1) == n:
                    out = []
                continue
            if out is not None:
                out.append(line)
        return out

    def section(self, n):
        lines = self.section_lines(n)
        return None if lines is None else norm(" ".join(lines))

    def mutants(self):
        """{id: (test file, [target cases])} from tests/mutants.py."""
        if self._mutants is None:
            spec = importlib.util.spec_from_file_location("claims_mutants", self.tests / "mutants.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            ids = [m[0] for m in mod.MUTANTS]
            self.twice = {i for i in ids if ids.count(i) > 1}
            self._mutants = {m[0]: (m[4], list(m[5])) for m in mod.MUTANTS}
        return self._mutants

    def has_case(self, test, case):
        p = self.tests / f"{test}.py"
        return p.is_file() and re.search(r"[\"']" + re.escape(case) + r"[\"']", p.read_text()) is not None


def witness_problems(repo, witnesses, mutants):
    """(code, detail) for each cited case or mutant that does not exist or does not burn a cited case."""
    out, cited = [], set()
    for w in witnesses:
        test, _, case = w.partition(":")
        if not (TEST_RE.match(test) and case):
            out.append(("BAD_WITNESS", f"{w!r} is not <test file>:<case id>"))
        elif not (repo.tests / f"{test}.py").is_file():
            out.append(("UNKNOWN_TEST_FILE", f"tests/{test}.py does not exist ({w})"))
        elif not repo.has_case(test, case):
            out.append(("UNKNOWN_CASE", f"tests/{test}.py has no case {case}"))
        else:
            cited.add((test, case))
    try:
        known = repo.mutants()
    except Exception as e:      # noqa: BLE001
        return out + [("MUTANTS_UNREADABLE", f"tests/mutants.py: {type(e).__name__}: {e}")]
    for mid in mutants:
        if mid not in known:
            out.append(("UNKNOWN_MUTANT", f"tests/mutants.py has no mutant {mid}"))
            continue
        if mid in repo.twice:
            out.append(("DUPLICATE_MUTANT_ID", f"tests/mutants.py defines {mid} more than once"))
            continue
        test, targets = known[mid]
        if not {(test, t) for t in targets} & cited:
            out.append(("MUTANT_OFF_WITNESS", f"{mid} targets {test} {','.join(targets)}, none of them cited"))
    return out


# ---------------------------------------------------------------- the records, read

class Node:
    """One claim transition: its record, its claim (or retire) blob."""

    def __init__(self, tid, rec, doc):
        self.tid, self.rec, self.doc = tid, rec, doc
        self.id = doc["id"]
        self.retired = doc["schema"] == RETIRE
        self.kind = "retired" if self.retired else doc["kind"]

    @property
    def backed(self):
        return self.kind == "normative" and bool(self.doc["witnesses"]) and bool(self.doc["mutants"])

    @property
    def status(self):
        if self.retired:
            return "RETIRED"
        if self.kind == "informative":
            return "INFORMATIVE"
        return "BACKED" if self.backed else "UNBACKED"


class Model:
    """The claims a snapshot holds under a trust, and what is wrong with them."""

    def __init__(self, snap, trust):
        self.snap = snap
        self.recs, self.bad = snap.authentic(trust)
        self.problems = []
        self.nodes = {}
        for rid, r in sorted(self.recs.items()):
            if r["type"] != "transition":
                continue
            heads = [(h, d) for h in r["body"]["evidence"] for d in [snap.json_blob(h)]
                     if isinstance(d, dict) and d.get("schema") in (CLAIM, RETIRE)]
            if not heads:
                continue
            if len(heads) > 1:
                self.problems.append(("STRUCTURE", f"transition {rid[:12]} carries {len(heads)} claim blobs"))
                continue
            h, doc = heads[0]
            why = self._shape(rid, r, h, doc)
            if why:
                self.problems.append(("STRUCTURE", f"transition {rid[:12]}: {why}"))
                continue
            self.nodes[rid] = Node(rid, r, doc)
        for n in list(self.nodes.values()):
            why = self._link(n)
            if why:
                self.problems.append(("STRUCTURE", f"transition {n.tid[:12]} ({n.id}): {why}"))
                del self.nodes[n.tid]
        replaced = {s for n in self.nodes.values() for s in n.rec["body"]["supersedes"]}
        self.by_id = {}
        for n in self.nodes.values():
            self.by_id.setdefault(n.id, []).append(n)
        self.current = {}
        for cid, ns in sorted(self.by_id.items()):
            cur = [n for n in ns if n.tid not in replaced]
            if len(cur) != 1:
                self.problems.append(("FORK", f"{cid} has {len(cur)} current claims: "
                                      + ", ".join(n.tid[:12] for n in cur)))
            if cur:
                self.current[cid] = sorted(cur, key=lambda n: (n.rec["at"], n.tid))[-1]
        live = {n.tid: n for n in self.current.values()}
        self.challenges = {}
        for rid, r in sorted(self.recs.items()):
            if r["type"] == "challenge" and r["body"]["target"] in live:
                self.challenges.setdefault(live[r["body"]["target"]].id, []).append(rid)

    def _shape(self, rid, r, h, doc):
        """Why this transition is not a well-formed claim transition, or None."""
        b = r["body"]
        if b["basis"] != "ATTESTED":
            return "basis is not ATTESTED"
        if doc["schema"] == RETIRE:
            return self._retire_shape(r, h, doc)
        if set(doc) != set(CLAIM_FIELDS):
            return f"claim blob members are not {list(CLAIM_FIELDS)}"
        if not (isinstance(doc["id"], str) and ID_RE.match(doc["id"])):
            return f"claim id {doc['id']!r} is not SPEC-<section>-<n>"
        if doc["section"] != ID_RE.match(doc["id"]).group(1) or doc["source"] != "SPEC.md":
            return "section or source does not match the id"
        if not (isinstance(doc["text"], str) and doc["text"] and doc["text"] == norm(doc["text"])):
            return "text must be a non-empty whitespace-normalized string"
        lists = all(isinstance(doc[k], list) and all(isinstance(x, str) for x in doc[k])
                    and doc[k] == sorted(set(doc[k])) for k in ("witnesses", "mutants"))
        if not lists:
            return "witnesses and mutants must be sorted lists of distinct strings"
        if doc["previous"] is not None and not (isinstance(doc["previous"], dict) and set(doc["previous"]) == set(PREVIOUS_FIELDS)):
            return "previous must be null or {transition, duty, statement_sha256}"
        if (doc["previous"] is None) != (doc["because"] is None) or (doc["because"] is not None and not (isinstance(doc["because"], str) and doc["because"])):
            return "a claim that replaces another says because, and only then"
        if doc["kind"] == "informative":
            if doc["duty"] is not None or not (isinstance(doc["reason"], str) and doc["reason"]) or doc["witnesses"] or doc["mutants"]:
                return "an informative claim has a reason and no duty, witnesses or mutants"
            return "an informative claim closes and establishes nothing" if b["closes"] or b["established"] else None
        if doc["kind"] != "normative" or doc["reason"] is not None:
            return "kind must be normative (no reason) or informative"
        d = self.recs.get(doc["duty"]) if isinstance(doc["duty"], str) else None
        if d is None or d["type"] != "duty":
            return "its duty is not an authentic duty record in the store"
        db = d["body"]
        if d["actor"] != r["actor"] or db["statement"] != statement_for(doc["id"], doc["text"]):
            return "the duty is not the author's duty for this sentence"
        if db["condition"] != {"attest": {}} or db["subject"] != sha(doc["text"]) or \
                self.snap.blob(db["subject"]) != doc["text"].encode():
            return "the duty's condition is not attest, or its subject is not the sentence's blob"
        if doc["witnesses"] and doc["mutants"]:
            want = [{"duty": doc["duty"], "act": "discharge", "evidence": [h]}]
            if b["closes"] != want or b["established"] != [doc["text"]]:
                return "a backed claim discharges its duty on the claim blob and establishes the sentence"
        elif b["closes"] or b["established"]:
            return "an unbacked claim closes and establishes nothing"
        return None

    def _retire_shape(self, r, h, doc):
        if set(doc) != set(RETIRE_FIELDS) or not (isinstance(doc["previous"], dict) and set(doc["previous"]) == set(PREVIOUS_FIELDS)):
            return f"retire blob members are not {list(RETIRE_FIELDS)}"
        if not (isinstance(doc["id"], str) and ID_RE.match(doc["id"]) and isinstance(doc["because"], str) and doc["because"]):
            return "a retirement names its claim and says because"
        b = r["body"]
        if b["closes"] or b["supersedes"] != [doc["previous"]["transition"]]:
            return "a retirement closes nothing and supersedes exactly the claim it retires"
        ch = self.recs.get(doc["challenge"]) if isinstance(doc["challenge"], str) else None
        if ch is None or ch["type"] != "challenge" or ch["body"]["target"] != doc["previous"]["transition"] \
                or doc["counter"] not in ch["body"]["evidence"]:
            return "its challenge is not in the store, or targets another claim, or lacks the counter-evidence"
        if not isinstance(doc["counter"], str) or not (self.snap.blob(doc["counter"]) is not None or doc["counter"] in self.recs):
            return "its counter-evidence does not resolve in the store"
        if not {doc["counter"], doc["challenge"], h} <= set(b["evidence"]):
            return "the transition does not carry its counter-evidence and challenge as evidence"
        return None

    def _link(self, n):
        """A replacing claim names, in `previous` and `supersedes`, a claim of the same id."""
        prev = n.doc["previous"]
        sup = n.rec["body"]["supersedes"]
        if prev is None:
            return "it supersedes something without saying what it replaces" if sup else None
        if sup != [prev["transition"]]:
            return "supersedes does not name exactly its previous claim"
        p = self.nodes.get(prev["transition"])
        if p is None or p.id != n.id or p.retired:
            return "its previous claim is not a live claim transition of the same id"
        if prev["duty"] != p.doc["duty"] or prev["statement_sha256"] != sha(p.doc["text"]):
            return "previous does not repeat the replaced claim's duty and statement hash"
        return None

    def text_of(self, n):
        """The last sentence a claim chain stated (a retirement states none of its own)."""
        while n.retired:
            n = self.nodes[n.doc["previous"]["transition"]]
        return n.doc["text"]


# ---------------------------------------------------------------- the view

def assessment(snap, trust):
    recs, _ = snap.authentic(trust)
    as_of = max((r["at"] for r in recs.values()), default=0)
    return E.assess(snap, trust, as_of, E.profile())


def disposition(rep, n):
    if n.retired or n.kind == "informative":
        return "— (no duty)"
    r = rep["duties"].get(n.doc["duty"])
    if r is None:
        return "MISSING"
    waiting = sorted({a for c in r["candidates"] if c["verdict"] == "PENDING" for a in c.get("waiting_for") or []})
    if r["disposition"] == "OPEN":
        return f"OPEN (awaiting {', '.join(waiting)})" if waiting else "OPEN (no closure filed)"
    return r["disposition"]


def cell(s):
    return s.replace("|", "\\|")


def render(repo):
    snap, trust = repo.snapshot(), repo.trust()
    model, pins = Model(snap, trust), repo.pins()
    rep = assessment(snap, trust)
    rows = sorted(model.current.values(), key=lambda n: id_key(n.id))
    live = [n for n in rows if not n.retired]
    retired = [n for n in rows if n.retired]
    count = {s: sum(n.status == s for n in live if n.id in pins["sentences"]) for s in ("BACKED", "UNBACKED", "INFORMATIVE")}
    secs = ", ".join(f"§{s}" for s in pins["sections"])
    out = [
        "# SPEC claims (generated view)", "",
        "Generated by `python tools/claims.py project` from the Warrant 2 records in",
        "`.warrant/store/`. **The records are the source; this file is a view.**",
        "`python tools/claims.py check` refuses it when it differs from what the records",
        "say. Do not edit it by hand: change SPEC.md, then add, supersede or retire the",
        "claim, then regenerate this file (README.md, \"Changing a normative sentence\").", "",
        f"Sections {secs} of SPEC.md · sentences {len(pins['sentences'])} · backed {count['BACKED']} · "
        f"unbacked {count['UNBACKED']} · informative {count['INFORMATIVE']} · retired {len(retired)} · "
        f"records {len(snap.records)} · blobs {len(snap.blobs)}", "",
        "A witness is a case of `tests/<file>.py`; a mutant is an entry of `tests/mutants.py`",
        "that must make one of the cited cases fail. *Disposition* is Warrant's own",
        "assessment of the claim's duty in this store (trust `.warrant/trust.json`, default",
        f"profile, as of the latest record): a backed claim waits for its acceptor ({', '.join(pins['accept_by'])})",
        "until an acceptance is filed. Nobody has accepted a claim yet unless this column says DISCHARGED.", "",
        "| ID | Statement | Witnesses | Mutants | Status | Disposition | Claim |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for n in live:
        wit = "; ".join(f"{t} {' '.join(cs)}" for t, cs in _grouped(n.doc["witnesses"])) or "—"
        mut = " ".join(n.doc["mutants"]) or "—"
        status = n.status + (" · CHALLENGED" if n.id in model.challenges else "")
        if n.kind == "informative":
            status += f": {n.doc['reason']}"
        out.append(f"| {n.id} | {cell(n.doc['text'])} | {cell(wit)} | {mut} | {cell(status)} | {disposition(rep, n)} | `{n.tid[:12]}` |")
    limits = [(n.id, x) for n in live for x in n.rec["body"]["residual"] if x not in (BACKED_RESIDUAL, UNBACKED_RESIDUAL)]
    if limits:
        out += ["", "## Limits the claims record", ""] + [f"- {cid}: {x}" for cid, x in limits]
    out += ["", "## Retired", ""]
    if retired:
        out += ["| ID | Last statement | Because | Counter-evidence | Challenge | Retired by |",
                "| --- | --- | --- | --- | --- | --- |"]
        for n in retired:
            out.append(f"| {n.id} | {cell(model.text_of(n))} | {cell(n.doc['because'])} | `{n.doc['counter']}` "
                       f"| `{n.doc['challenge'][:12]}` | `{n.tid[:12]}` |")
    else:
        out.append("None.")
    return "\n".join(out) + "\n"


def _grouped(witnesses):
    groups = {}
    for w in witnesses:
        t, _, c = w.partition(":")
        groups.setdefault(t, []).append(c)
    return [(t, sorted(cs, key=lambda c: (re.sub(r"[0-9].*", "", c), int(re.sub(r"(?:^[A-Z]+)|(?:[a-z]+$)", "", c) or 0), c)))
            for t, cs in sorted(groups.items())]


# ---------------------------------------------------------------- check

def check(repo, base=None):
    """[(code, detail)]: empty iff the records, SPEC.md, the tests, the pins and the projection agree."""
    out = []
    store = repo.store_dir
    for p in sorted(store.iterdir()) if store.is_dir() else []:
        if p.name not in ("records", "blobs"):
            out.append(("STRAY_FILE", f".warrant/store/{p.name}"))
    snap, trust = repo.snapshot(), repo.trust()
    for m in snap.misfiled:
        out.append(("RECORD_MISNAMED" if m.startswith("records/") else "BLOB_MISNAMED", m))
    model = Model(snap, trust)
    for rid, why in sorted(model.bad.items()):
        code = "NOT_CANONICAL" if why.startswith("not canonical") else \
            "RECORD_MISNAMED" if why.startswith("id does not match") else "UNAUTHENTIC"
        out.append((code, f"records/{rid}.json: {why}"))
    out += model.problems
    pins = repo.pins()
    sections = {s: repo.section(s) for s in pins["sections"]}
    for s, text in sections.items():
        if text is None:
            out.append(("SECTION_MISSING", f"SPEC.md has no section {s}"))
    for cid, n in sorted(model.current.items(), key=lambda kv: id_key(kv[0])):
        if n.retired:
            continue
        sec = n.doc["section"]
        text = sections.get(sec) if sec in sections else repo.section(sec)
        if text is None or n.doc["text"] not in text:
            out.append(("QUOTE_NOT_IN_SPEC", f"{cid}: the sentence is not in SPEC.md §{sec}: {n.doc['text'][:80]!r}"))
        out += [(code, f"{cid}: {why}") for code, why in witness_problems(repo, n.doc["witnesses"], n.doc["mutants"])]
        if n.kind == "normative" and not n.backed:
            out.append(("UNBACKED", f"{cid}: a normative sentence with no witness case or no mutant"))
        if cid in model.challenges:
            out.append(("CHALLENGED", f"{cid}: standing challenge {', '.join(c[:12] for c in model.challenges[cid])}"
                        " against the current claim; supersede or retire it"))
        if sec in sections and cid not in pins["sentences"]:
            out.append(("UNPINNED_CLAIM", f"{cid}: a current claim of §{sec} that .warrant/claims.json does not pin"))
    for cid, kind in sorted(pins["sentences"].items(), key=lambda kv: id_key(kv[0])):
        n = model.current.get(cid)
        if n is None:
            out.append(("UNCLAIMED", f"{cid}: pinned, and no claim record states it"))
        elif n.retired:
            out.append(("PINNED_RETIRED", f"{cid}: pinned, but its claim is retired"))
        elif n.kind != kind:
            out.append(("KIND_MISMATCH", f"{cid}: pinned {kind}, claimed {n.kind}"))
    for s, text in sections.items():
        if text is None:
            continue
        rest = text
        claimed = [n.doc["text"] for n in model.current.values() if not n.retired and n.doc["section"] == s]
        for q in sorted(claimed, key=len, reverse=True):
            rest = rest.replace(q, " ", 1)
        words = norm("".join(ch if ch not in RESIDUE_OK else " " for ch in rest))
        if words:
            out.append(("UNCOVERED_TEXT", f"§{s} has text no current claim quotes: {words[:120]!r}"))
    if not repo.projection.is_file():
        out.append(("PROJECTION_MISSING", "SPEC-CLAIMS.md does not exist; run tools/claims.py project"))
    elif repo.projection.read_text() != render(repo):
        out.append(("PROJECTION_STALE", "SPEC-CLAIMS.md is not the view of the records; run tools/claims.py project"))
    if base is not None:
        out += check_base(repo, base, snap, model, pins)
    return out


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo.root), *args], input=data, capture_output=True, check=True).stdout


def base_files(repo, rev):
    """{path: bytes} of .warrant/ at revision `rev`."""
    listing = git(repo, "ls-tree", "-r", "-z", rev, "--", ".warrant").split(b"\0")
    entries = [(e.split(b"\t", 1)[1].decode(), e.split(b" ")[2].split(b"\t")[0].decode()) for e in listing if e]
    if not entries:
        return {}
    batch = git(repo, "cat-file", "--batch", data="".join(f"{o}\n" for _, o in entries).encode())
    out, pos = {}, 0
    for path, _ in entries:
        nl = batch.index(b"\n", pos)
        size = int(batch[pos:nl].split()[2])
        out[path] = batch[nl + 1: nl + 1 + size]
        pos = nl + 1 + size + 1
    return out


def check_base(repo, base, snap, model, pins):
    """Records are never deleted or changed, and a claim id leaves only through a record."""
    try:
        rev = git(repo, "rev-parse", "--verify", f"{base}^{{commit}}").decode().strip()
        files = base_files(repo, rev)
    except subprocess.CalledProcessError as e:
        return [("BASE_UNREADABLE", f"{base}: {e.stderr.decode().strip() or e}")]
    prefix = ".warrant/store/"
    stored = {p: b for p, b in files.items() if p.startswith(prefix)}
    if not stored:
        return []
    out = []
    for path, data in sorted(stored.items()):
        now = repo.root / path
        if not now.is_file():
            out.append(("RECORD_DELETED" if "/records/" in path else "BLOB_DELETED", f"{path} exists at {rev[:12]}"))
        elif now.read_bytes() != data:
            out.append(("RECORD_CHANGED", f"{path} differs from {rev[:12]}"))
    recs = {Path(p).name[:-5]: b for p, b in stored.items() if p.startswith(prefix + "records/") and p.endswith(".json")}
    blobs = {Path(p).name: b for p, b in stored.items() if p.startswith(prefix + "blobs/")}
    trust = Trust(C.loads(files[".warrant/trust.json"])) if ".warrant/trust.json" in files else repo.trust()
    then = Model(Snapshot(recs, blobs), trust)
    for cid in sorted(then.current, key=id_key):
        if cid not in model.by_id:
            out.append(("CLAIM_DELETED", f"{cid} is claimed at {rev[:12]} and no record states, supersedes or retires it now"))
    old_pins = json.loads(files[".warrant/claims.json"]) if ".warrant/claims.json" in files else {"sentences": {}}
    for cid in sorted(set(old_pins["sentences"]) - set(pins["sentences"]), key=id_key):
        n = model.current.get(cid)
        if n is None or not n.retired:
            out.append(("UNPINNED_WITHOUT_RETIREMENT", f"{cid} is pinned at {rev[:12]}; unpinning it needs its retirement record"))
    return out


# ---------------------------------------------------------------- authoring

def load_key(repo, path, actor):
    p = Path(path or os.environ.get("WARRANT_CLAIMS_KEY") or "")
    if not p.is_file():
        raise Refused("a signing seed is needed: --key PATH or WARRANT_CLAIMS_KEY (keygen makes one)")
    key = W.Key.from_seed_hex(p.read_text())
    if repo.trust().keys.get(key.id, (None,))[0] != actor:
        raise Refused(f"key {key.id[:12]} is not bound to {actor!r} in .warrant/trust.json")
    return key


class Author:
    """Files claim records into the repository's store under one key."""

    def __init__(self, repo, key, actor=AUTHOR, validate=True):
        self.repo, self.key, self.actor, self.validate = repo, key, actor, validate
        self.store = Store(repo.store_dir).init()
        self.pins = repo.pins()

    def model(self):
        return Model(self.repo.snapshot(), self.repo.trust())

    def at(self):
        recs = self.model().recs
        return max([int(time.time())] + [r["at"] for r in recs.values()])

    def put(self, rtype, body, at):
        return self.store.put_record(R.record(rtype, self.actor, at, body), self.key)

    def _validate(self, cid, text, kind, witnesses, mutants, reason):
        m = ID_RE.match(cid)
        if not m:
            raise Refused(f"{cid!r} is not SPEC-<section>-<n>")
        section = self.repo.section(m.group(1))
        if section is None or text not in section:
            raise Refused(f"{cid}: the sentence is not in SPEC.md §{m.group(1)}: {text[:80]!r}")
        if kind == "informative" and (witnesses or mutants or not reason):
            raise Refused(f"{cid}: an informative sentence has a reason and cites no witnesses or mutants")
        bad = witness_problems(self.repo, witnesses, mutants)
        if bad:
            raise Refused(f"{cid}: " + "; ".join(f"{c} {w}" for c, w in bad))

    def claim(self, cid, text, witnesses=(), mutants=(), reason=None, because=None, residual=(), previous=None):
        """File one claim: (duty and) transition. `previous` is the Node it replaces, or None."""
        text = norm(text)
        witnesses, mutants = sorted(set(witnesses)), sorted(set(mutants))
        kind = "informative" if reason else "normative"
        if self.validate:
            self._validate(cid, text, kind, witnesses, mutants, reason)
        if previous is not None and not because:
            raise Refused(f"{cid}: replacing a claim needs --because")
        at = self.at()
        duty = None
        if kind == "normative":
            if previous is not None and previous.kind == "normative" and previous.doc["text"] == text:
                duty = previous.doc["duty"]
            else:
                self.store.put_blob(text.encode())
                accept_by = self.pins["accept_by"]
                duty = self.put("duty", R.duty(self.actor, statement_for(cid, text), self.pins["owed_to"], {"attest": {}},
                                               accept_by=accept_by, subject=sha(text)), at)
        if previous is not None and previous.retired:
            raise Refused(f"{cid} is retired; a new sentence takes a new id")
        prev = None if previous is None else {
            "transition": previous.tid, "duty": previous.doc["duty"], "statement_sha256": sha(previous.doc["text"])}
        doc = {"schema": CLAIM, "id": cid, "source": "SPEC.md", "section": ID_RE.match(cid).group(1), "text": text,
               "kind": kind, "duty": duty, "witnesses": witnesses, "mutants": mutants, "reason": reason,
               "because": because if previous is not None else None, "previous": prev}
        h = self.store.put_json(doc)
        backed = kind == "normative" and witnesses and mutants
        body = R.transition("ATTESTED", [h],
                            closes=[R.item(duty, "discharge", [h])] if backed else [],
                            established=[text] if backed else [],
                            residual=([BACKED_RESIDUAL] if backed else [UNBACKED_RESIDUAL] if kind == "normative" else [])
                            + list(residual),
                            opened=[] if backed or kind == "informative" else
                            [{"text": f"which witness case and which mutant back {cid}?", "scope": cid}],
                            supersedes=[previous.tid] if previous is not None else [])
        tid = self.put("transition", body, at)
        self._pin(cid, kind)
        return tid

    def retire(self, cid, because, counter):
        cur = self.model().current.get(cid)
        if cur is None or cur.retired:
            raise Refused(f"{cid}: no live claim to retire")
        if not because:
            raise Refused("a retirement needs --because")
        snap = self.repo.snapshot()
        if counter not in snap.blobs and counter not in snap.records:
            raise Refused(f"counter-evidence {counter[:12]} is neither a blob nor a record of the store")
        at = self.at()
        item = 0 if cur.rec["body"]["closes"] else None
        ch = self.put("challenge", R.challenge(cur.tid, because, [counter], item), at)
        doc = {"schema": RETIRE, "id": cid, "because": because, "counter": counter, "challenge": ch,
               "previous": {"transition": cur.tid, "duty": cur.doc["duty"], "statement_sha256": sha(cur.doc["text"])}}
        h = self.store.put_json(doc)
        tid = self.put("transition", R.transition("ATTESTED", sorted({counter, ch, h}),
                                                  established=[f"{cid} is retired: {because}"],
                                                  residual=["the claim's duty and transitions stay in the store as history"],
                                                  supersedes=[cur.tid]), at)
        self.pins["sentences"].pop(cid, None)
        self.repo.write_pins(self.pins)
        return tid

    def _pin(self, cid, kind):
        section = ID_RE.match(cid).group(1)
        if section in self.pins["sections"]:
            self.pins["sentences"][cid] = kind
            self.repo.write_pins(self.pins)


def stanzas(a):
    if a.stanza:
        data = json.loads(Path(a.stanza).read_text())
        return data if isinstance(data, list) else [data]
    return [{"id": a.id, "text": a.text, "witnesses": [w for x in a.witness for w in x.split(",") if w],
             "mutants": [m for x in a.mutant for m in x.split(",") if m], "informative": a.informative,
             "residual": a.residual, "because": a.because}]


def same_claim(n, s):
    extra = [x for x in n.rec["body"]["residual"] if x not in (BACKED_RESIDUAL, UNBACKED_RESIDUAL)]
    return (n.doc["witnesses"], n.doc["mutants"], n.doc["reason"], extra) == \
        (sorted(set(s.get("witnesses", ()))), sorted(set(s.get("mutants", ()))), s.get("informative"), list(s.get("residual", ())))


def cmd_add(repo, a):
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    for s in stanzas(a):
        cur = author.model().current.get(s["id"])
        if cur is not None and cur.retired:
            raise Refused(f"{s['id']} is retired; a new sentence takes a new id")
        if cur is not None and cur.doc["text"] != norm(s["text"]):
            raise Refused(f"{s['id']} states another sentence now; use supersede")
        if cur is not None and same_claim(cur, s):
            print(f"{s['id']}: unchanged {cur.tid}")
            continue
        if cur is not None and not s.get("because"):
            raise Refused(f"{s['id']} is already claimed; re-backing it needs --because")
        tid = author.claim(s["id"], s["text"], s.get("witnesses", ()), s.get("mutants", ()), s.get("informative"),
                           s.get("because"), s.get("residual", ()), previous=cur)
        print(f"{s['id']}: {tid}")


def cmd_supersede(repo, a):
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    cur = author.model().current.get(a.id)
    if cur is None or cur.retired:
        raise Refused(f"{a.id}: no live claim to supersede")
    wit = [w for x in a.witness for w in x.split(",") if w] or (cur.doc["witnesses"] if a.informative is None else [])
    mut = [m for x in a.mutant for m in x.split(",") if m] or (cur.doc["mutants"] if a.informative is None else [])
    print(f"{a.id}: {author.claim(a.id, a.text, wit, mut, a.informative, a.because, a.residual, previous=cur)}")


def cmd_retire(repo, a):
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    counter = a.counter or author.store.put_blob(Path(a.counter_file).read_bytes())
    print(f"{a.id}: retired by {author.retire(a.id, a.because, counter)}")


def cmd_keygen(repo, a):
    out = Path(a.out).expanduser().resolve()
    if repo.root.resolve() in out.parents:
        raise Refused("the seed must live outside the repository")
    if out.exists():
        raise Refused(f"{out} exists")
    key = W.Key.generate()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(key.seed_hex() + "\n")
    out.chmod(0o600)
    doc = C.loads(repo.trust_path.read_bytes()) if repo.trust_path.is_file() else Trust.document([])
    doc["keys"].append({"actor": a.actor, "public": key.public})
    Trust(doc)
    repo.trust_path.parent.mkdir(parents=True, exist_ok=True)
    repo.trust_path.write_bytes(C.canon(doc))
    print(f"{a.actor}: key {key.id} bound in .warrant/trust.json; seed at {out}")


def default_base(repo):
    try:
        return git(repo, "rev-parse", "--verify", "origin/master^{commit}").decode().strip()
    except subprocess.CalledProcessError:
        return None


def cmd_check(repo, a):
    base = None if a.no_base else (a.base or default_base(repo))
    if base is None and not a.no_base:
        print("REFUSED BASE_UNREADABLE no --base given and origin/master is not available (use --no-base to skip)")
        return 1
    problems = check(repo, base)
    for code, detail in problems:
        print(f"REFUSED {code} {detail}")
    model = Model(repo.snapshot(), repo.trust())
    live = [n for n in model.current.values() if not n.retired]
    print(f"CLAIMS: {len(live)} current ({sum(n.backed for n in live)} backed, "
          f"{sum(n.kind == 'normative' and not n.backed for n in live)} unbacked, "
          f"{sum(n.kind == 'informative' for n in live)} informative), "
          f"{sum(n.retired for n in model.current.values())} retired; base {base[:12] if base else 'none'}; "
          f"{'OK' if not problems else f'{len(problems)} refused'}")
    return 1 if problems else 0


# ---------------------------------------------------------------- selftest

def selftest():
    """Burns `check`: on a copy of this repository's claims, each defect must be refused
    with its own code, and the clean copy, a supersession and a retirement must pass."""
    work = Path(tempfile.mkdtemp(prefix="claims-selftest-"))
    try:
        fix = work / "base"
        (fix / "tests").mkdir(parents=True)
        for p in [ROOT / "SPEC.md", ROOT / "SPEC-CLAIMS.md"]:
            shutil.copy2(p, fix / p.name)
        for p in sorted((ROOT / "tests").glob("*.py")):
            shutil.copy2(p, fix / "tests" / p.name)
        shutil.copytree(ROOT / ".warrant", fix / ".warrant")
        repo = Repo(fix)
        key = W.Key.generate()                    # an ephemeral second key for the claim author
        doc = C.loads(repo.trust_path.read_bytes())
        doc["keys"].append({"actor": AUTHOR, "public": key.public})
        repo.trust_path.write_bytes(C.canon(doc))
        g = ["-c", "user.name=claims-selftest", "-c", "user.email=selftest@invalid", "-c", "commit.gpgsign=false"]
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, *g, "commit", "-q", "-m", "base")
        base = git(repo, "rev-parse", "HEAD").decode().strip()
        model = Model(repo.snapshot(), repo.trust())
        live = sorted((n for n in model.current.values() if n.backed), key=lambda n: id_key(n.id))
        if len(live) < 2:
            print("FAIL  selftest: the repository's store has fewer than two backed claims to work on")
            return 1
        a, b = live[0], live[-1]
        failures = 0

        def case(name, expect, mutate):
            nonlocal failures
            d = work / name
            shutil.copytree(fix, d, symlinks=True)
            r = Repo(d)
            mutate(r)
            got = check(r, base)
            codes = {c for c, _ in got}
            ok = (not got) if expect is None else expect in codes
            failures += not ok
            what = "passes" if expect is None else f"refused {expect}"
            print(("ok    " if ok else "FAIL  ") + f"{name}: {what}" + ("" if ok else f" | got {sorted(codes) or 'nothing'}: {got[:3]}"))

        def author(r):
            return Author(r, key, AUTHOR, validate=False)

        def spec_edit(old, new):
            def f(r):
                r.spec.write_text(replace_wrapped(r.spec.read_text(), old, new))
            return f

        def reproject(r):
            r.projection.write_text(render(r))

        def rebacked(witnesses, mutants):
            def f(r):
                n = Model(r.snapshot(), r.trust()).current[a.id]
                author(r).claim(a.id, n.doc["text"], witnesses, mutants, because="selftest", previous=n)
                reproject(r)
            return f

        def duplicate_mutant(r):
            p = r.tests / "mutants.py"
            src = p.read_text()
            mid = a.doc["mutants"][0]
            other = next(i for i in re.findall(r'\("(M[0-9]+)", ', src) if i != mid)
            p.write_text(src.replace(f'("{other}", ', f'("{mid}", ', 1))

        def rename(r):
            p = sorted((r.store_dir / "records").iterdir())[0]
            p.rename(p.with_name(hashlib.sha256(p.name.encode()).hexdigest() + ".json"))
            reproject(r)

        def noncanonical(r):
            p = r.store_dir / "records" / f"{a.tid}.json"
            p.write_text(json.dumps(json.loads(p.read_text()), indent=1))
            reproject(r)

        def delete_claim(r):
            for rid in {n.tid for n in Model(r.snapshot(), r.trust()).by_id[b.id]} | {b.doc["duty"]}:
                (r.store_dir / "records" / f"{rid}.json").unlink()
            reproject(r)

        def hand_edit(r):
            s = r.projection.read_text()
            r.projection.write_text(s.replace("| BACKED |", "| BACKED (reviewed) |", 1))

        def challenge(r):
            author(r).put("challenge", R.challenge(a.tid, "selftest: a standing counterexample", [], 0), author(r).at())
            reproject(r)

        def unpin(r):
            p = r.pins()
            del p["sentences"][b.id]
            r.write_pins(p)

        def add_sentence(r):
            spec_edit(b.doc["text"], b.doc["text"] + " An unclaimed rule appears here.")(r)

        def supersede(r):
            new = a.doc["text"] + " (as amended)"
            spec_edit(a.doc["text"], new)(r)
            n = Model(r.snapshot(), r.trust()).current[a.id]
            author(r).claim(a.id, new, n.doc["witnesses"], n.doc["mutants"], because="selftest amendment", previous=n)
            reproject(r)

        def retire(r):
            spec_edit(b.doc["text"], "")(r)
            ev = Store(r.store_dir).put_blob(b"selftest: the sentence was removed from SPEC.md")
            author(r).retire(b.id, "selftest: removed from SPEC.md", ev)
            reproject(r)

        def unretired_removal(r):
            spec_edit(b.doc["text"], "")(r)

        case("clean copy", None, lambda r: None)
        case("a quoted sentence no longer in SPEC.md", "QUOTE_NOT_IN_SPEC", spec_edit(a.doc["text"], "Something else entirely."))
        case("a cited mutant that does not exist", "UNKNOWN_MUTANT", rebacked(a.doc["witnesses"], ["M999"]))
        case("a cited case that does not exist", "UNKNOWN_CASE", rebacked(["contract_test:Z9"], a.doc["mutants"]))
        case("a mutant that burns none of the cited cases", "MUTANT_OFF_WITNESS", rebacked(["contract_test:A1"], ["M19"]))
        case("a normative sentence without a mutant", "UNBACKED", rebacked(a.doc["witnesses"], []))
        case("a cited mutant id defined twice", "DUPLICATE_MUTANT_ID", duplicate_mutant)
        case("a record file renamed", "RECORD_MISNAMED", rename)
        case("a record rewritten in non-canonical bytes", "NOT_CANONICAL", noncanonical)
        case("a claim deleted without a retiring record", "CLAIM_DELETED", delete_claim)
        case("the projection edited by hand", "PROJECTION_STALE", hand_edit)
        case("a standing challenge against a current claim", "CHALLENGED", challenge)
        case("a pinned sentence unpinned without retirement", "UNPINNED_WITHOUT_RETIREMENT", unpin)
        case("a new sentence in a pinned section with no claim", "UNCOVERED_TEXT", add_sentence)
        case("a sentence removed from SPEC.md, its claim not retired", "QUOTE_NOT_IN_SPEC", unretired_removal)
        case("a supersession with because", None, supersede)
        case("a retirement with counter-evidence", None, retire)
        print(f"CLAIMS SELFTEST: {'OK' if not failures else f'{failures} FAIL'}")
        return 1 if failures else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--selftest", action="store_true", help="burn the checker on a copy and exit")
    ap.add_argument("--root", default=str(ROOT), help="the repository (default: this checkout)")
    sub = ap.add_subparsers(dest="cmd")

    def authoring(p):
        p.add_argument("--key", help="seed file of the signing key (or WARRANT_CLAIMS_KEY)")
        p.add_argument("--actor", default=AUTHOR)
        p.add_argument("--residual", action="append", default=[], help="what this claim does not establish")
        return p

    p = authoring(sub.add_parser("add", help="author claims from a stanza"))
    p.add_argument("--stanza", help="JSON stanza or list: {id, text, witnesses, mutants, informative, residual, because}")
    p.add_argument("--id")
    p.add_argument("--text")
    p.add_argument("--witness", action="append", default=[], help="<test file>:<case>, repeatable or comma-separated")
    p.add_argument("--mutant", action="append", default=[])
    p.add_argument("--informative", help="the reason this sentence is not normative")
    p.add_argument("--because")
    p = authoring(sub.add_parser("supersede", help="replace a claim's statement"))
    p.add_argument("--id", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--because", required=True)
    p.add_argument("--witness", action="append", default=[])
    p.add_argument("--mutant", action="append", default=[])
    p.add_argument("--informative")
    p = authoring(sub.add_parser("retire", help="retire a claim with counter-evidence"))
    p.add_argument("--id", required=True)
    p.add_argument("--because", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--counter", help="record or blob id of the counter-evidence, already in the store")
    g.add_argument("--counter-file", help="a file to store as the counter-evidence blob")
    sub.add_parser("project", help="regenerate SPEC-CLAIMS.md")
    p = sub.add_parser("check", help="CI: refuse any disagreement")
    p.add_argument("--base", help="the revision whose claims must survive (default: origin/master)")
    p.add_argument("--no-base", action="store_true")
    p = sub.add_parser("keygen", help="make an author key: seed outside the repository, public key in the trust")
    p.add_argument("--out", required=True)
    p.add_argument("--actor", default=AUTHOR)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    repo = Repo(a.root)
    if a.cmd is None:
        ap.print_help()
        return 2
    try:
        if a.cmd == "project":
            repo.projection.write_text(render(repo))
            return 0
        if a.cmd == "check":
            return cmd_check(repo, a)
        {"add": cmd_add, "supersede": cmd_supersede, "retire": cmd_retire, "keygen": cmd_keygen}[a.cmd](repo, a)
        return 0
    except Refused as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
