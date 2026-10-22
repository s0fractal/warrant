#!/usr/bin/env python3
"""SPEC claims as Warrant 2 records (pilot W; SPEC.md generated since W5).

The sentences of SPEC.md are claims filed as ordinary Warrant 2 records in this
repository's own store, `.warrant/store/` (records/<id>.json, blobs/<sha256>).
The records are the source. SPEC.md and SPEC-CLAIMS.md are views generated from
them by `project`, and `check` refuses either file when it says anything else:
nothing in SPEC.md is written by hand.

A claim is a `duty` (holder: the author; owed_to: readers; condition: attest;
accept_by: the reviewer) whose statement is the sentence, with an ATTESTED
`transition` that discharges it. The transition's evidence is one claim blob
carrying the sentence, its witness cases (tests/<file>_test.py) and its mutants
(tests/mutants.py, ids M…, or tests/agent_mutants.py, ids A…); its `established`
repeats the sentence. A sentence with no witness or no mutant is filed UNBACKED:
the transition closes nothing and opens the question, and the blob says why it is
open (`reason`). UNBACKED is an allowed status, listed in SPEC-CLAIMS.md as an open
question. A claim that was BACKED at the base revision and is UNBACKED now needs a
proof of the loss: its backing was already broken at the base (a cited case or
mutant absent there; removing it in the same change as the downgrade is refused),
or a transition after it cites a counter blob (warrant-claims/counter@1: a patch that
is confined to the code the claim's own mutants alter (scopes compared by AST), under which every cited witness
still passes and some case fails), directly or through a challenge against the
replaced claim, and `check` replays that blob. An informative sentence is
a transition with no duty, its reason in the blob. A supersession is a transition
whose `supersedes` names the claim it replaces. A retirement is a `challenge`
carrying the counter-evidence plus a transition superseding the claim. Nothing is
ever deleted.

What SPEC.md holds besides sentences is one more record: the **document**, an
ATTESTED transition with no duty whose single evidence blob
(warrant-claims/document@1) lists SPEC.md's parts in order: headings, references
to claims (each with the whitespace layout it had when filed) and the literal
gaps between them, which hold only spaces and line breaks and, at a line's start,
a list marker (`- `, `3. `) or a table rule (`| --- | --- |`). A new version supersedes the
previous one. A claim renders in its recorded layout while its text is the one
that layout was taken from; a changed or new sentence is filled to 80 columns
(unwrapped inside a fence or a table row); a retired one is left out.

    python3 tools/claims.py keygen --out SEED            # once per author; the seed stays out of git
    python3 tools/claims.py add --key SEED --stanza STANZAS.json
    python3 tools/claims.py add --key SEED --id SPEC-4.2-9 --text '...' --after SPEC-4.2-8 \
        --witness contract_test:H1 --mutant M01           # a new sentence names its position
    python3 tools/claims.py add --key SEED --id SPEC-1-6 --text '...' --after SPEC-1-5 --paragraph \
        --unbacked-because '...'
    python3 tools/claims.py supersede --key SEED --id SPEC-4.2-3 --text '...' --because '...'
    python3 tools/claims.py supersede --key SEED --id SPEC-7-1 --text '...' --because '...' \
        --unbacked-because '...' --counter-file COUNTER.json --challenge   # a BACKED claim losing its backing
    python3 tools/claims.py retire --key SEED --id SPEC-4.2-3 --because '...' --counter HEX
    python3 tools/claims.py project                      # regenerate SPEC.md and SPEC-CLAIMS.md
    python3 tools/claims.py check [--base REV | --no-base]
    python3 tools/claims.py --selftest                   # every refusal of `check`, burned on a copy
    python3 tools/claims.py migrate --key SEED --because '...'   # once (W5): the first document, from SPEC.md
    python3 tools/claims.py heading --key SEED --section 4.2 --because '...'   # after changing that pin

A claim's text is whitespace-normalized: runs of whitespace compare as one space.
Refusals are printed one per line as `REFUSED <CODE> <detail>`.
"""
import argparse
import ast
import concurrent.futures
import copy
import difflib
import hashlib
import importlib.util
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(ROOT))

import warrant as W                          # noqa: E402
from warrant import engine as E              # noqa: E402
from warrant import jcs as C                 # noqa: E402
from warrant import records as R             # noqa: E402
from warrant import store as S               # noqa: E402
from warrant.store import Snapshot, Store, Trust   # noqa: E402

AUTHOR = "claude"
CLAIM, RETIRE = "warrant-claims/claim@1", "warrant-claims/retire@1"
PINS_VERSION = "warrant-claims/pins@1"
ID_RE = re.compile(r"^SPEC-([0-9]+(?:\.[0-9]+)*)-([1-9][0-9]*)\Z")    # \Z: `$` admits a trailing newline
TEST_RE = re.compile(r"^[a-z][a-z0-9_]*_test\Z")
HEADING = re.compile(r"^#+ ([0-9]+(?:\.[0-9]+)*)\.? ")
RESIDUE_OK = frozenset(" |-.0123456789")    # layout characters: table rules, list markers, numbers
BACKED_RESIDUAL = ("this record cites its witness cases and mutants and does not run them; "
                   "CI runs the suites and tests/mutants.py before tools/claims.py check")
UNBACKED_RESIDUAL = "UNBACKED: no witness case or no mutant cites this sentence yet"
CLAIM_FIELDS = ("schema", "id", "source", "section", "text", "kind", "duty", "witnesses", "mutants",
                "reason", "because", "previous")
RETIRE_FIELDS = ("schema", "id", "because", "counter", "challenge", "previous")
PREVIOUS_FIELDS = ("transition", "duty", "statement_sha256")
# The mutant harnesses and the id prefix each one owns: an id resolves in exactly one of them.
HARNESSES = (("mutants.py", "M"), ("agent_mutants.py", "A"))
HARNESS_PACKAGE = {"mutants.py": "warrant", "agent_mutants.py": "warrant_agent"}
COUNTER = "warrant-claims/counter@1"
COUNTER_FIELDS = ("counter", "claim", "against", "patch", "passes", "fails", "why")
# The document (W5): SPEC.md's parts in order. A literal gap carries layout only, never words.
DOCUMENT = "warrant-claims/document@1"
DOCUMENT_FIELDS = ("schema", "source", "parts", "because", "previous")
DOCUMENT_PREVIOUS = ("transition", "sha256")
DOCUMENT_RESIDUAL = "the document orders and lays out the claims; it states no rule"
LITERAL_OK = RESIDUE_OK | {"\n"}
# A literal gap: spaces up to its first line break; after each line break, an indentation
# and at most a list marker ("- ", "12. "), or a table rule. No digit can touch a sentence.
LITERAL_LINE = re.compile(r"^(?: *(?:- |[0-9]{1,3}\. )?|\| ---(?: \| ---)* \|)\Z")
# A heading line: one to six #, a space, a title with no control character and no
# space at either end. \Z, not $: `$` admits a trailing newline.
HEADING_LINE = re.compile(r"^#{1,6} [^\x00-\x20\x7f-\x9f](?:[^\x00-\x1f\x7f-\x9f]*[^\x00-\x20\x7f-\x9f])?\Z")
GAP_RUN = re.compile(r"^[ \n]+\Z")
PREAMBLE = "0"              # the section before the first numbered heading
WIDTH = 80                  # the fill width of a sentence whose recorded layout no longer applies
GONE = "\x00"               # placeholder of a retired sentence while SPEC.md is rendered


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

    def mutants(self):
        """{id: (harness file, test file, [target cases])} from every harness of HARNESSES.
        Also sets `twice` (an id defined twice in one harness), `collide` (an id defined in
        more than one harness) and `misprefixed` ({id: harness} for an id without its
        harness's prefix)."""
        if self._mutants is None:
            out, twice, seen, misprefixed, edits = {}, set(), {}, {}, {}
            for name, prefix in HARNESSES:
                path = self.tests / name
                if not path.is_file():
                    continue
                spec = importlib.util.spec_from_file_location(f"claims_{path.stem}", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                ids = [m[0] for m in mod.MUTANTS]
                twice |= {i for i in ids if ids.count(i) > 1}
                for m in mod.MUTANTS:
                    seen.setdefault(m[0], set()).add(name)
                    if not m[0].startswith(prefix):
                        misprefixed[m[0]] = name
                    out.setdefault(m[0], (name, m[4], list(m[5])))
                    edits.setdefault(m[0], (f"{HARNESS_PACKAGE[name]}/{m[1]}", list(m[3])))
            self.twice, self.misprefixed = twice, misprefixed
            self.collide = {i for i, names in seen.items() if len(names) > 1}
            self._mutants, self.mutant_edits = out, edits
        return self._mutants

    def harness_problems(self):
        """(code, detail) for ids that do not resolve in exactly one harness."""
        try:
            self.mutants()
        except Exception as e:      # noqa: BLE001
            return [("MUTANTS_UNREADABLE", f"{type(e).__name__}: {e}")]
        prefixes = dict(HARNESSES)
        return ([("MUTANT_ID_COLLISION", f"{i} is defined in more than one of tests/mutants.py, tests/agent_mutants.py")
                 for i in sorted(self.collide)]
                + [("MUTANT_ID_PREFIX", f"{i} is in tests/{h}, whose ids start with {prefixes[h]}")
                   for i, h in sorted(self.misprefixed.items())])

    def mutant_scopes(self, mid):
        """The scopes (file, function) mutant `mid` changes, from its own (old, new) edits
        applied to the file as it is now; empty when its edits no longer apply."""
        self.mutants()
        path, edits = self.mutant_edits.get(mid, (None, ()))
        f = self.root / path if path else None
        if f is None or not f.is_file():
            return set()
        old = new = f.read_text()
        for o, n in edits:
            if new.count(o) != 1:
                return set()
            new = new.replace(o, n)
        try:
            return changed_scopes(path, old, new)
        except SyntaxError:
            return set()

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
        return out + [("MUTANTS_UNREADABLE", f"{type(e).__name__}: {e}")]
    for mid in mutants:
        if mid not in known:
            out.append(("UNKNOWN_MUTANT", f"neither tests/mutants.py nor tests/agent_mutants.py has a mutant {mid}"))
            continue
        harness, test, targets = known[mid]
        if mid in repo.twice:
            out.append(("DUPLICATE_MUTANT_ID", f"tests/{harness} defines {mid} more than once"))
            continue
        if mid in repo.collide:
            out.append(("MUTANT_ID_COLLISION", f"{mid} is defined in more than one harness; it names no one mutant"))
            continue
        if mid in repo.misprefixed:
            out.append(("MUTANT_ID_PREFIX", f"{mid} is in tests/{harness}, whose ids start with {dict(HARNESSES)[harness]}"))
            continue
        missing = [t for t in targets if not (TEST_RE.match(test) and repo.has_case(test, t))]
        if missing or not targets:
            out.append(("MUTANT_TARGET_UNKNOWN", f"{mid} targets {test} {','.join(missing) or '(nothing)'}, "
                        "which is not a case of an existing test file"))
            continue
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


_AUTH = {}


def authentic(snap, trust):
    """Snapshot.authentic, memoized per (record id, record bytes, trust bindings): one command
    builds many Models over the same records, and each signature needs checking once."""
    tk = hashlib.sha256(repr(sorted(trust.keys.items())).encode()).digest()
    good, bad = {}, {}
    for rid, data in sorted(snap.records.items()):
        k = (rid, hashlib.sha256(data).digest(), tk)
        if k not in _AUTH:
            _AUTH[k] = S._authenticate(rid, data, trust)
        why, rec = _AUTH[k]
        if why:
            bad[rid] = why
        else:
            good[rid] = rec
    return good, bad


class Model:
    """The claims a snapshot holds under a trust, and what is wrong with them."""

    def __init__(self, snap, trust):
        self.snap = snap
        self.recs, self.bad = authentic(snap, trust)
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
        if not (isinstance(doc["text"], str) and doc["text"] and doc["text"] == norm(doc["text"])
                and not any(unicodedata.category(c) == "Cc" for c in doc["text"])):
            return "text must be a non-empty whitespace-normalized string with no control character"
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
        if doc["kind"] != "normative":
            return "kind must be normative or informative"
        if doc["reason"] is not None and (doc["witnesses"] and doc["mutants"] or not (isinstance(doc["reason"], str) and doc["reason"])):
            return "a backed claim has no reason; an unbacked one says why it is open in a non-empty reason"
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


# ---------------------------------------------------------------- the document (W5)

class Document:
    """The document records a snapshot holds: transitions whose single evidence blob is
    a DOCUMENT blob. `current` is the one no other document version supersedes (or None);
    `problems` lists malformed versions and forks."""

    def __init__(self, model):
        self.model = model
        self.nodes, self.problems = {}, []
        for rid, r in sorted(model.recs.items()):
            if r["type"] != "transition":
                continue
            heads = [h for h in r["body"]["evidence"] for d in [model.snap.json_blob(h)]
                     if isinstance(d, dict) and d.get("schema") == DOCUMENT]
            if not heads:
                continue
            doc = model.snap.json_blob(heads[0])
            code, why = self._shape(r, heads, doc)
            if why:
                self.problems.append((code, f"document transition {rid[:12]}: {why}"))
                continue
            self.nodes[rid] = (r, heads[0], doc)
        for rid, (r, h, doc) in list(self.nodes.items()):
            prev = doc["previous"]
            if prev is None:
                continue
            p = self.nodes.get(prev["transition"])
            if p is None or p[1] != prev["sha256"]:
                self.problems.append(("STRUCTURE", f"document transition {rid[:12]}: its previous version is not "
                                                   "a document transition of this store with that blob"))
                del self.nodes[rid]
        replaced = {s for r, _, _ in self.nodes.values() for s in r["body"]["supersedes"]}
        cur = sorted((rid for rid in self.nodes if rid not in replaced), key=lambda rid: (self.nodes[rid][0]["at"], rid))
        if len(cur) > 1:
            self.problems.append(("DOCUMENT_FORK", f"{len(cur)} current document versions: "
                                  + ", ".join(rid[:12] for rid in cur)))
        self.tid = cur[-1] if cur else None
        self.current = self.nodes[self.tid][2] if cur else None

    def _shape(self, r, heads, doc):
        """(code, why) when this transition is not a well-formed document version, else (None, None)."""
        b = r["body"]
        if len(heads) != 1 or b["evidence"] != heads:
            return "STRUCTURE", "a document transition carries its document blob and nothing else as evidence"
        if b["basis"] != "ATTESTED" or b["closes"] or b["established"] or b["opened"]:
            return "STRUCTURE", "a document transition is ATTESTED and closes, establishes and opens nothing"
        if set(doc) != set(DOCUMENT_FIELDS) or doc["source"] != "SPEC.md":
            return "STRUCTURE", f"document blob members are not {list(DOCUMENT_FIELDS)} with source SPEC.md"
        prev = doc["previous"]
        if prev is not None and not (isinstance(prev, dict) and set(prev) == set(DOCUMENT_PREVIOUS)
                                     and all(isinstance(prev[k], str) for k in DOCUMENT_PREVIOUS)):
            return "STRUCTURE", "previous must be null or {transition, sha256}"
        if not (isinstance(doc["because"], str) and doc["because"]):
            return "STRUCTURE", "every document version says because, in a non-empty string"
        if b["supersedes"] != ([] if prev is None else [prev["transition"]]):
            return "STRUCTURE", "supersedes does not name exactly its previous version"
        parts = doc["parts"]
        if not (isinstance(parts, list) and parts):
            return "STRUCTURE", "parts must be a non-empty list"
        for i, p in enumerate(parts):
            if isinstance(p, str):
                if not p:
                    return "STRUCTURE", f"part {i} is an empty literal"
                if not literal_ok(p):
                    return "DOCUMENT_LITERAL", (f"part {i} is the literal {p[:60]!r}: a gap holds spaces and line breaks, "
                                                "and at a line's start a list marker or a table rule; words are claims")
            elif isinstance(p, dict) and set(p) == {"heading"}:
                if not (isinstance(p["heading"], str) and HEADING_LINE.match(p["heading"])):
                    return "STRUCTURE", f"part {i}: {str(p['heading'])[:60]!r} is not a heading line"
            elif isinstance(p, dict) and set(p) == {"claim", "layout"}:
                if not (isinstance(p["claim"], str) and ID_RE.match(p["claim"])):
                    return "STRUCTURE", f"part {i}: {str(p['claim'])[:60]!r} is not a claim id"
                why = _layout_shape(p["layout"])
                if why:
                    return "STRUCTURE", f"part {i} ({p['claim']}): {why}"
            else:
                return "STRUCTURE", f"part {i} is not a literal, {{heading}} or {{claim, layout}}"
        return None, None

    def problems_with(self, pins):
        """(code, detail) for headings the pins do not name, references that do not match
        the claims, and claims left out.

        Headings are pinned (AMEND 1 of #166): `.warrant/claims.json` maps each pinned
        section to its exact heading line, the preamble ("0") to the document's title. A
        heading's words are free text that no witness backs, so the document may hold only
        those lines, each once, in the pinned order; a changed or new heading is a reviewed
        pin change first, then a document version."""
        out, seen, section = [], {}, PREAMBLE
        headings = pins.get("headings", {})
        order = {sec: k for k, sec in enumerate(pins["sections"])}
        headed, last = {}, -1
        model = self.model
        for i, p in enumerate(self.current["parts"]):
            if isinstance(p, str):
                continue
            if "heading" in p:
                line = p["heading"]
                sec = heading_section(line, headings)
                if sec is None:
                    out.append(("DOCUMENT_HEADING", f"part {i}: {line[:80]!r} is neither a numbered heading nor the pinned title"))
                elif sec not in headings:
                    out.append(("DOCUMENT_HEADING", f"part {i}: {line[:80]!r} heads §{sec}, which .warrant/claims.json pins no heading for"))
                elif line != headings[sec]:
                    out.append(("DOCUMENT_HEADING", f"part {i}: {line[:80]!r} is not the pinned heading of §{sec}, {headings[sec][:80]!r}"))
                elif sec in headed:
                    out.append(("DOCUMENT_HEADING", f"part {i}: a second heading of §{sec} (the first is part {headed[sec]})"))
                elif order.get(sec, -1) < last:
                    out.append(("DOCUMENT_HEADING", f"part {i}: the heading of §{sec} comes after a later section's"))
                else:
                    headed[sec] = i
                    last = order.get(sec, last)
                    section = sec
                continue
            cid = p["claim"]
            if cid in seen:
                out.append(("DOCUMENT_CLAIM_TWICE", f"{cid} is part {seen[cid]} and part {i}"))
                continue
            seen[cid] = i
            if cid not in model.by_id:
                out.append(("DOCUMENT_UNKNOWN_CLAIM", f"part {i} names {cid}, which no claim record states"))
            elif ID_RE.match(cid).group(1) != section:
                out.append(("DOCUMENT_SECTION", f"part {i} puts {cid} under the heading of §{section}"))
        for cid, n in sorted(model.current.items(), key=lambda kv: id_key(kv[0])):
            if not n.retired and cid not in seen:
                out.append(("CLAIM_NOT_IN_DOCUMENT", f"{cid} is a current claim and no part of the document places it"))
        for s in pins["sections"]:
            if s not in headings:
                out.append(("DOCUMENT_HEADING", f".warrant/claims.json pins §{s} and no heading for it"))
            elif s not in headed:
                out.append(("SECTION_MISSING", f"the document has no heading of §{s}"))
        return out


def heading_section(line, headings):
    """The section a heading line heads: its number, PREAMBLE for the pinned title, else None."""
    m = HEADING.match(line)
    return m.group(1) if m else (PREAMBLE if line == headings.get(PREAMBLE) else None)


def literal_ok(text):
    """True iff `text` is a literal gap (LITERAL_LINE)."""
    first, *lines = text.split("\n")
    return set(first) <= {" "} and all(LITERAL_LINE.match(ln) for ln in lines)


def _layout_shape(layout):
    if layout is None:
        return None
    if not (isinstance(layout, dict) and set(layout) == {"sha256", "gaps"} and isinstance(layout["sha256"], str)
            and R.HEX64.match(layout["sha256"]) and isinstance(layout["gaps"], list)):
        return "layout must be null or {sha256: hex64, gaps: [[index, run]…]}"
    last = -1
    for g in layout["gaps"]:
        if not (isinstance(g, list) and len(g) == 2 and type(g[0]) is int and g[0] > last
                and isinstance(g[1], str) and GAP_RUN.match(g[1]) and g[1] != " "):
            return "a layout gap is [index, run]: indices ascending, runs of spaces and line breaks other than one space"
        last = g[0]
    return None


def lay_out(text, layout, before):
    """The sentence `text` as SPEC.md shows it, after the rendered text `before`: in its
    recorded layout while `text` is the sentence that layout was taken from (and every
    gap index falls inside it), else filled (fill)."""
    words = text.split(" ")
    if layout is not None and layout["sha256"] == sha(text) and all(i < len(words) - 1 for i, _ in layout["gaps"]):
        runs = [" "] * (len(words) - 1)
        for i, run in layout["gaps"]:
            runs[i] = run
        return words[0] + "".join(r + w for r, w in zip(runs, words[1:]))
    return fill(words, before, layout)


def fill(words, before, layout=None):
    """Words joined by single spaces, broken before a word that would pass column WIDTH and
    continued under the current line's indentation and list marker; never broken inside a
    fenced block or a table row (a line break there would change what the line says). In a
    fenced block the recorded run after the first word is kept, so a field line stays aligned."""
    line = before[before.rfind("\n") + 1:]
    fenced = sum(ln.startswith("```") for ln in before.split("\n")[:-1]) % 2 == 1
    if fenced:
        first = next((r for i, r in (layout or {}).get("gaps", []) if i == 0 and "\n" not in r), " ")
        return words[0] + (first + " ".join(words[1:]) if len(words) > 1 else "")
    if line.lstrip(" ").startswith("|"):
        return " ".join(words)
    indent = " " * len(re.match(r" *(?:[-*] |[0-9]+\. )?", line).group(0))
    out, col = words[0], len(line) + len(words[0])
    for w in words[1:]:
        if col + 1 + len(w) > WIDTH and col > len(indent):
            out, col = out + "\n" + indent, len(indent)
        else:
            out, col = out + " ", col + 1
        out, col = out + w, col + len(w)
    return out


def render_spec(model, document):
    """SPEC.md: the document's parts in order, each claim reference as its current
    sentence (lay_out); a retired claim is left out (drop_gone)."""
    s = ""
    for p in document["parts"]:
        if isinstance(p, str):
            s += p
        elif "heading" in p:
            s += p["heading"]
        else:
            n = model.current.get(p["claim"])
            s += GONE if n is None or n.retired else lay_out(n.doc["text"], p["layout"], s)
    return drop_gone(s)


def drop_gone(s):
    """Remove each retired sentence's placeholder. Alone on its line (nothing else there but
    layout characters), the line goes, and a blank line left doubled becomes one; sharing a
    line with other text, the placeholder goes with one adjacent space."""
    while GONE in s:
        pos = s.index(GONE)
        ls, le = s.rfind("\n", 0, pos) + 1, s.find("\n", pos)
        le = len(s) if le < 0 else le
        rest = s[ls:pos] + s[pos + 1:le]
        if GONE not in rest and set(rest) <= LITERAL_OK:
            if le < len(s):
                s = s[:ls] + s[le + 1:]
                if s[max(0, ls - 2):ls] == "\n\n" and s[ls:ls + 1] == "\n":
                    s = s[:ls] + s[ls + 1:]
            else:
                s = s[:max(0, ls - 1)]
                s = s.rstrip("\n") + "\n" if s else s
        elif s[pos + 1:pos + 2] == " ":
            s = s[:pos] + s[pos + 2:]
        elif s[pos - 1:pos] == " ":
            s = s[:pos - 1] + s[pos + 1:]
        else:
            s = s[:pos] + s[pos + 1:]
    return s


def parse_spec(text, model):
    """Migration only (W5, once): the parts that reproduce `text` from the current claims,
    or raise Refused. Each section's text is matched against that section's claims, at
    each point the claim that starts earliest (then the longest, then the lowest id),
    where only layout characters lie between; every claim must be placed and nothing
    else may remain. The caller still renders the parts and compares bytes: this
    reader is trusted with nothing (PATTERNS.md: never parse Markdown to find claims)."""
    by_sec = {}
    for n in model.current.values():
        if not n.retired:
            by_sec.setdefault(n.doc["section"], []).append(n)
    parts, section, pos = [], PREAMBLE, 0
    lines = text.split("\n")
    chunks, buf, at = [], [], 0          # [(section, body text) | ("#", heading line)]
    for k, line in enumerate(lines):
        end = "\n" if k < len(lines) - 1 else ""
        if line.startswith("#"):
            chunks.append((section, "".join(buf)))
            buf = [end]
            chunks.append(("#", line))
            m = HEADING.match(line)
            section = m.group(1) if m else section
        else:
            buf.append(line + end)
    chunks.append((section, "".join(buf)))
    placed = set()
    for sec, body in chunks:
        if sec == "#":
            if not HEADING_LINE.match(body):
                raise Refused(f"{body[:60]!r} is not a heading line")
            parts.append({"heading": body})
            continue
        todo = [n for n in by_sec.get(sec, []) if n.id not in placed]
        pos = 0
        while True:
            best = None
            for n in todo:
                words = n.doc["text"].split(" ")
                m = re.compile(r"[ \n]+".join(re.escape(w) for w in words)).search(body, pos)
                if m is None or not literal_ok(body[pos:m.start()]):
                    continue
                key = (m.start(), -len(m.group(0)), id_key(n.id))
                if best is None or key < best[0]:
                    best = (key, n, m)
            if best is None:
                break
            _, n, m = best
            if m.start() > pos:
                parts.append(body[pos:m.start()])
            runs = re.findall(r"[ \n]+", m.group(0))
            gaps = [[i, r] for i, r in enumerate(runs) if r != " "]
            parts.append({"claim": n.id, "layout": {"sha256": sha(n.doc["text"]), "gaps": gaps}})
            placed.add(n.id)
            todo.remove(n)
            pos = m.end()
        rest = body[pos:]
        if not literal_ok(rest):
            raise Refused(f"§{sec} has text no current claim of §{sec} places: {norm(rest)[:120]!r}")
        if rest:
            parts.append(rest)
    left = sorted((n.id for ns in by_sec.values() for n in ns if n.id not in placed), key=id_key)
    if left:
        raise Refused(f"claims not found in SPEC.md: {', '.join(left[:10])}")
    return parts


# ---------------------------------------------------------------- the view

def assessment(snap, trust):
    recs, _ = authentic(snap, trust)
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
    secs = ", ".join("the preamble" if s == PREAMBLE else f"§{s}" for s in pins["sections"])
    out = [
        "# SPEC claims (generated view)", "",
        "Generated by `python tools/claims.py project` from the Warrant 2 records in",
        "`.warrant/store/`. **The records are the source; this file is a view.**",
        "`python tools/claims.py check` refuses it when it differs from what the records",
        "say. SPEC.md is generated from the same records. Edit neither by hand: add,",
        "supersede or retire the claim, then regenerate both (README.md, \"Changing a",
        "normative sentence\").", "",
        f"Sections {secs} of SPEC.md · sentences {len(pins['sentences'])} · backed {count['BACKED']} · "
        f"unbacked {count['UNBACKED']} · informative {count['INFORMATIVE']} · retired {len(retired)} · "
        f"records {len(snap.records)} · blobs {len(snap.blobs)}", "",
        "A witness is a case of `tests/<file>.py`; a mutant is an entry of `tests/mutants.py`",
        "(ids M…) or `tests/agent_mutants.py` (ids A…) that must make one of the cited cases",
        "fail. An UNBACKED sentence is an open question, listed below with the reason it is",
        "open; it closes nothing and establishes nothing. *Disposition* is Warrant's own",
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
    opened = [n for n in live if n.status == "UNBACKED"]
    out += ["", "## Open questions", "",
            "A claim that was BACKED and lost its backing cites a counter blob that `check` replayed: under its",
            "patch, which changes only code the claim's own mutants change (compared by AST), at least one case",
            "fails and every witness of the claim passes. The witnesses are blind to a change in the code the",
            "sentence is about.",
            "The reason below is the filer's thesis; the replay is what admitted the loss.", ""]
    if opened:
        out += ["| ID | Statement | Why it is open | Claim |", "| --- | --- | --- | --- |"]
        out += [f"| {n.id} | {cell(n.doc['text'])} | {cell(n.doc['reason'] or '(no reason given)')} | `{n.tid[:12]}` |"
                for n in opened]
    else:
        out.append("None.")
    doc = Document(model)
    if doc.current is not None:
        heads = [p["heading"] for p in doc.current["parts"] if isinstance(p, dict) and "heading" in p]
        out += ["", "## Document", "",
                f"SPEC.md is rendered from document version `{doc.tid[:12]}` ({len(doc.current['parts'])} parts). Its headings",
                "are not claims: each is pinned, line for line, in `.warrant/claims.json`, and the document may hold",
                "only those lines, once each and in order. A title is free text that no witness backs, so a",
                "rule-shaped title is a review matter; the pin makes every change of one a reviewed diff.", ""]
        out += [f"- `{h}`" for h in heads]
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
    def key(c):        # letters, then the number, then the rest: B2 < B2a < B10; P-edge has no number
        m = re.match(r"([^0-9]*)([0-9]*)(.*)", c)
        return m.group(1), int(m.group(2) or 0), c
    return [(t, sorted(cs, key=key)) for t, cs in sorted(groups.items())]


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
    out += repo.harness_problems()
    pins = repo.pins()
    for cid, n in sorted(model.current.items(), key=lambda kv: id_key(kv[0])):
        if n.retired:
            continue
        sec = n.doc["section"]
        out += [(code, f"{cid}: {why}") for code, why in witness_problems(repo, n.doc["witnesses"], n.doc["mutants"])]
        if n.kind == "normative" and not n.backed and not n.doc["reason"]:
            out.append(("UNBACKED_WITHOUT_REASON", f"{cid}: an unbacked claim must say why it is open (--unbacked-because)"))
        if cid in model.challenges:
            out.append(("CHALLENGED", f"{cid}: standing challenge {', '.join(c[:12] for c in model.challenges[cid])}"
                        " against the current claim; supersede or retire it"))
        if sec in pins["sections"] and cid not in pins["sentences"]:
            out.append(("UNPINNED_CLAIM", f"{cid}: a current claim of §{sec} that .warrant/claims.json does not pin"))
    for cid, kind in sorted(pins["sentences"].items(), key=lambda kv: id_key(kv[0])):
        n = model.current.get(cid)
        if n is None:
            out.append(("UNCLAIMED", f"{cid}: pinned, and no claim record states it"))
        elif n.retired:
            out.append(("PINNED_RETIRED", f"{cid}: pinned, but its claim is retired"))
        elif n.kind != kind:
            out.append(("KIND_MISMATCH", f"{cid}: pinned {kind}, claimed {n.kind}"))
    # W5: SPEC.md is the document's rendering; nothing in it is written by hand.
    doc = Document(model)
    out += doc.problems
    if doc.current is None:
        out.append(("DOCUMENT_MISSING", "no document record lays out SPEC.md; see tools/claims.py migrate"))
    else:
        out += doc.problems_with(pins)
        want = render_spec(model, doc.current).encode()
        if not repo.spec.is_file():
            out.append(("SPEC_NOT_PROJECTION", "SPEC.md does not exist; run tools/claims.py project"))
        elif repo.spec.read_bytes() != want:
            out.append(("SPEC_NOT_PROJECTION", "SPEC.md is not the rendering of the records (edited by hand?); "
                        "run tools/claims.py project"))
    if not repo.projection.is_file():
        out.append(("PROJECTION_MISSING", "SPEC-CLAIMS.md does not exist; run tools/claims.py project"))
    elif repo.projection.read_bytes() != render(repo).encode():     # bytes: read_text() would turn \r\n into \n
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
    at_base = BaseTests(repo, rev)
    try:
        for cid in sorted(then.current, key=id_key):
            was, now = then.current[cid], model.current.get(cid)
            if was.backed and now is not None and not now.retired and now.kind == "normative" and not now.backed:
                lost = lost_backing(repo, model, now, at_base)
                if lost:
                    out.append((lost[0], f"{cid} is BACKED at {rev[:12]} and UNBACKED now: {lost[1]}"))
    finally:
        at_base.close()
    old_pins = json.loads(files[".warrant/claims.json"]) if ".warrant/claims.json" in files else {"sentences": {}}
    for cid in sorted(set(old_pins["sentences"]) - set(pins["sentences"]), key=id_key):
        n = model.current.get(cid)
        if n is None or not n.retired:
            out.append(("UNPINNED_WITHOUT_RETIREMENT", f"{cid} is pinned at {rev[:12]}; unpinning it needs its retirement record"))
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


def _strip_docstring(body):
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def _hollow(node, prefix, out):
    """A copy of `node` with docstrings removed and every function inside it replaced by a
    marker; each function's own hollow dump goes into `out` under its qualified name."""
    node = copy.copy(node)
    for field, value in ast.iter_fields(node):
        if isinstance(value, list):
            if field == "body" and isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                value = _strip_docstring(value)
            new = []
            for v in value:
                if isinstance(v, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    q = prefix + v.name
                    out[q] = ast.dump(_hollow(v, q + ".", out))
                    new.append(ast.Expr(ast.Name(id=f"<def {q}>", ctx=ast.Load())))
                elif isinstance(v, ast.ClassDef):
                    new.append(_hollow(v, prefix + v.name + ".", out))
                else:
                    new.append(_hollow(v, prefix, out) if isinstance(v, ast.AST) else v)
            setattr(node, field, new)
        elif isinstance(value, ast.AST):
            setattr(node, field, _hollow(value, prefix, out))
    return node


def scope_dumps(src):
    """{scope: dump}: each function (qualified by its classes) and `<module>` (everything
    outside functions, classes' other statements included), as ast.dump without positions,
    comments, layout or docstrings. Raises SyntaxError if `src` does not parse."""
    out = {}
    out["<module>"] = ast.dump(_hollow(ast.parse(src), "", out))
    return out


def changed_scopes(path, old, new):
    """{(path, scope)} whose AST differs between `old` and `new` (scope_dumps): a comment,
    whitespace or a docstring changes no scope. Raises SyntaxError if `new` does not parse."""
    a, b = scope_dumps(old) if old else {}, scope_dumps(new)
    return {(path, k) for k in set(a) | set(b) if a.get(k) != b.get(k)}


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


def _replay_counter(repo, doc, p):
    if set(doc) != set(COUNTER_FIELDS):
        return f"members are not {list(COUNTER_FIELDS)}"
    if doc["claim"] != p.id or doc["against"] != p.tid:
        return f"it is against {doc['claim']!r} {str(doc['against'])[:12]}, not {p.id} {p.tid[:12]}"
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
    for line in doc["patch"].splitlines():
        if line.startswith(("--- ", "+++ ")):
            path = line[4:].split("\t")[0].strip()
            if path != "/dev/null" and not re.match(r"[ab]/(warrant|warrant_agent)/[A-Za-z0-9_./-]+\Z", path) or ".." in path:
                return f"the patch touches {path!r}, outside warrant/ and warrant_agent/"
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
        # Locality: the patch must alter code that one of the claim's own mutants alters. Those
        # mutants are the repository's statement of which code the sentence is about; a patch
        # elsewhere that breaks some case proves nothing about this claim's witnesses.
        files = {m.group(1) for m in re.finditer(r"^\+\+\+ b/(\S+)", doc["patch"], re.M)} | \
                {m.group(1) for m in re.finditer(r"^--- a/(\S+)", doc["patch"], re.M)}
        # A scope counts as changed only if its AST changes (no comments, layout or docstrings),
        # and every changed scope must be one the claim's mutants change: no foreign hunk can
        # supply the FAIL while a cosmetic or harmless local edit supplies the locality.
        touched = set()
        for f in sorted(files):
            if not f.endswith(".py"):
                return f"the patch changes {f}, which is not Python source"
            old = (repo.root / f).read_text() if (repo.root / f).is_file() else ""
            new = (tmp / f).read_text() if (tmp / f).is_file() else ""
            try:
                touched |= changed_scopes(f, old, new)
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
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
        self.pending = {}

    def model(self):
        """The store as filed, plus `pending`: blobs a command has read but not yet stored,
        so a refused command can be validated against them and leave the store unchanged."""
        snap = self.repo.snapshot()
        if self.pending:
            snap = Snapshot(snap.records, {**snap.blobs, **self.pending}, snap.misfiled)
        return Model(snap, self.repo.trust())

    def at(self):
        recs = self.model().recs
        return max([int(time.time())] + [r["at"] for r in recs.values()])

    def put(self, rtype, body, at):
        return self.store.put_record(R.record(rtype, self.actor, at, body), self.key)

    def _validate(self, cid, text, kind, witnesses, mutants, reason, unbacked_because, counter, previous):
        m = ID_RE.match(cid)
        if not m:
            raise Refused(f"{cid!r} is not SPEC-<section>-<n>")
        if not text or text != norm(text) or any(unicodedata.category(c) == "Cc" for c in text):
            raise Refused(f"{cid}: a sentence is non-empty text with no control character")
        if kind == "informative" and (witnesses or mutants or not reason or unbacked_because):
            raise Refused(f"{cid}: an informative sentence has a reason and cites no witnesses or mutants")
        backed = kind == "normative" and witnesses and mutants
        if kind == "normative" and not backed and not unbacked_because:
            raise Refused(f"{cid}: an unbacked sentence needs --unbacked-because (why it is open)")
        if backed and unbacked_because:
            raise Refused(f"{cid}: a backed sentence takes no --unbacked-because")
        if previous is not None and previous.backed and kind == "normative" and not backed \
                and not witness_problems(self.repo, previous.doc["witnesses"], previous.doc["mutants"]):
            model = self.model()
            cands = [c for h in counter for c in counter_candidates(model, h, previous)]
            whys = [why for c in cands for why in [replay_counter(self.repo, model.snap, c, previous)]]
            if not cands or all(whys):
                raise Refused(f"{cid} is BACKED; losing its backing needs a counter blob ({COUNTER}) that replays, "
                              f"via --counter-file or a challenge carrying it: "
                              + ("; ".join(whys) if cands else "none given"))
        bad = witness_problems(self.repo, witnesses, mutants) + [
            (c, w) for c, w in self.repo.harness_problems() if any(w.startswith(f"{x} ") for x in mutants)]
        if bad:
            raise Refused(f"{cid}: " + "; ".join(f"{c} {w}" for c, w in bad))

    def placement(self, cid, after=None, paragraph=False, because=None):
        """The document version that places a new sentence `cid` after claim `after`, as
        (parts, because), or None when `cid` is already placed or no document exists yet
        (before the migration). Raises Refused, writing nothing, when a new sentence names
        no position or a position that is not a placed claim of its own section."""
        doc = Document(self.model())
        if doc.current is None:
            return None
        parts = doc.current["parts"]
        at = [i for i, p in enumerate(parts) if isinstance(p, dict) and p.get("claim") == cid]
        if at:
            if after is not None:
                raise Refused(f"{cid} is already placed in SPEC.md; it keeps its position")
            return None
        if after is None:
            raise Refused(f"{cid} is a new sentence: name its position (--after <claim id> [--paragraph])")
        i = [k for k, p in enumerate(parts) if isinstance(p, dict) and p.get("claim") == after]
        if not i:
            raise Refused(f"{cid}: --after {after} is not a claim the document places")
        if ID_RE.match(after) is None or ID_RE.match(after).group(1) != ID_RE.match(cid).group(1):
            raise Refused(f"{cid}: --after {after} is in another section")
        k = i[0] + 1
        new = parts[:k] + ["\n\n" if paragraph else " ", {"claim": cid, "layout": None}] + parts[k:]
        return new, f"{cid} placed after {after}" + (" as a new paragraph" if paragraph else "") + (f": {because}" if because else "")

    def file_document(self, parts, because, at):
        """File a document version: an ATTESTED transition whose evidence is the document blob,
        superseding the current version if there is one."""
        doc = Document(self.model())
        prev = None if doc.current is None else {"transition": doc.tid, "sha256": doc.nodes[doc.tid][1]}
        h = self.store.put_json({"schema": DOCUMENT, "source": "SPEC.md", "parts": parts, "because": because,
                                 "previous": prev})
        return self.put("transition", R.transition("ATTESTED", [h], residual=[DOCUMENT_RESIDUAL],
                                                   supersedes=[prev["transition"]] if prev else []), at)

    def claim(self, cid, text, witnesses=(), mutants=(), reason=None, because=None, residual=(), previous=None,
              unbacked_because=None, counter=(), after=None, paragraph=False):
        """File one claim: (duty and) transition. `previous` is the Node it replaces, or None.
        `reason` makes it informative; `unbacked_because` says why a normative one is open;
        `counter` (ids already in the store) goes into the transition's evidence. A sentence
        the document does not place yet is placed after claim `after` (a new version of the
        document); everything is validated before anything is written."""
        text = norm(text)
        witnesses, mutants = sorted(set(witnesses)), sorted(set(mutants))
        kind = "informative" if reason else "normative"
        if self.validate:
            self._validate(cid, text, kind, witnesses, mutants, reason, unbacked_because, counter, previous)
        if previous is not None and not because:
            raise Refused(f"{cid}: replacing a claim needs --because")
        if previous is not None and previous.retired:
            raise Refused(f"{cid} is retired; a new sentence takes a new id")
        placed = self.placement(cid, after, paragraph, because if previous is None else None)
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
        prev = None if previous is None else {
            "transition": previous.tid, "duty": previous.doc["duty"], "statement_sha256": sha(previous.doc["text"])}
        backed = kind == "normative" and witnesses and mutants
        doc = {"schema": CLAIM, "id": cid, "source": "SPEC.md", "section": ID_RE.match(cid).group(1), "text": text,
               "kind": kind, "duty": duty, "witnesses": witnesses, "mutants": mutants,
               "reason": reason if kind == "informative" else None if backed else unbacked_because,
               "because": because if previous is not None else None, "previous": prev}
        h = self.store.put_json(doc)
        body = R.transition("ATTESTED", sorted({h} | set(counter)),
                            closes=[R.item(duty, "discharge", [h])] if backed else [],
                            established=[text] if backed else [],
                            residual=([BACKED_RESIDUAL] if backed else [UNBACKED_RESIDUAL] if kind == "normative" else [])
                            + list(residual),
                            opened=[] if backed or kind == "informative" else
                            [{"text": f"which witness case and which mutant back {cid}?", "scope": cid}],
                            supersedes=[previous.tid] if previous is not None else [])
        tid = self.put("transition", body, at)
        if placed:
            self.file_document(*placed, at)
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
             "residual": a.residual, "because": a.because, "unbacked_because": a.unbacked_because,
             "after": a.after, "paragraph": a.paragraph}]


def same_claim(n, s):
    extra = [x for x in n.rec["body"]["residual"] if x not in (BACKED_RESIDUAL, UNBACKED_RESIDUAL)]
    return (n.doc["witnesses"], n.doc["mutants"], n.doc["reason"], extra) == \
        (sorted(set(s.get("witnesses", ()))), sorted(set(s.get("mutants", ()))),
         s.get("informative") or s.get("unbacked_because"), list(s.get("residual", ())))


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
                           s.get("because"), s.get("residual", ()), previous=cur,
                           unbacked_because=s.get("unbacked_because"), counter=s.get("counter", ()),
                           after=s.get("after"), paragraph=bool(s.get("paragraph")))
        print(f"{s['id']}: {tid}")


def cmd_supersede(repo, a):
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    cur = author.model().current.get(a.id)
    if cur is None or cur.retired:
        raise Refused(f"{a.id}: no live claim to supersede")
    keep = a.informative is None and a.unbacked_because is None     # otherwise only what is given now
    wit = [w for x in a.witness for w in x.split(",") if w] or (cur.doc["witnesses"] if keep else [])
    mut = [m for x in a.mutant for m in x.split(",") if m] or (cur.doc["mutants"] if keep else [])
    counter = list(a.counter)
    if a.counter_file:
        data = counter_file_bytes(a.counter_file)
        author.pending[C.digest(data)] = data         # read, validated, stored only once the claim can be filed
        counter.append(C.digest(data))
    if a.challenge and not counter:
        raise Refused(f"{a.id}: --challenge needs --counter or --counter-file as its evidence")
    # Refuse before anything is written: a refused command leaves the store byte-identical.
    author.placement(a.id)
    author._validate(a.id, norm(a.text), "informative" if a.informative else "normative", sorted(set(wit)),
                     sorted(set(mut)), a.informative, a.unbacked_because, counter, cur)
    for data in author.pending.values():
        author.store.put_blob(data)
    author.pending = {}
    if a.challenge:
        # The dispute goes on record against the claim being replaced (its discharge item,
        # if it has one), so its closure cannot later be accepted as if nothing were found.
        # Against the last BACKED claim of the chain: its discharge item is the closure in dispute.
        model, target = author.model(), cur
        while not target.backed and target.doc["previous"] and target.doc["previous"]["transition"] in model.nodes:
            target = model.nodes[target.doc["previous"]["transition"]]
        item = 0 if target.rec["body"]["closes"] else None
        counter.append(author.put("challenge", R.challenge(target.tid, a.because, counter, item), author.at()))
    tid = author.claim(a.id, a.text, wit, mut, a.informative, a.because, a.residual, previous=cur,
                       unbacked_because=a.unbacked_because, counter=counter)
    print(f"{a.id}: {tid}")


def counter_file_bytes(path):
    """The blob bytes of a counter file: canonical JSON for a counter blob (so `check` can
    read it back), the file's bytes otherwise."""
    data = Path(path).read_bytes()
    try:
        doc = json.loads(data)
    except ValueError:
        return data
    return C.canon(doc) if isinstance(doc, dict) and doc.get("counter") == COUNTER else data


def cmd_retire(repo, a):
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    cur = author.model().current.get(a.id)
    if cur is None or cur.retired or not a.because:
        raise Refused(f"{a.id}: no live claim to retire, or no --because")   # before the counter-file is stored
    counter = a.counter or author.store.put_blob(Path(a.counter_file).read_bytes())
    print(f"{a.id}: retired by {author.retire(a.id, a.because, counter)}")


def cmd_migrate(repo, a):
    """W5, once: file the first document version, read from the hand-written SPEC.md, only if
    its rendering reproduces that file byte for byte. Afterwards SPEC.md is generated."""
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    model = author.model()
    if Document(model).current is not None:
        raise Refused("a document already lays out SPEC.md; SPEC.md is generated from the records now")
    text = repo.spec.read_text()
    parts = parse_spec(text, model)
    got = render_spec(model, {"parts": parts})
    if got != text:
        i = next((k for k, (x, y) in enumerate(zip(got, text)) if x != y), min(len(got), len(text)))
        raise Refused(f"the parts do not reproduce SPEC.md: first difference at character {i}: "
                      f"{got[max(0, i - 30):i + 30]!r} vs {text[max(0, i - 30):i + 30]!r}")
    print(f"document: {author.file_document(parts, a.because, author.at())} ({len(parts)} parts)")


def cmd_heading(repo, a):
    """A document version whose heading of §SECTION is the line .warrant/claims.json now pins
    for it: the reviewed pin change comes first, then this record, with a because."""
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    doc = Document(author.model())
    if doc.current is None:
        raise Refused("no document record lays out SPEC.md yet")
    want = author.pins.get("headings", {}).get(a.section)
    if want is None:
        raise Refused(f".warrant/claims.json pins no heading for §{a.section}")
    parts = copy.deepcopy(doc.current["parts"])
    pinned = author.pins.get("headings", {})
    at = [i for i, q in enumerate(parts) if isinstance(q, dict) and "heading" in q
          and heading_section(q["heading"], pinned) == a.section]
    if len(at) != 1:
        raise Refused(f"the document has {len(at)} headings of §{a.section}; this command changes one in place")
    if parts[at[0]]["heading"] == want:
        raise Refused(f"the heading of §{a.section} is already {want!r}")
    parts[at[0]] = {"heading": want}
    print(f"document: {author.file_document(parts, a.because, author.at())}")


def cmd_project(repo):
    model = Model(repo.snapshot(), repo.trust())
    doc = Document(model)
    if doc.current is None:
        raise Refused("no document record lays out SPEC.md (tools/claims.py migrate files the first)")
    repo.spec.write_bytes(render_spec(model, doc.current).encode())
    repo.projection.write_bytes(render(repo).encode())


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

_CASE_RUNNER = None


def _run_registered_case(i):
    return _CASE_RUNNER(i)


def selftest(jobs=1):
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
        for pkg in ("warrant", "warrant_agent"):     # a counter blob's patch is replayed against them
            if (ROOT / pkg).is_dir():
                shutil.copytree(ROOT / pkg, fix / pkg, ignore=shutil.ignore_patterns("__pycache__"))
        repo = Repo(fix)
        key = W.Key.generate()                    # an ephemeral second key for the claim author
        doc = C.loads(repo.trust_path.read_bytes())
        doc["keys"].append({"actor": AUTHOR, "public": key.public})
        repo.trust_path.write_bytes(C.canon(doc))
        # No automatic gc or maintenance: a detached repack after the commit would move the
        # fixture's objects while a case is made from it (run 39537906378).
        g_cfg = ["-c", "user.name=claims-selftest", "-c", "user.email=selftest@invalid", "-c", "commit.gpgsign=false",
                 "-c", "gc.auto=0", "-c", "maintenance.auto=false"]
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, *g_cfg, "commit", "-q", "-m", "base")
        base = git(repo, "rev-parse", "HEAD").decode().strip()
        model = Model(repo.snapshot(), repo.trust())
        live = sorted((n for n in model.current.values() if n.backed), key=lambda n: id_key(n.id))
        if len(live) < 2:
            print("FAIL  selftest: the repository's store has fewer than two backed claims to work on")
            return 1
        a, b = live[0], live[-1]
        # `e`: a claim whose witnesses are records_test cases and whose mutants live outside jcs.py, so a
        # counter patch to jcs.py replays for it (some case fails, its witnesses pass) yet is not local.
        e = next((n for n in live if n.doc["witnesses"] and all(w.startswith("records_test:") for w in n.doc["witnesses"])
                  and "records_test:E2" not in n.doc["witnesses"] and n.doc["mutants"]
                  and all(sc[0] != "warrant/jcs.py" for mid in n.doc["mutants"] for sc in repo.mutant_scopes(mid))
                  and all(repo.mutant_scopes(mid) for mid in n.doc["mutants"])), None)
        if e is None:
            print("FAIL  selftest: no claim backed by records_test whose mutants live outside jcs.py")
            return 1
        # `g`: a claim whose mutants all live in one function of engine.py (SPEC-4.1-6, M02 in
        # engine._transfer_effect, when present): the target of Codex's reproduction on 0590956.
        def one_engine_scope(n):
            scs = {sc for mid in n.doc["mutants"] for sc in repo.mutant_scopes(mid)}
            return len(scs) == 1 and next(iter(scs))[0] == "warrant/engine.py" and next(iter(scs))[1] != "<module>"
        g = next((n for n in live if n.id == "SPEC-4.1-6" and one_engine_scope(n)), None) or \
            next((n for n in live if n.doc["mutants"] and one_engine_scope(n)), None)
        if g is None:
            print("FAIL  selftest: no claim whose mutants all alter one engine.py function")
            return 1
        failures, ran = 0, []

        cases = []
        seed = work / "selftest.seed"
        seed.write_text(key.seed_hex() + "\n")

        def case(name, expect, mutate, also=None):
            """Register one case; all of them run later, `jobs` at a time (run_case).
            `mutate` may return a revision to check against instead of `base`; `also(r)`,
            when given, must hold as well (what the rendered files say)."""
            cases.append((name, expect, mutate, also))

        def run_case(i):
            """(ok, report line) of case `i`, on a clone of its own: cases share nothing but
            the read-only fixture, so they may run in parallel processes."""
            name, expect, mutate, also = cases[i]
            d = work / f"case-{i:03d}"
            # A clone through the pack protocol, never a copy of .git's files: copytree, and a
            # local clone (which copies objects/ too), fail with ENOENT if the fixture is
            # repacked meanwhile; --no-local reads objects through git, consistently.
            try:
                subprocess.run(["git", "-c", "gc.auto=0", "clone", "-q", "--no-local", str(fix), str(d)],
                               capture_output=True, check=True)
                r = Repo(d)
                against = mutate(r)
                against = against if isinstance(against, str) else base
                got = check(r, against)
                codes = {c for c, _ in got}
                ok = bool(((not got) if expect is None else expect in codes) and (also is None or also(r)))
                detail = f" | got {sorted(codes) or 'nothing'}: {got[:3]}"
            except Exception as ex:      # noqa: BLE001 -- a case that crashes is a failed case, not a crashed selftest
                ok, detail = False, f" | raised {type(ex).__name__}: {ex}"
            finally:
                shutil.rmtree(d, ignore_errors=True)
            what = "passes" if expect is None else f"refused {expect}"
            return ok, ("ok    " if ok else "FAIL  ") + f"{name}: {what}" + ("" if ok else detail)

        def author(r):
            return Author(r, key, AUTHOR, validate=False)

        def spec_edit(old, new):
            def f(r):
                r.spec.write_text(replace_wrapped(r.spec.read_text(), old, new))
            return f

        def reproject(r):
            m = Model(r.snapshot(), r.trust())
            doc = Document(m)
            if doc.current is not None:
                r.spec.write_bytes(render_spec(m, doc.current).encode())
            r.projection.write_bytes(render(r).encode())

        def spec_text(r):
            return norm(r.spec.read_text())

        def doc_version(change, because="selftest"):
            """File a document version whose parts are `change(parts)` of the current ones."""
            def f(r):
                au = author(r)
                parts = copy.deepcopy(Document(Model(r.snapshot(), r.trust())).current["parts"])
                au.file_document(change(parts), because, au.at())
                reproject(r)
            return f

        def part_of(parts, cid):
            return next(i for i, q in enumerate(parts) if isinstance(q, dict) and q.get("claim") == cid)

        def rebacked(witnesses, mutants, unbacked_because=None, counter=None, claim=None):
            def f(r):
                cid = (claim or a).id
                n = Model(r.snapshot(), r.trust()).current[cid]
                ev = counter(r, n) if counter else ()
                author(r).claim(cid, n.doc["text"], witnesses, mutants, because="selftest", previous=n,
                                unbacked_because=unbacked_because, counter=ev)
                reproject(r)
            return f

        def challenge_of(target):
            def f(r, n):
                au = author(r)
                return [au.put("challenge", R.challenge(target(n), "selftest: the witness passes without the rule",
                                                        [Store(r.store_dir).put_blob(b"selftest: failing case")], 0), au.at())]
            return f

        def junk_blob(r, n):
            return [Store(r.store_dir).put_blob(b"lol\n")]

        # A counter blob against claim `a`: a patch that admits floats (records_test E2 fails)
        # while every witness `a` cites still passes. Variants break one requirement each.
        floats_old, floats_new = "    if isinstance(v, int):\n", "    if isinstance(v, float):\n        return repr(v)\n    if isinstance(v, int):\n"

        # A patch to jcs._check_text: lone surrogates reach the encoder (records_test E3 fails), in a
        # function of the same file that no mutant of `a` alters (its mutants alter _scalar, _push_container).
        surrogates_old, surrogates_new = '        raise NotCanonical("lone surrogate")', "        pass"

        def counter_doc(r, n, edit=None, **kv):
            old_text, new_text = edit or (floats_old, floats_new)
            src = (r.root / "warrant" / "jcs.py").read_text()
            patch = "".join(difflib.unified_diff(src.splitlines(True), src.replace(old_text, new_text, 1).splitlines(True),
                                                 "a/warrant/jcs.py", "b/warrant/jcs.py"))
            doc = {"counter": COUNTER, "claim": n.id, "against": n.tid, "patch": patch,
                   "passes": sorted(n.doc["witnesses"]), "fails": ["records_test:E2"],
                   "why": "selftest: floats admitted while the cited witnesses still pass"}
            doc.update(kv)
            return doc

        def counter(**kv):
            def f(r, n):
                return [Store(r.store_dir).put_json(counter_doc(r, n, **kv))]
            return f

        def challenge_carrying(**kv):
            def f(r, n):
                au = author(r)
                h = Store(r.store_dir).put_json(counter_doc(r, n, **kv))
                return [au.put("challenge", R.challenge(n.tid, "selftest: the witnesses pass without the rule", [h], 0), au.at())]
            return f

        def outside_patch(r, n):
            doc = counter_doc(r, n)
            doc["patch"] = doc["patch"].replace("a/warrant/jcs.py", "a/tests/world.py").replace("b/warrant/jcs.py", "b/tests/world.py")
            return [Store(r.store_dir).put_json(doc)]

        def witness_gone_at_base(r):
            """The witness case is renamed away in a commit of its own, which becomes the base;
            the downgrade comes after it."""
            for w in a.doc["witnesses"]:
                test, _, cid = w.partition(":")
                pth = r.tests / f"{test}.py"
                pth.write_text(pth.read_text().replace(f'"{cid}"', f'"{cid}gone"'))
            git(r, "add", "-A")
            git(r, *g_cfg, "commit", "-q", "-m", "the witness leaves first")
            rev = git(r, "rev-parse", "HEAD").decode().strip()
            rebacked([], [], unbacked_because="selftest: its witness case was removed earlier")(r)
            return rev

        def head_of(parts, sec):
            return next(k for k, q in enumerate(parts) if isinstance(q, dict) and "heading" in q
                        and HEADING.match(q["heading"]) and HEADING.match(q["heading"]).group(1) == sec)

        def heading_through_pin(r):
            pins = r.pins()
            pins["headings"]["2"] = "## 2. Encoding of values"
            r.write_pins(pins)
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_heading(r, argparse.Namespace(key=str(seed), actor=AUTHOR, section="2", because="selftest: a renamed heading"))
            reproject(r)

        def document_fork(r):
            au = author(r)
            d = Document(Model(r.snapshot(), r.trust()))
            prev = {"transition": d.tid, "sha256": d.nodes[d.tid][1]}
            for k in (1, 2):
                h = au.store.put_json({"schema": DOCUMENT, "source": "SPEC.md", "parts": d.current["parts"],
                                       "because": f"selftest fork {k}", "previous": prev})
                au.put("transition", R.transition("ATTESTED", [h], residual=[DOCUMENT_RESIDUAL],
                                                  supersedes=[d.tid]), au.at() + k)
            reproject(r)

        def document_bad_previous(r):
            au = author(r)
            d = Document(Model(r.snapshot(), r.trust()))
            h = au.store.put_json({"schema": DOCUMENT, "source": "SPEC.md", "parts": d.current["parts"],
                                   "because": "selftest", "previous": {"transition": a.tid, "sha256": d.nodes[d.tid][1]}})
            au.put("transition", R.transition("ATTESTED", [h], residual=[DOCUMENT_RESIDUAL], supersedes=[a.tid]), au.at())
            reproject(r)

        def control_text(r):
            n = Model(r.snapshot(), r.trust()).current[a.id]
            author(r).claim(a.id, n.doc["text"].replace(" ", " \x00", 1), n.doc["witnesses"], n.doc["mutants"],
                            because="selftest", previous=n)
            reproject(r)

        def delete_document(r):
            m = Model(r.snapshot(), r.trust())
            for rid in Document(m).nodes:
                (r.store_dir / "records" / f"{rid}.json").unlink()
            reproject(r)

        def witness_gone(r):
            for w in a.doc["witnesses"]:
                test, _, cid = w.partition(":")
                pth = r.tests / f"{test}.py"
                pth.write_text(pth.read_text().replace(f'"{cid}"', f'"{cid}gone"'))
            rebacked([], [], unbacked_because="selftest: its witness case was removed")(r)

        def own_sentence_blob(r, n):
            return [sha(n.doc["text"])]

        def new_open_question(reason):
            def f(r):
                text = "An open rule is stated here."
                cid = f"SPEC-{b.doc['section']}-{id_key(b.id)[1] + 1000}"
                author(r).claim(cid, text, unbacked_because=reason, after=b.id)
                reproject(r)
            return f

        def edit_harness(name, old, new):
            def f(r):
                pth = r.tests / name
                src = pth.read_text()
                assert src.count(old) == 1, (name, old)
                pth.write_text(src.replace(old, new))
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

        amended = a.doc["text"] + " (as amended)"

        def supersede(r):
            n = Model(r.snapshot(), r.trust()).current[a.id]
            author(r).claim(a.id, amended, n.doc["witnesses"], n.doc["mutants"], because="selftest amendment", previous=n)
            reproject(r)

        def supersede_rendered(r):
            t = spec_text(r)
            return norm(amended) in t and t.count(norm(a.doc["text"])) == t.count(norm(amended))

        def retire(r):
            ev = Store(r.store_dir).put_blob(b"selftest: the sentence leaves SPEC.md")
            author(r).retire(b.id, "selftest: the sentence leaves SPEC.md", ev)
            reproject(r)

        def retire_rendered(r):
            m = Model(r.snapshot(), r.trust())
            history = [n for n in m.by_id[b.id] if not n.retired]
            return (norm(b.doc["text"]) not in spec_text(r) and m.current[b.id].retired and history
                    and all((r.store_dir / "records" / f"{n.tid}.json").is_file() for n in history)
                    and cell(b.doc["text"]) in r.projection.read_text().split("## Retired", 1)[1])

        inserted = "A new sentence is inserted here."
        new_id = f"SPEC-{a.doc['section']}-{id_key(a.id)[1] + 1000}"

        def insert(r):
            author(r).claim(new_id, inserted, unbacked_because="selftest: placed, not yet backed", after=a.id)
            reproject(r)

        def insert_rendered(r):
            return norm(a.doc["text"] + " " + inserted) in spec_text(r)

        def unretired_removal(r):
            spec_edit(b.doc["text"], "")(r)

        def newline_id(r):
            # AMEND 2 of #164: while ID_RE ended in `$`, an id with a trailing newline passed
            # `.match`; a claim filed under one, with a duty of its own and pinned, was accepted
            au = author(r)
            cid, text = a.id + "\n", a.doc["text"]
            at = au.at()
            au.store.put_blob(text.encode())
            duty = au.put("duty", R.duty(AUTHOR, statement_for(cid, text), au.pins["owed_to"], {"attest": {}},
                                         accept_by=au.pins["accept_by"], subject=sha(text)), at)
            doc = {"schema": CLAIM, "id": cid, "source": "SPEC.md", "section": a.doc["section"], "text": text,
                   "kind": "normative", "duty": duty, "witnesses": a.doc["witnesses"], "mutants": a.doc["mutants"],
                   "reason": None, "because": None, "previous": None}
            h = au.store.put_json(doc)
            au.put("transition", R.transition("ATTESTED", [h], closes=[R.item(duty, "discharge", [h])],
                                              established=[text], residual=[BACKED_RESIDUAL]), at)
            p = r.pins()
            p["sentences"][cid] = "normative"
            r.write_pins(p)
            reproject(r)

        def target_unknown(r):
            pth = r.tests / "agent_mutants.py"
            src = pth.read_text()
            i = src.index('("A28", ')
            j = src.index('"agent_handoff_test", ["V09"]', i)
            pth.write_text(src[:j] + '"agent_handoff_test", ["V09", "Z99"]' + src[j + len('"agent_handoff_test", ["V09"]'):])
            rebacked(["agent_handoff_test:V09"], ["A28"])(r)

        case("clean copy", None, lambda r: None)
        # W5: SPEC.md is the rendering of the records; nothing in it is written by hand
        case("SPEC.md edited by hand: a sentence changed", "SPEC_NOT_PROJECTION", spec_edit(a.doc["text"], "Something else entirely."))
        case("SPEC.md edited by hand: layout only (a line break joined)", "SPEC_NOT_PROJECTION",
             lambda r: r.spec.write_text(r.spec.read_text().replace(".\n", ". ", 1)))
        case("SPEC.md with \\r\\n line ends", "SPEC_NOT_PROJECTION",
             lambda r: r.spec.write_bytes(r.spec.read_bytes().replace(b"\n", b"\r\n")))
        case("SPEC-CLAIMS.md with \\r\\n line ends", "PROJECTION_STALE",
             lambda r: r.projection.write_bytes(r.projection.read_bytes().replace(b"\n", b"\r\n")))
        case("a supersede + project round trip", None, supersede, also=supersede_rendered)
        case("a new sentence inserted at a position renders there", None, insert, also=insert_rendered)
        case("a retired sentence leaves SPEC.md, stays in the store and in SPEC-CLAIMS.md", None, retire, also=retire_rendered)
        case("a cited mutant that does not exist", "UNKNOWN_MUTANT", rebacked(a.doc["witnesses"], ["M999"]))
        case("a cited case that does not exist", "UNKNOWN_CASE", rebacked(["contract_test:Z9"], a.doc["mutants"]))
        case("a mutant that burns none of the cited cases", "MUTANT_OFF_WITNESS", rebacked(["contract_test:A1"], ["M19"]))
        # W4: UNBACKED is an allowed open question, with guards
        case("a new sentence filed UNBACKED with its reason", None, new_open_question("selftest: no case reaches it"))
        case("an UNBACKED claim without a reason", "UNBACKED_WITHOUT_REASON", new_open_question(None))
        case("a BACKED claim superseded UNBACKED without counter-evidence", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked(a.doc["witnesses"], [], unbacked_because="selftest"))
        # AMEND 1: the counter-evidence must be a counter blob that replays, not any blob or challenge
        case("a BACKED claim superseded UNBACKED citing a counter-file of junk bytes", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=junk_blob))
        case("a BACKED claim superseded UNBACKED citing a challenge alone", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=challenge_of(lambda n: n.tid)))
        case("a counter blob that replays (its patch alters a function a cited mutant alters)", None,
             rebacked([], [], unbacked_because="selftest", counter=counter()))
        # AMEND 2: the patch must alter code the claim's own mutants alter
        case("a counter patch in a module the claim's mutants do not touch", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=counter(), claim=e))
        case("a counter patch in another function of the same file", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest",
                      counter=counter(edit=(surrogates_old, surrogates_new), fails=["records_test:E3"])))
        # AMEND 4: a scope changes only if its AST does, and every changed scope must be the claim's
        # mutants' (Codex on 0590956: a comment in M02's function let a foreign JCS break through).
        def scope_edit(r, how):
            """A diff that changes `g`'s mutant function in the fixture as `how` says."""
            (path, qual), = {sc for mid in g.doc["mutants"] for sc in r.mutant_scopes(mid)}
            src = (r.root / path).read_text()
            node = next(x for x in ast.walk(ast.parse(src)) if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and x.name == qual.split(".")[-1])
            lines = src.splitlines(True)
            at = node.body[0].lineno - 1
            indent = lines[at][:len(lines[at]) - len(lines[at].lstrip())]
            doc = isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str)
            if how == "docstring" and doc:
                lines[at] = lines[at].replace('"""', '"""Selftest. ', 1)
            else:
                lines.insert(at, indent + {"comment": "# selftest marker: no behavioural change", "blank": "   ",
                                           "docstring": '"""Selftest docstring."""', "assign": "_selftest_unused = 1"}[how] + "\n")
            return "".join(difflib.unified_diff(src.splitlines(True), lines, f"a/{path}", f"b/{path}"))

        def foreign_break(r):
            """Codex's foreign hunk: jcs admits floats (records_test E2 fails)."""
            src = (r.root / "warrant" / "jcs.py").read_text()
            new = src.replace(floats_old, floats_new, 1).replace("parse_constant=_constant, parse_float=_float)",
                                                                  "parse_constant=_constant)", 1)
            return "".join(difflib.unified_diff(src.splitlines(True), new.splitlines(True), "a/warrant/jcs.py", "b/warrant/jcs.py"))

        def g_counter(how, foreign=True):
            def f(r, n):
                doc = {"counter": COUNTER, "claim": n.id, "against": n.tid,
                       "patch": (foreign_break(r) if foreign else "") + scope_edit(r, how),
                       "passes": sorted(n.doc["witnesses"]), "fails": ["records_test:E2"], "why": "selftest"}
                return [Store(r.store_dir).put_json(doc)]
            return f

        for name, how, foreign in (
                ("Codex's shape: a foreign float break plus a comment inside the mutant's function", "comment", True),
                ("a foreign break plus a whitespace-only line inside the mutant's function", "blank", True),
                ("a foreign break plus a docstring-only change inside the mutant's function", "docstring", True),
                ("a foreign hunk plus a behaviour-neutral AST change inside the mutant's function", "assign", True),
                ("a patch whose only change is AST-equal inside the mutant's function", "comment", False)):
            case(name, "COUNTER_NOT_REPLAYED",
                 rebacked([], [], unbacked_because="selftest", counter=g_counter(how, foreign), claim=g))
        case("a challenge carrying a counter blob that replays", None,
             rebacked([], [], unbacked_because="selftest", counter=challenge_carrying()))
        case("a counter blob whose passes omits a cited witness", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=counter(passes=[])))
        case("a counter blob whose fails case passes under the patch", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=counter(fails=["records_test:E3"])))
        case("a counter blob with an empty patch (nothing fails)", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=counter(patch="")))
        case("a counter blob against another claim", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=counter(against=b.tid)))
        case("a counter blob whose patch reaches outside the packages", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=outside_patch))
        case("a challenge carrying a counter blob that does not replay", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=challenge_carrying(fails=["records_test:E3"])))
        # W5: route 1 is admitted only when the witness was already gone at the base
        case("a BACKED claim superseded UNBACKED in the change that removes its witness", "WITNESS_REMOVED_WITH_DOWNGRADE",
             witness_gone)
        case("a BACKED claim superseded UNBACKED whose witness was already absent at the base", None, witness_gone_at_base)
        case("a BACKED claim superseded UNBACKED citing a challenge against another record", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=challenge_of(lambda n: n.doc["duty"])))
        case("a BACKED claim superseded UNBACKED citing only its own sentence", "LOST_BACKING_WITHOUT_COUNTER",
             rebacked([], [], unbacked_because="selftest", counter=own_sentence_blob))
        case("a normative sentence without a mutant and without a reason", "UNBACKED_WITHOUT_REASON",
             rebacked(a.doc["witnesses"], []))
        # W4: mutants of tests/agent_mutants.py are citable, in their own namespace
        case("an agent mutant cited with the case it targets", None, rebacked(["agent_handoff_test:V09"], ["A28"]))
        case("an agent mutant that burns none of the cited cases", "MUTANT_OFF_WITNESS",
             rebacked(["contract_test:A1"], ["A28"]))
        case("a mutant id defined in both harnesses", "MUTANT_ID_COLLISION",
             edit_harness("agent_mutants.py", '("A28", ', f'("{a.doc["mutants"][0]}", '))
        case("an agent harness id without its prefix", "MUTANT_ID_PREFIX",
             edit_harness("agent_mutants.py", '("A28", ', '("M9999", '))
        case("a cited mutant whose target is not a case of an existing test file", "MUTANT_TARGET_UNKNOWN", target_unknown)
        case("a cited mutant id defined twice", "DUPLICATE_MUTANT_ID", duplicate_mutant)
        case("a record file renamed", "RECORD_MISNAMED", rename)
        case("a record rewritten in non-canonical bytes", "NOT_CANONICAL", noncanonical)
        case("a claim deleted without a retiring record", "CLAIM_DELETED", delete_claim)
        case("the projection edited by hand", "PROJECTION_STALE", hand_edit)
        case("a standing challenge against a current claim", "CHALLENGED", challenge)
        case("a pinned sentence unpinned without retirement", "UNPINNED_WITHOUT_RETIREMENT", unpin)
        case("a new sentence in SPEC.md with no claim", "SPEC_NOT_PROJECTION", add_sentence)
        case("a sentence removed from SPEC.md, its claim not retired", "SPEC_NOT_PROJECTION", unretired_removal)
        # W5: the document record's own guards, each with SPEC.md re-rendered so only the guard refuses
        case("prose smuggled into a document literal", "DOCUMENT_LITERAL",
             doc_version(lambda ps: ps[:1] + [" Every actor may sign for every other. "] + ps[1:]))
        case("a digit glued to a sentence by a literal", "DOCUMENT_LITERAL",
             doc_version(lambda ps: ps[:part_of(ps, b.id) + 1] + ["0"] + ps[part_of(ps, b.id) + 1:]))
        case("prose smuggled into a layout run", "STRUCTURE", doc_version(
            lambda ps: [dict(q, layout={"sha256": q["layout"]["sha256"], "gaps": [[0, " and nobody checks "]]})
                        if isinstance(q, dict) and q.get("claim") == a.id else q for q in ps]))
        case("a heading line with a trailing newline", "STRUCTURE",
             doc_version(lambda ps: [{"heading": q["heading"] + "\n"} if isinstance(q, dict) and "heading" in q and k == 0 else q
                                     for k, q in enumerate(ps)]))
        case("a document version that leaves out a current claim", "CLAIM_NOT_IN_DOCUMENT",
             doc_version(lambda ps: ps[:part_of(ps, b.id)] + ps[part_of(ps, b.id) + 1:]))
        case("a document version that places a claim twice", "DOCUMENT_CLAIM_TWICE",
             doc_version(lambda ps: ps + [" ", copy.deepcopy(ps[part_of(ps, b.id)])]))
        case("a document version that names a claim no record states", "DOCUMENT_UNKNOWN_CLAIM",
             doc_version(lambda ps: ps[:part_of(ps, b.id) + 1] + [" ", {"claim": b.id[:-1] + "9999", "layout": None}]
                         + ps[part_of(ps, b.id) + 1:]))
        case("a document version that moves a claim under another section's heading", "DOCUMENT_SECTION",
             doc_version(lambda ps: [q for q in ps if q != ps[part_of(ps, a.id)]] + [" ", ps[part_of(ps, a.id)]]))
        case("a document version without a pinned section's heading", "SECTION_MISSING",
             doc_version(lambda ps: [q for q in ps if not (isinstance(q, dict) and q.get("heading", "").startswith(
                 f"## {a.doc['section']}. "))]))
        case("two current document versions", "DOCUMENT_FORK", document_fork)
        # AMEND 1 of #166: headings are pinned; a heading is free text no witness backs
        case("the parent's probe: an unnumbered heading carrying a rule, after §4.2's", "DOCUMENT_HEADING",
             doc_version(lambda ps: ps[:head_of(ps, "4.2") + 1]
                         + ["\n\n", {"heading": "#### Any holder may discharge any duty without acceptance"}]
                         + ps[head_of(ps, "4.2") + 1:]))
        case("a numbered heading for a section the pins do not name", "DOCUMENT_HEADING",
             doc_version(lambda ps: ps[:head_of(ps, "5")] + [{"heading": "### 4.8 Exceptions"}, "\n\n"] + ps[head_of(ps, "5"):]))
        case("a pinned section's heading with its title altered", "DOCUMENT_HEADING",
             doc_version(lambda ps: [{"heading": q["heading"] + ": floats are allowed"} if k == head_of(ps, "2") else q
                                     for k, q in enumerate(ps)]))
        case("a second heading for a pinned section", "DOCUMENT_HEADING",
             doc_version(lambda ps: ps[:head_of(ps, "2") + 1] + ["\n\n", copy.deepcopy(ps[head_of(ps, "2")])]
                         + ps[head_of(ps, "2") + 1:]))
        case("two pinned headings swapped out of order", "DOCUMENT_HEADING",
             doc_version(lambda ps: [ps[head_of(ps, "3.6")] if k == head_of(ps, "3.5") else
                                     ps[head_of(ps, "3.5")] if k == head_of(ps, "3.6") else q for k, q in enumerate(ps)]))
        case("a heading changed through its pin, then `heading --section`", None, heading_through_pin,
             also=lambda r: "## 2. Encoding of values\n" in r.spec.read_text())
        case("a document version whose previous is not a document version", "STRUCTURE", document_bad_previous)
        case("a claim text with a control character (U+0000 would vanish from SPEC.md)", "STRUCTURE", control_text)
        case("the document records deleted", "DOCUMENT_MISSING", delete_document)
        case("a claim id with a trailing newline", "STRUCTURE", newline_id)

        # Run the registered cases: in `jobs` forked processes (each inherits the fixture and the
        # closures above), results reported in registration order.
        global _CASE_RUNNER
        _CASE_RUNNER = run_case          # a forked worker finds it here; a closure does not pickle
        if jobs > 1 and "fork" in multiprocessing.get_all_start_methods():
            with concurrent.futures.ProcessPoolExecutor(jobs, mp_context=multiprocessing.get_context("fork")) as ex:
                results = list(ex.map(_run_registered_case, range(len(cases))))
        else:
            results = [run_case(i) for i in range(len(cases))]
        for (name, *_), (ok, line) in zip(cases, results):
            failures += not ok
            ran.append(name)
            print(line)

        # AMEND 3: a refused command leaves the store byte-identical. Through the command line:
        # `supersede --counter-file` with junk bytes, and with a well-formed counter blob that is
        # not local (and --challenge), each refused; then the store's files, and `check`, as before.
        import contextlib
        import io
        d = work / "refused-counter-file"
        subprocess.run(["git", "-c", "gc.auto=0", "clone", "-q", "--no-local", str(fix), str(d)], capture_output=True, check=True)
        r = Repo(d)

        def listing():
            return sorted((q.relative_to(r.store_dir).as_posix(), q.read_bytes()) for q in r.store_dir.rglob("*") if q.is_file())
        junk = work / "junk.txt"
        junk.write_bytes(b"lol\n")
        nonlocal_counter = work / "nonlocal.json"
        nonlocal_counter.write_text(json.dumps(counter_doc(r, Model(r.snapshot(), r.trust()).current[e.id])))
        before, rcs = listing(), []
        for cid, f, extra in ((a.id, junk, []), (e.id, nonlocal_counter, ["--challenge"])):
            n = Model(r.snapshot(), r.trust()).current[cid]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rcs.append(main(["--root", str(d), "supersede", "--key", str(seed), "--id", cid, "--text", n.doc["text"],
                                 "--because", "selftest", "--unbacked-because", "selftest", "--counter-file", str(f)] + extra))
        got = check(r, base)
        ok = rcs == [2, 2] and listing() == before and not got
        failures += not ok
        print(("ok    " if ok else "FAIL  ") + "a refused counter-file leaves no blob: refused, store unchanged, check passes"
              + ("" if ok else f" | exit {rcs}, store {'changed' if listing() != before else 'unchanged'}, check {got[:2]}"))
        ran.append("refused counter-file")
        # W5: a new sentence names its position; without one, nothing is written. Through the
        # command line (`add` with no --after) and through Author.claim, on the same clone.
        before = listing()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = main(["--root", str(d), "add", "--key", str(seed), "--id", new_id, "--text", inserted,
                       "--unbacked-because", "selftest: no position given"])
        try:
            Author(r, key, AUTHOR, validate=False).claim(new_id, inserted, unbacked_because="selftest")
            raised = False
        except Refused:
            raised = True
        ok = rc == 2 and raised and listing() == before and not check(r, base)
        failures += not ok
        ran.append("unplaced sentence")
        print(("ok    " if ok else "FAIL  ") + "a new sentence without a position: refused, store unchanged, check passes"
              + ("" if ok else f" | exit {rc}, raised {raised}, store {'changed' if listing() != before else 'unchanged'}"))
        print(f"CLAIMS SELFTEST: {'OK' if not failures else f'{failures} FAIL'} ({len(ran)} cases)")
        return 1 if failures else 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- main

def _jobs(v):
    """A worker count: a decimal integer >= 1 ("+2", "-1", "0" and "two" are refused)."""
    if not re.fullmatch(r"[1-9][0-9]*", v):
        raise argparse.ArgumentTypeError(f"--jobs must be an integer >= 1, got {v!r}")
    return int(v)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--selftest", action="store_true", help="burn the checker on a copy and exit")
    ap.add_argument("--jobs", type=_jobs, default=min(os.cpu_count() or 1, 8), metavar="N",
                    help="--selftest: cases run N at a time, each on its own clone (default: CPUs, at most 8)")
    ap.add_argument("--root", default=str(ROOT), help="the repository (default: this checkout)")
    sub = ap.add_subparsers(dest="cmd")

    def authoring(p):
        p.add_argument("--key", help="seed file of the signing key (or WARRANT_CLAIMS_KEY)")
        p.add_argument("--actor", default=AUTHOR)
        p.add_argument("--residual", action="append", default=[], help="what this claim does not establish")
        return p

    p = authoring(sub.add_parser("add", help="author claims from a stanza"))
    p.add_argument("--stanza", help="JSON stanza or list: {id, text, witnesses, mutants, informative, unbacked_because, "
                   "counter, residual, because}")
    p.add_argument("--id")
    p.add_argument("--text")
    p.add_argument("--witness", action="append", default=[], help="<test file>:<case>, repeatable or comma-separated")
    p.add_argument("--mutant", action="append", default=[])
    p.add_argument("--informative", help="the reason this sentence is not normative")
    p.add_argument("--unbacked-because", help="why this normative sentence is open (no witness or no mutant)")
    p.add_argument("--because")
    p.add_argument("--after", help="a new sentence's position: the claim it follows, in its own section")
    p.add_argument("--paragraph", action="store_true", help="start a new paragraph after --after")
    p = authoring(sub.add_parser("supersede", help="replace a claim's statement"))
    p.add_argument("--id", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--because", required=True)
    p.add_argument("--witness", action="append", default=[])
    p.add_argument("--mutant", action="append", default=[])
    p.add_argument("--informative")
    p.add_argument("--unbacked-because", help="why the sentence is open now; the claim keeps no witnesses or mutants")
    p.add_argument("--counter", action="append", default=[],
                   help="challenge record or counter blob id already in the store (a BACKED claim losing its backing)")
    p.add_argument("--counter-file", help="a counter blob (warrant-claims/counter@1 JSON) to store and cite")
    p.add_argument("--challenge", action="store_true",
                   help="also file a challenge against the claim being replaced, its evidence the counter-evidence")
    p = authoring(sub.add_parser("retire", help="retire a claim with counter-evidence"))
    p.add_argument("--id", required=True)
    p.add_argument("--because", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--counter", help="record or blob id of the counter-evidence, already in the store")
    g.add_argument("--counter-file", help="a file to store as the counter-evidence blob")
    sub.add_parser("project", help="regenerate SPEC.md and SPEC-CLAIMS.md")
    p = authoring(sub.add_parser("migrate", help="W5, once: the first document version, from SPEC.md"))
    p.add_argument("--because", required=True)
    p = authoring(sub.add_parser("heading", help="file the heading .warrant/claims.json now pins for a section"))
    p.add_argument("--section", required=True, help="the section number, or 0 for the document's title")
    p.add_argument("--because", required=True)
    p = sub.add_parser("check", help="CI: refuse any disagreement")
    p.add_argument("--base", help="the revision whose claims must survive (default: origin/master)")
    p.add_argument("--no-base", action="store_true")
    p = sub.add_parser("keygen", help="make an author key: seed outside the repository, public key in the trust")
    p.add_argument("--out", required=True)
    p.add_argument("--actor", default=AUTHOR)
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.jobs)
    repo = Repo(a.root)
    if a.cmd is None:
        ap.print_help()
        return 2
    try:
        if a.cmd == "project":
            cmd_project(repo)
            return 0
        if a.cmd == "check":
            return cmd_check(repo, a)
        {"add": cmd_add, "supersede": cmd_supersede, "retire": cmd_retire, "keygen": cmd_keygen,
         "migrate": cmd_migrate, "heading": cmd_heading}[a.cmd](repo, a)
        return 0
    except Refused as e:
        print(f"REFUSED {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
