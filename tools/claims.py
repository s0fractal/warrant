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
is confined to the code the claim's own mutants alter (scopes compared by AST, and only
statements one of those mutants changes, AMEND 1 of #169), under which every cited witness
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
    python3 tools/claims.py bind --key SEED --actor NAME  # bind an existing key, with its proof of possession
    python3 tools/claims.py accept --key SEED --actor codex --claim SPEC-4.2-3 [--all]
    python3 tools/claims.py challenge --key SEED --actor NAME --claim SPEC-4.2-3 --because '...' \
        [--counter-file COUNTER.json]                    # anyone bound; a counter must replay
    python3 tools/claims.py trust                        # the admitted bindings, as a trust/2 document
    python3 tools/claims.py pin --key SEED --actor NAME   # pin a role's key in .warrant/roles.json (reviewed)
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
    python3 tools/claims.py audit --matrix M.json [--matrix A.json] [--counters DIR] [--refuse]
    python3 tools/claims.py why warrant/engine.py:729 [--json]   # the claims, obligations, goals a statement serves
    python3 tools/claims.py why --uncovered [FILE] [--json]      # the statements no cited mutant changes
    python3 tools/claims.py --selftest                   # every refusal of `check`, burned on a copy
    python3 tools/claims.py migrate --key SEED --because '...'   # once (W5): the first document, from SPEC.md
    python3 tools/claims.py heading --key SEED --section 4.2 --because '...'   # after changing that pin

The open circle of witnesses (README.md): `.warrant/trust.json` holds bindings that
certify themselves (the key signs {actor, public, purpose}), admitted by `check`
with no admin, the first binding of an actor winning, except that a name the
configuration gives a role is pinned in `.warrant/roles.json` (a key, reserved, or
collective; AMEND 1); `accept` files an acceptance
signed by an acceptor the duty names; a challenge by anyone bound that carries a
counter blob which replays lowers the claim's backing (COUNTERED), while only the
claim's author supersedes or retires it; WITNESSES.md is a ledger derived from the
records that grants nothing.

`audit` hunts the class of defect a counter blob proves, before a reviewer does
(the six counters of the Gemini deep review, 2026-10-22, were all of it): from a
matrix written by `tests/mutants.py --matrix` (every case's result under every
mutant), it names each BACKED claim and each mutant outside the claim's mutants
whose AST scopes overlap theirs, under which some case fails and every witness of
the claim passes, and prints the would-be counter. It is a report, not a refusal
of `check`: an own-file matrix (what CI's mutant run gives for free) leaves most
witnesses unknown, and the full one costs every suite under every mutant.

`why` follows the links the other way, from code to records: a statement (the unit
changed_statements counts) is served by the current claims BACKED in the view (`standing`:
a COUNTERED claim is named, never backing) citing a mutant that changes it, by the roadmap obligations whose serves or requires name those claims'
duties, and by the goals those obligations answer; `why --uncovered` lists the
statements of warrant/ and warrant_agent/ no cited mutant changes.

A claim's text is whitespace-normalized: runs of whitespace compare as one space.
Refusals are printed one per line as `REFUSED <CODE> <detail>`.
"""
import argparse
import ast
import concurrent.futures
import copy
import difflib
import functools
import hashlib
import importlib.util
import io
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tokenize
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.environ.get("WARRANT_IMPL") or str(ROOT))

import warrant as W                          # noqa: E402
from warrant import engine as E              # noqa: E402
from warrant import jcs as C                 # noqa: E402
from warrant import keys as K                # noqa: E402
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
# What a Markdown reader takes for a heading line (CommonMark): an ATX heading, up to three
# spaces then one to six # then a space, a tab or the line's end; a setext underline, a line
# of = or of - under a non-blank line. Fenced blocks are not exempt: such a line anywhere is
# counted, and refused unless it is the document's own heading part (AMEND 2 of #166).
ATX_LINE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|\Z)")
SETEXT_LINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*\Z")
# Open circle of witnesses: a binding certifies itself (its key signs it); nobody admits anyone.
BINDINGS = "warrant-claims/bindings@1"       # .warrant/trust.json: {"bindings": BINDINGS, "keys": [...]}
BINDING = "warrant-claims/binding@1"         # the purpose a proof signs: canon({actor, public, purpose})
BINDING_FIELDS = ("actor", "public", "proof")
LOCAL_TRUST = "WARRANT_CLAIMS_TRUST"         # a receiver's own trust/2 file, added to the admitted bindings
ROLES = "warrant-claims/roles@1"             # .warrant/roles.json: the actors the configuration gives a role
COLLECTIVE = "collective"                    # a role no key signs as (readers): never bindable
WITNESSES = "WITNESSES.md"
PREAMBLE = "0"              # the section before the first numbered heading
WIDTH = 80                  # the fill width of a sentence whose recorded layout no longer applies
GONE = "\x00"               # placeholder of a retired sentence while SPEC.md is rendered


class Refused(Exception):
    """An authoring command that cannot be carried out; nothing was written. `code`, when
    given, names the refusal (printed before the detail; tests read it, never the wording)."""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


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


# ---------------------------------------------------------------- bindings (open circle, part A)

def binding_message(actor, public):
    """The bytes a binding's proof signs: canon({actor, public, purpose}). It starts with `{`,
    so it is never the message of a record signature ("warrant-sig-v1:" || id)."""
    return C.canon({"actor": actor, "public": public, "purpose": BINDING})


def binding_proof(key, actor):
    return key.sign(binding_message(actor, key.public))


def read_roles(doc):
    """({actor: public hex | None | COLLECTIVE}, problems) of a roles document (.warrant/roles.json).

    AMEND 1 of #170: a name the repository's own configuration gives a role (an acceptor, a
    creditor, the claims' author) is not first-come. Its key is pinned here, as a receiver's
    profile pins the keys it trusts: a hex64 public key (a binding of that actor is admitted
    with exactly that key), null (reserved: not bindable until a pin names its key) or
    "collective" (a role no key signs as, such as `readers`: never bindable). Every other
    name stays first-come. Changing who a role is, is a diff of this reviewed file."""
    if not (isinstance(doc, dict) and set(doc) == {"roles", "actors"} and doc["roles"] == ROLES
            and isinstance(doc["actors"], dict)):
        return {}, [("ROLES_SHAPE", f".warrant/roles.json is not {{\"roles\": {ROLES!r}, \"actors\": {{...}}}}")]
    roles, problems = {}, []
    for actor, v in doc["actors"].items():
        try:
            R.check_actor(actor)
        except R.Invalid as e:
            problems.append(("ROLES_SHAPE", f".warrant/roles.json: {actor[:60]!r} is not an actor id: {e}"))
            continue
        if not (v is None or v == COLLECTIVE or (isinstance(v, str) and R.HEX64.match(v))):
            problems.append(("ROLES_SHAPE", f".warrant/roles.json: {actor}: a role is a hex64 public key, null or "
                             f"{COLLECTIVE!r}, not {str(v)[:70]!r}"))
            continue
        roles[actor] = v
    return roles, problems


def _role_name(v):
    """A role value for a message: 'key <id>' for a key, else what it is (never raises)."""
    return f"key {K.key_id(v)[:12]}" if isinstance(v, str) and R.HEX64.match(v) else "collective" if v == COLLECTIVE \
        else "reserved" if v is None else repr(v)[:40]


def unpinned(roles, names, where):
    """ROLE_UNPINNED for each actor a configuration file names that .warrant/roles.json does not."""
    return [("ROLE_UNPINNED", f"{where} names {a!r}, and .warrant/roles.json gives it no role: a name with a role "
             "is pinned (a key, null for reserved, or collective), never first-come")
            for a in sorted(set(names) - set(roles))]


def admit_bindings(doc, legacy=False, roles=None):
    """(admitted [(actor, public)], problems [(code, detail)]) of a bindings document.

    A binding is admitted mechanically, in file order, iff its proof is the signature of its
    own key over binding_message(actor, public), its actor id has SPEC-3-21's shape, its
    actor's role (`roles`, read_roles) admits that key, its key is not bound already, and its
    actor is not bound already to another key: the first binding of a name with no role
    wins, and a second key for it would need a record signed by the first, which this tool
    does not implement (rotation is out of scope), so it is refused. Nobody judges who may
    join; what a binding grants is only "this key signs as this actor" (SPEC §6). `legacy`
    reads a trust/2 document (actor, public, no proof) as admitted: only for a base revision
    written before bindings carried proofs."""
    if legacy and isinstance(doc, dict) and doc.get("warrant") == "trust/2":
        try:
            return [(a, p) for a, p in Trust(doc).keys.values()], []
        except R.Invalid as e:
            return [], [("BINDINGS_SHAPE", f".warrant/trust.json: {e}")]
    if not (isinstance(doc, dict) and set(doc) == {"bindings", "keys"} and doc["bindings"] == BINDINGS
            and isinstance(doc["keys"], list)):
        return [], [("BINDINGS_SHAPE", f".warrant/trust.json is not {{\"bindings\": {BINDINGS!r}, \"keys\": [...]}} "
                                       "(tools/claims.py bind writes it)")]
    admitted, problems = [], []
    publics = [k.get("public") for k in doc["keys"] if isinstance(k, dict)]
    for i, k in enumerate(doc["keys"]):
        code, why = _binding_problem(k, publics, admitted, roles or {})
        if code:
            problems.append((code, f".warrant/trust.json keys[{i}]: {why}"))
        else:
            admitted.append((k["actor"], k["public"]))
    return admitted, problems


def _binding_problem(k, publics, admitted, roles):
    """(code, why) when entry `k` is not admitted after `admitted`, else (None, None)."""
    if not (isinstance(k, dict) and set(k) <= set(BINDING_FIELDS) and {"actor", "public"} <= set(k)
            and isinstance(k["public"], str) and R.HEX64.match(k["public"])):
        return "BINDING_SHAPE", f"an entry is {{actor, public: hex64, proof: hex128}}, not {str(k)[:120]}"
    try:
        R.check_actor(k["actor"])
    except R.Invalid as e:
        return "BINDING_ACTOR_SHAPE", f"{str(k['actor'])[:60]!r} is not an actor id (SPEC-3-21): {e}"
    if "proof" not in k:
        return "BINDING_UNPROVEN", f"{k['actor']}: no proof; the key's own signature over the binding is needed"
    msg = binding_message(k["actor"], k["public"])
    if not K.verify(k["public"], k["proof"], msg):
        other = [p for p in publics if p != k["public"] and isinstance(p, str) and K.verify(p, k["proof"], msg)]
        if other:
            return "BINDING_PROOF_OTHER_KEY", (f"{k['actor']}: the proof is signed by key {K.key_id(other[0])[:12]}, "
                                               f"not by the key it binds ({K.key_id(k['public'])[:12]})")
        return "BINDING_PROOF_FORGED", f"{k['actor']}: the proof is not the bound key's signature over this binding"
    role = roles.get(k["actor"], k["public"])
    if role != k["public"]:                 # one rule; the code only says which kind of role refused it
        if role == COLLECTIVE:
            return "BINDING_ROLE_COLLECTIVE", f"{k['actor']} is a collective role in .warrant/roles.json: no key signs as it"
        if role is None:
            return "BINDING_ROLE_RESERVED", (f"{k['actor']} is reserved in .warrant/roles.json: it is bindable once a "
                                             "reviewed pin names its key")
        return "BINDING_ROLE_KEY", (f"{k['actor']}: .warrant/roles.json pins {_role_name(role)}, this binding is of "
                                    f"key {K.key_id(k['public'])[:12]}")
    if any(p == k["public"] for _, p in admitted):
        return "BINDING_KEY_TWICE", f"key {K.key_id(k['public'])[:12]} is bound already"
    first = next((p for a, p in admitted if a == k["actor"]), None)
    if first is not None:
        return "BINDING_ACTOR_TAKEN", (f"{k['actor']} is bound already to key {K.key_id(first)[:12]}; the first "
                                       "binding wins, and rotation (a record signed by the first key) is not "
                                       "implemented, so a second key for an actor is refused")
    return None, None


def local_bindings():
    """[(actor, public)] of the receiver's own trust/2 file named by $WARRANT_CLAIMS_TRUST, if
    any: a receiver may bind whatever keys it chooses for itself (SPEC §4.6); nothing in the
    repository can set it, and CI sets none. The claims selftest binds its ephemeral key here."""
    path = os.environ.get(LOCAL_TRUST)
    return [] if not path else [(a, p) for a, p in Trust.load(path).keys.values()]


def trust_of(bindings):
    """A Trust of (actor, public) pairs, the first binding of each key kept."""
    seen, pairs = set(), []
    for a, p in bindings:
        if p not in seen:
            seen.add(p)
            pairs.append((a, p))
    return Trust(Trust.document(pairs))


# ---------------------------------------------------------------- the repository

class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.spec = self.root / "SPEC.md"
        self.store_dir = self.root / ".warrant" / "store"
        self.trust_path = self.root / ".warrant" / "trust.json"
        self.pins_path = self.root / ".warrant" / "claims.json"
        self.roles_path = self.root / ".warrant" / "roles.json"
        self.projection = self.root / "SPEC-CLAIMS.md"
        self.witnesses = self.root / WITNESSES
        self.tests = self.root / "tests"
        self._mutants = None

    def pins(self):
        return json.loads(self.pins_path.read_text())

    def write_pins(self, pins):
        pins["sentences"] = dict(sorted(pins["sentences"].items(), key=lambda kv: id_key(kv[0])))
        self.pins_path.write_text(json.dumps(pins, indent=2, ensure_ascii=False) + "\n")

    def roles(self):
        """(roles, problems) of .warrant/roles.json (read_roles); none given, no name has a role."""
        if not self.roles_path.is_file():
            return {}, []
        try:
            doc = json.loads(self.roles_path.read_text())
        except ValueError as e:
            return {}, [("ROLES_SHAPE", f".warrant/roles.json: {e}")]
        return read_roles(doc)

    def bindings(self):
        """(admitted [(actor, public)], problems) of .warrant/trust.json (admit_bindings), under
        the roles of .warrant/roles.json."""
        if not self.trust_path.is_file():
            return [], [("BINDINGS_SHAPE", ".warrant/trust.json does not exist (tools/claims.py bind writes it)")]
        try:
            doc = C.loads(self.trust_path.read_bytes())
        except Exception as e:      # noqa: BLE001 -- an unreadable file admits nothing, and says why
            return [], [("BINDINGS_SHAPE", f".warrant/trust.json: {type(e).__name__}: {e}")]
        return admit_bindings(doc, roles=self.roles()[0])

    def trust(self):
        """The trust this checker uses: the admitted bindings, then the receiver's own (local_bindings)."""
        return trust_of(self.bindings()[0] + local_bindings())

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

    def mutant_statements(self, mid):
        """The statements (changed_statements) mutant `mid` changes in the file as it is now;
        empty when its edits no longer apply."""
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
            return changed_statements(path, old, new)
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
            code, why = self._link(n)
            if why:
                self.problems.append((code, f"transition {n.tid[:12]} ({n.id}): {why}"))
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
        """(code, why) unless a replacing claim names, in `previous` and `supersedes`, a claim of
        the same id by the same author; else (None, None)."""
        prev = n.doc["previous"]
        sup = n.rec["body"]["supersedes"]
        if prev is None:
            return ("STRUCTURE", "it supersedes something without saying what it replaces") if sup else (None, None)
        if sup != [prev["transition"]]:
            return "STRUCTURE", "supersedes does not name exactly its previous claim"
        p = self.nodes.get(prev["transition"])
        if p is None or p.id != n.id or p.retired:
            return "STRUCTURE", "its previous claim is not a live claim transition of the same id"
        if prev["duty"] != p.doc["duty"] or prev["statement_sha256"] != sha(p.doc["text"]):
            return "STRUCTURE", "previous does not repeat the replaced claim's duty and statement hash"
        # Open circle, part C: anyone may bind a key and file a counter, but a claim's lineage
        # (supersession, retirement) stays with its author: a counter lowers backing, never authorship.
        if n.rec["actor"] != p.rec["actor"]:
            return "LINEAGE_NOT_AUTHOR", (f"filed by {n.rec['actor']!r}, and the claim it replaces by {p.rec['actor']!r}: "
                                          "only a claim's author supersedes or retires it")
        return None, None

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
            elif p[0]["actor"] != r["actor"]:
                self.problems.append(("LINEAGE_NOT_AUTHOR", f"document transition {rid[:12]} by {r['actor']!r} supersedes "
                                      f"a version by {p[0]['actor']!r}: only the document's author files its next version"))
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
                parts = self.current["parts"]
                before, after = (parts[i - 1] if i else None), (parts[i + 1] if i + 1 < len(parts) else None)
                if not ((i == 0 or isinstance(before, str) and before.endswith("\n"))
                        and isinstance(after, str) and after.startswith("\n")):
                    out.append(("DOCUMENT_HEADING", f"part {i}: {line[:80]!r} does not stand on a line of its own "
                                "(a literal ending in a line break before it, one starting with a line break after)"))
                if sec is None or headings.get(sec) != line:      # one predicate: the line is its section's pin
                    why = ("is neither a numbered heading nor the pinned title" if sec is None else
                           f"heads §{sec}, which .warrant/claims.json pins no heading for" if sec not in headings else
                           f"is not the pinned heading of §{sec}, {headings[sec][:80]!r}")
                    out.append(("DOCUMENT_HEADING", f"part {i}: {line[:80]!r} {why}"))
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


def rendered_headings(text):
    """The heading lines a Markdown reader sees in `text`: ATX lines as they are, a setext
    heading as its text line and underline joined by a line break."""
    lines, out = text.split("\n"), []
    for k, ln in enumerate(lines):
        if ATX_LINE.match(ln):
            out.append(ln)
        elif SETEXT_LINE.match(ln) and k and lines[k - 1].strip():
            out.append(lines[k - 1] + "\n" + ln)
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


def disposition(rep, n, accepted=()):
    """The engine's disposition of claim `n`'s duty, with who accepted its closure (`accepted`)."""
    if n.retired or n.kind == "informative":
        return "— (no duty)"
    r = rep["duties"].get(n.doc["duty"])
    if r is None:
        return "MISSING"
    by = f"accepted by {', '.join(accepted)}" if accepted else ""
    waiting = sorted({a for c in r["candidates"] if c["verdict"] == "PENDING" for a in c.get("waiting_for") or []})
    if r["disposition"] == "OPEN":
        return f"OPEN (awaiting {', '.join(waiting)}{'; ' + by if by else ''})" if waiting else "OPEN (no closure filed)"
    return r["disposition"] + (f" ({by})" if by else "")


def cell(s):
    return s.replace("|", "\\|")


def status_of(n, low):
    """A claim's status in the view: COUNTERED when a replaying counter lowers its backing (`low`)."""
    return "COUNTERED" if n.id in low else n.status


def standing(repo, model, table=None):
    """({claim id: status}, low): every current claim's status as the views show it (status_of
    over lowered(challenge_table)), and the lowering entries by claim. `Node.backed` says only
    that a claim cites witnesses and mutants; a replaying counter (#170) lowers it to COUNTERED,
    and whatever counts backing (SPEC-CLAIMS.md, `why`, `audit`, check's totals) reads this."""
    low = lowered(challenge_table(repo, model) if table is None else table)
    return {cid: status_of(n, low) for cid, n in model.current.items()}, low


def render(repo, model=None, table=None):
    snap, trust = repo.snapshot(), repo.trust()
    model, pins = model or Model(snap, trust), repo.pins()
    table = challenge_table(repo, model) if table is None else table
    status, low = standing(repo, model, table)
    rep = assessment(snap, trust)
    index = accept_index(model.recs)
    rows = sorted(model.current.values(), key=lambda n: id_key(n.id))
    live = [n for n in rows if not n.retired]
    retired = [n for n in rows if n.retired]
    count = {s: sum(status[n.id] == s for n in live if n.id in pins["sentences"])
             for s in ("BACKED", "COUNTERED", "UNBACKED", "INFORMATIVE")}
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
        f"countered {count['COUNTERED']} · unbacked {count['UNBACKED']} · informative {count['INFORMATIVE']} · "
        f"retired {len(retired)} · "
        f"records {len(snap.records)} · blobs {len(snap.blobs)}", "",
        "A witness is a case of `tests/<file>.py`; a mutant is an entry of `tests/mutants.py`",
        "(ids M…) or `tests/agent_mutants.py` (ids A…) that must make one of the cited cases",
        "fail. An UNBACKED sentence is an open question, listed below with the reason it is",
        "open; it closes nothing and establishes nothing. *Disposition* is Warrant's own",
        "assessment of the claim's duty in this store (trust `.warrant/trust.json`, default",
        f"profile, as of the latest record): a backed claim waits for its acceptor ({', '.join(pins['accept_by'])})",
        "until an acceptance is filed (`tools/claims.py accept`, signed by the acceptor's own key); the",
        "column names who accepted. A claim is COUNTERED when a counter blob that replays (below), filed",
        "by anyone with an admitted binding, lowers its backing: it counts as backed no longer.", "",
        "| ID | Statement | Witnesses | Mutants | Status | Disposition | Claim |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    counted = {x["claim"] for x in table.values() if x["kind"] == COUNTED}
    for n in live:
        wit = "; ".join(f"{t} {' '.join(cs)}" for t, cs in _grouped(n.doc["witnesses"])) or "—"
        mut = " ".join(n.doc["mutants"]) or "—"
        shown = status[n.id] + (" · CHALLENGED" if n.id in counted else "")
        if n.kind == "informative":
            shown += f": {n.doc['reason']}"
        acc = acceptors(model.recs, index, n.tid, 0) if n.backed else []
        out.append(f"| {n.id} | {cell(n.doc['text'])} | {cell(wit)} | {mut} | {cell(shown)} | {cell(disposition(rep, n, acc))} "
                   f"| `{n.tid[:12]}` |")
    opened = [n for n in live if n.status == "UNBACKED" or n.id in low]
    out += ["", "## Open questions", "",
            "A claim that was BACKED and lost its backing cites a counter blob that `check` replayed: under its",
            "patch, which changes only code the claim's own mutants change (compared by AST), at least one case",
            "fails and every witness of the claim passes. The witnesses are blind to a change in the code the",
            "sentence is about.",
            "The reason below is the filer's thesis; the replay is what admitted the loss.", ""]
    if opened:
        out += ["| ID | Statement | Why it is open | Claim |", "| --- | --- | --- | --- |"]
        out += [f"| {n.id} | {cell(n.doc['text'])} | {cell(_open_reason(n, low))} | `{n.tid[:12]}` |" for n in opened]
    else:
        out.append("None.")
    out += ["", "## Challenges", "",
            "Every challenge against a current claim, and what it does here. A counter blob that replays lowers",
            "the claim's backing whoever filed it (COUNTERED); with none that replays, a challenge by the claim's",
            "author or by an actor its duty is owed to or accepted by stands until the author answers (`check`",
            "refuses CHALLENGED); one by anyone else is a thesis: listed here, it lowers and blocks nothing.", ""]
    if table:
        out += ["| Claim | Challenge | Filed by | Counters | Effect |", "| --- | --- | --- | --- | --- |"]
        effect = {LOWERS: "lowers the backing (a counter replays)", COUNTED: "standing: the author must answer",
                  THESIS: "a thesis: lowers and blocks nothing"}
        for ch, x in sorted(table.items(), key=lambda kv: (id_key(kv[1]["claim"]), kv[0])):
            cs = " ".join(f"`{c[:12]}`" + ("" if c in x["replays"] else " (does not replay)") for c in x["counters"]) or "—"
            out.append(f"| {x['claim']} | `{ch[:12]}` | {cell(x['actor'])} | {cs} | {effect[x['kind']]} |")
    else:
        out.append("None.")
    doc = Document(model)
    if doc.current is not None:
        heads = [p["heading"] for p in doc.current["parts"] if isinstance(p, dict) and "heading" in p]
        out += ["", "## Document", "",
                f"SPEC.md is rendered from document version `{doc.tid[:12]}` ({len(doc.current['parts'])} parts). Its headings",
                "are not claims: each is pinned, line for line, in `.warrant/claims.json`, and the document may hold",
                "only those lines, once each, in order and each on its own line; the rendered SPEC.md must show",
                "exactly those headings. A title is free text that no witness backs, so a",
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


def _open_reason(n, low):
    if n.id in low:
        return "; ".join(f"countered by {x['actor']}: challenge {x['challenge'][:12]}, counter "
                         f"{', '.join(c[:12] for c in x['replays'])} replays" for x in low[n.id])
    return n.doc["reason"] or "(no reason given)"


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
    out += repo.bindings()[1]
    roles, why = repo.roles()
    pins_ = repo.pins()
    out += why + unpinned(roles, [AUTHOR] + pins_["owed_to"] + pins_["accept_by"], ".warrant/claims.json")
    model = Model(snap, trust)
    table = challenge_table(repo, model)
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
        standing = [ch for ch, x in table.items() if x["claim"] == cid and x["kind"] == COUNTED]
        if standing:
            out.append(("CHALLENGED", f"{cid}: standing challenge {', '.join(c[:12] for c in standing)}"
                        " against the current claim; supersede or retire it"))
        terms = duty_terms(model, n, pins)
        if terms:
            out.append(("CLAIM_DUTY_TERMS", f"{cid}: {terms}"))
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
        # The output, not the parts: the headings a reader of the rendered SPEC.md sees are
        # exactly the document's heading parts, in order (AMEND 2 of #166: a heading part
        # rendered inline was counted as a heading although SPEC.md showed none).
        shown = rendered_headings(want.decode())
        parts = [p["heading"] for p in doc.current["parts"] if isinstance(p, dict) and "heading" in p]
        if shown != parts:
            k = next((j for j, (x, y) in enumerate(zip(shown, parts)) if x != y), min(len(shown), len(parts)))
            out.append(("SPEC_HEADINGS_MISMATCH", f"the rendered SPEC.md shows {len(shown)} heading lines, the document "
                        f"has {len(parts)} headings; first difference at {k}: "
                        f"{(shown[k] if k < len(shown) else None)!r} vs {(parts[k] if k < len(parts) else None)!r}"))
    if not repo.projection.is_file():
        out.append(("PROJECTION_MISSING", "SPEC-CLAIMS.md does not exist; run tools/claims.py project"))
    elif repo.projection.read_bytes() != render(repo, model, table).encode():   # bytes: read_text() turns \r\n into \n
        out.append(("PROJECTION_STALE", "SPEC-CLAIMS.md is not the view of the records; run tools/claims.py project"))
    if not repo.witnesses.is_file():
        out.append(("WITNESSES_MISSING", "WITNESSES.md does not exist; run tools/claims.py project"))
    elif repo.witnesses.read_bytes() != render_witnesses(repo, model, table).encode():
        out.append(("WITNESSES_STALE", "WITNESSES.md is not the ledger of the records; run tools/claims.py project"))
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
    was_roles = read_roles(json.loads(files[".warrant/roles.json"]))[0] if ".warrant/roles.json" in files else {}
    was = admit_bindings(C.loads(files[".warrant/trust.json"]), legacy=True, roles=was_roles)[0] \
        if ".warrant/trust.json" in files else []
    roles = repo.roles()[0]
    conflicts = pin_conflicts(was, roles, rev)
    out += conflicts + bindings_kept([(a, p) for a, p in was if not (a in roles and roles[a] != p)], repo.bindings()[0], rev)
    then = Model(Snapshot(recs, blobs), trust_of(was + local_bindings()))
    out += new_counters(repo, model, set(recs))
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


def bindings_kept(was, now, rev):
    """BINDING_REMOVED for each binding admitted at the base and not admitted now: the first
    binding of an actor wins only if a later change can neither drop it nor put another
    binding of that actor before it (a binding is never deleted, like a record)."""
    have = set(now)
    return [("BINDING_REMOVED", f"{a} -> key {K.key_id(p)[:12]} is admitted at {rev[:12]} and not now")
            for a, p in was if (a, p) not in have]


def pin_conflicts(was, roles, rev):
    """ROLE_PIN_CONFLICT for each binding admitted at the base that a role pin now contradicts:
    a binding is never removed (BINDING_REMOVED), so a pin may not take its name from it."""
    return [("ROLE_PIN_CONFLICT", f"{a} is bound to key {K.key_id(p)[:12]} at {rev[:12]}; .warrant/roles.json now says "
             f"{_role_name(roles[a])}")
            for a, p in was if a in roles and roles[a] != p]


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


def duty_terms(model, n, pins):
    """Why claim `n`'s duty is not held by its author, owed to and accepted by whom
    .warrant/claims.json pins, with no release_by; or None. A key anyone may bind must not
    file a claim that only its own accomplice has to accept."""
    if n.retired or n.kind != "normative":
        return None
    b = model.recs[n.doc["duty"]]["body"]
    want = (n.rec["actor"], pins["owed_to"], pins["accept_by"], [])
    got = (b["holder"], b["owed_to"], b["accept_by"], b["release_by"])
    return None if got == want else (f"its duty has holder {got[0]!r}, owed_to {got[1]}, accept_by {got[2]}, "
                                     f"release_by {got[3]}; pinned: owed_to {want[1]}, accept_by {want[2]}, no release_by")


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


@functools.lru_cache(maxsize=512)
def scope_dumps(src):
    """{scope: dump}: each function (qualified by its classes) and `<module>` (everything
    outside functions, classes' other statements included), as ast.dump without positions,
    comments, layout or docstrings. Raises SyntaxError if `src` does not parse."""
    out = {}
    out["<module>"] = ast.dump(_hollow(ast.parse(src), "", out))
    return out


@functools.lru_cache(maxsize=4096)
def changed_scopes(path, old, new):
    """{(path, scope)} whose AST differs between `old` and `new` (scope_dumps): a comment,
    whitespace or a docstring changes no scope. Raises SyntaxError if `new` does not parse."""
    a, b = scope_dumps(old) if old else {}, scope_dumps(new)
    return frozenset((path, k) for k in set(a) | set(b) if a.get(k) != b.get(k))


STMT_LISTS = ("body", "handlers", "orelse", "finalbody", "cases")


def _units(stmts, scope, depth, out, top=True, nodes=None):
    """Append (scope, depth, dump) for each statement of `stmts`, in source order: a simple
    statement whole, a compound one by its header (the node with its statement lists
    emptied) followed by its children; a docstring is no unit. `nodes`, when given, gets
    each unit's node, in the same order (statement_lines)."""
    for k, st in enumerate(stmts):
        if top and k == 0 and isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) \
                and isinstance(st.value.value, str):
            continue
        lists = [(f, getattr(st, f)) for f in STMT_LISTS if isinstance(getattr(st, f, None), list)]
        if nodes is not None:
            nodes.append(st)
        if not lists:
            out.append((scope, depth, ast.dump(st)))
            continue
        head = copy.copy(st)
        for f, _ in lists:
            setattr(head, f, [])
        out.append((scope, depth, ast.dump(head)))
        inner = scope + st.name + "." if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else scope
        for f, children in lists:
            _units(children, inner, depth + 1, out, top=f == "body" and inner != scope, nodes=nodes)


@functools.lru_cache(maxsize=512)
def statement_units(src):
    """[(scope, depth, dump)]: the statements of `src` at statement granularity (_units),
    without positions, comments, layout or docstrings. Raises SyntaxError."""
    out = []
    _units(ast.parse(src).body, "", 0, out)
    return out


CODELESS = frozenset({tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
                      tokenize.ENCODING, tokenize.ENDMARKER})


def code_lines(src):
    """The numbers of the lines of `src` that hold a token of code: not blank, not only a
    comment. A token spanning lines (a triple-quoted string) marks each of them."""
    out = set()
    for t in tokenize.generate_tokens(io.StringIO(src).readline):
        if t.type not in CODELESS:
            out.update(range(t.start[0], t.end[0] + 1))
    return out


def _extent(st):
    """(first, last) source line of a statement node, decorators included; a match case has no
    position of its own and runs from its pattern to the end of its body."""
    if isinstance(st, ast.match_case):
        return st.pattern.lineno, st.body[-1].end_lineno
    return min([st.lineno] + [d.lineno for d in getattr(st, "decorator_list", [])]), st.end_lineno


@functools.lru_cache(maxsize=512)
def statement_lines(src):
    """[(scope, function, lines)] parallel to statement_units(src): unit i's own source lines,
    the lines of its extent outside its children's extents (a docstring child included) that
    hold code (code_lines); a compound header sharing its only line with its body keeps that
    line. `function` is the qualified name of the function the unit belongs to (a def header
    to its own function), or None at module or class level. Raises SyntaxError."""
    nodes, units = [], []
    _units(ast.parse(src).body, "", 0, units, nodes=nodes)
    code, out = code_lines(src), []
    funcs = {sc + st.name for (sc, _, _), st in zip(units, nodes) if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for (scope, _, _), st in zip(units, nodes):
        first, last = _extent(st)
        own = set(range(first, last + 1))
        for f in STMT_LISTS:
            for child in getattr(st, f, None) or []:
                a, b = _extent(child)
                own -= set(range(a, b + 1))
        own = own & code or {first}
        if isinstance(st, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = scope + st.name
        else:
            parts = scope.rstrip(".").split(".") if scope else []
            fn = next((".".join(parts[:k]) for k in range(len(parts), 0, -1) if ".".join(parts[:k]) in funcs), None)
        out.append((scope, fn, frozenset(own)))
    return out


@functools.lru_cache(maxsize=4096)
def changed_statements(path, old, new):
    """{(path, key)}: the statements of `old` a change to `new` replaces or deletes, key
    ("at", i) for its i-th unit, and the places it inserts new ones, ("insert", i) before
    old unit i: both sides' units aligned (difflib), so a key names the same statement for
    any change made to the same `old`. Raises SyntaxError if `new` does not parse."""
    a, b = statement_units(old) if old else [], statement_units(new)
    out = set()
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            out |= {(path, ("at", i)) for i in range(i1, i2)}
        if op == "insert" or (op == "replace" and j2 - j1 > i2 - i1):
            out.add((path, ("insert", i1)))
    return frozenset(out)


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


# ---------------------------------------------------------------- challenges (open circle, part C)

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


# ---------------------------------------------------------------- acceptances (open circle, part B)

def accept_index(recs):
    """{(transition, item): {actor}} of authentic accept records, each under the evidence it
    names: an acceptance counts only for exactly that (transition, item, evidence set)."""
    out = {}
    for r in recs.values():
        if r["type"] == "accept":
            b = r["body"]
            out.setdefault((b["transition"], b["item"], tuple(sorted(b["evidence"]))), set()).add(r["actor"])
    return out


def acceptors(recs, index, tid, item):
    """The actors who accepted exactly (tid, item and that item's evidence); item None: the
    transition's results, its whole evidence (SPEC §3.3)."""
    t = recs.get(tid)
    if t is None or t["type"] != "transition":
        return []
    b = t["body"]
    if item is None:
        want = b["evidence"]
    elif 0 <= item < len(b["closes"]):
        want = b["closes"][item]["evidence"]
    else:
        return []
    want = tuple(sorted(want))
    return sorted({a for (t, i, ev), actors in index.items() if t == tid and i == item and ev == want for a in actors})


# ---------------------------------------------------------------- the witness ledger (open circle, part D)

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


def ledger(model, table, bindings):
    """{actor: row}: what each actor's records did, counted from the records (and, for counters
    standing now, from `table`). It grants nothing; no rule reads it. Row:
      key         key ids of the admitted bindings of the actor
      authored    claim lineages the actor began (a claim transition with no previous)
      accepts     accept records the actor filed
      refuted     the actor's acceptances of a closure later refuted: a claim transition against
                  which a counter replays now (LOWERS) or a downgrade cites a counter
                  (downgrade_counters); or a closure a challenge targets that a revalidation names
      challenges  challenge records the actor filed
      counters    COUNTER blobs the actor filed (the earliest record citing one is the actor's)
      now         of those, counters that lower a current claim's backing now
      downgrade   of those, counters a downgrade cites
      rebacks     BACKED claim transitions the actor filed that supersede a claim a counter is
                  against (the answer to a counter: a witness that sees it)"""
    recs = model.recs
    rows = {a: {"key": [], "authored": 0, "accepts": [], "refuted": [], "challenges": 0, "counters": [], "now": [],
                "downgrade": [], "rebacks": []}
            for a in sorted({r["actor"] for r in recs.values()} | {a for a, _ in bindings})}
    for a, p in bindings:
        rows[a]["key"].append(K.key_id(p)[:12])
    for n in model.nodes.values():
        if n.doc["previous"] is None:
            rows[n.rec["actor"]]["authored"] += 1
    cites = counter_citations(model)
    downs = downgrade_counters(model)
    now = {c for x in table.values() if x["kind"] == LOWERS for c in x["replays"]}
    against = {c: model.snap.json_blob(c).get("against") for c in cites}
    for c, rids in sorted(cites.items()):
        first = min(rids, key=lambda rid: (recs[rid]["at"], rid))
        row = rows[recs[first]["actor"]]
        row["counters"].append(c)
        if c in now:
            row["now"].append(c)
        if c in downs:
            row["downgrade"].append(c)
    refuting = {against[c] for c in now | set(downs)}
    revalidated = {x for r in recs.values() if r["type"] == "transition" for m in r["body"]["closes"]
                   if m["act"] == "revalidate" for x in m["revalidates"]}
    challenged = {(r["body"]["target"], r["body"]["item"]) for r in recs.values() if r["type"] == "challenge"}
    for rid, r in sorted(recs.items()):
        if r["type"] == "challenge":
            rows[r["actor"]]["challenges"] += 1
        elif r["type"] == "accept":
            b = r["body"]
            rows[r["actor"]]["accepts"].append(rid)
            if b["transition"] in refuting and b["transition"] in model.nodes:
                rows[r["actor"]]["refuted"].append((rid, b["transition"], "a counter against the accepted claim replays"))
            elif (b["transition"], b["item"]) in challenged and b["transition"] in revalidated:
                rows[r["actor"]]["refuted"].append((rid, b["transition"], "the accepted closure was challenged, then revalidated"))
    countered = set(against.values())
    for n in model.nodes.values():
        prev = n.doc["previous"]
        if n.backed and prev and prev["transition"] in countered:
            rows[n.rec["actor"]]["rebacks"].append(n.tid)
    return rows


def render_witnesses(repo, model, table):
    """WITNESSES.md: the ledger (ledger) as a view."""
    bindings = repo.bindings()[0]
    rows = ledger(model, table, bindings)
    out = [
        "# Witness ledger (generated view)", "",
        "Generated by `python tools/claims.py project` from the Warrant 2 records in",
        "`.warrant/store/` and the admitted bindings of `.warrant/trust.json`. **It grants",
        "nothing, and no rule reads it**: `check`, the engine and every profile ignore this",
        "file; `check` only refuses it when it is not the rendering of the records (compared",
        "as bytes). A count says what an actor's signed records did, not who may act: that is",
        "the duty's and the receiver's profile's (SPEC §4.6, §6).", "",
        "- **claims authored**: claim lineages the actor began.",
        "- **acceptances**: accept records the actor filed; **later refuted**: of those, ones",
        "  accepting a claim against which a counter replays now or a downgrade cites a counter,",
        "  or a closure that a challenge targets and a revalidation names.",
        "- **challenges**: challenge records the actor filed.",
        "- **counters**: counter blobs (`warrant-claims/counter@1`) the actor's record cited",
        "  first; **lowering now**: of those, ones that replay against a current BACKED claim",
        "  (its backing is lowered); **cited by a downgrade**: ones a BACKED-to-UNBACKED",
        "  supersession cites (`check --base` replays those when the downgrade is filed).",
        "- **re-backs**: BACKED claims the actor filed over a claim a counter is against.", "",
        "| Actor | Key | Claims authored | Acceptances | Later refuted | Challenges | Counters | Lowering now "
        "| Cited by a downgrade | Re-backs |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for a, row in rows.items():
        out.append(f"| {cell(a)} | {' '.join(f'`{k}`' for k in row['key']) or '—'} | {row['authored']} "
                   f"| {len(row['accepts'])} | {len(row['refuted'])} | {row['challenges']} | {len(row['counters'])} "
                   f"| {len(row['now'])} | {len(row['downgrade'])} | {len(row['rebacks'])} |")
    refuted = [(a, x) for a, row in rows.items() for x in row["refuted"]]
    out += ["", "## Acceptances later refuted", ""]
    out += [f"- {cell(a)}: accept `{rid[:12]}` of `{tid[:12]}`: {why}" for a, (rid, tid, why) in refuted] or ["None."]
    out += ["", "## Counters", ""]
    counters = [(c, a) for a, row in rows.items() for c in row["counters"]]
    if counters:
        out += ["| Counter | Filed by | Claim | Against | Lowering now | Cited by a downgrade |",
                "| --- | --- | --- | --- | --- | --- |"]
        for c, a in sorted(counters, key=lambda x: (str(model.snap.json_blob(x[0]).get("claim")), x[0])):
            doc = model.snap.json_blob(c)
            out.append(f"| `{c[:12]}` | {cell(a)} | {cell(str(doc.get('claim')))} | `{str(doc.get('against'))[:12]}` "
                       f"| {'yes' if c in rows[a]['now'] else 'no'} | {'yes' if c in rows[a]['downgrade'] else 'no'} |")
    else:
        out.append("None.")
    return "\n".join(out) + "\n"


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
        # extends the author's chain (SPEC §3), its head read under the checker's own trust
        return self.store.append(rtype, self.actor, at, body, self.key, self.repo.trust())

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
        if doc.current is not None and doc.nodes[doc.tid][0]["actor"] != self.actor:
            raise Refused(f"the document is {doc.nodes[doc.tid][0]['actor']}'s: only its author files its next version",
                          "LINEAGE_NOT_AUTHOR")
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
        if previous is not None and previous.rec["actor"] != self.actor:
            raise Refused(f"{cid} is {previous.rec['actor']}'s claim: only its author supersedes it; a counter is "
                          "filed as a challenge (tools/claims.py challenge)", "LINEAGE_NOT_AUTHOR")
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
        if cur.rec["actor"] != self.actor:
            raise Refused(f"{cid} is {cur.rec['actor']}'s claim: only its author retires it", "LINEAGE_NOT_AUTHOR")
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
    if cur.rec["actor"] != a.actor:
        raise Refused(f"{a.id} is {cur.rec['actor']}'s claim: only its author retires it", "LINEAGE_NOT_AUTHOR")
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
    table = challenge_table(repo, model)
    repo.spec.write_bytes(render_spec(model, doc.current).encode())
    repo.projection.write_bytes(render(repo, model, table).encode())
    repo.witnesses.write_bytes(render_witnesses(repo, model, table).encode())


def cmd_keygen(repo, a):
    out = Path(a.out).expanduser().resolve()
    if repo.root.resolve() in out.parents:
        raise Refused("the seed must live outside the repository")
    if out.exists():
        raise Refused(f"{out} exists")
    key = W.Key.generate()
    doc = None if a.no_bind else bound_document(repo, key, a.actor)     # refused before the seed is written
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(key.seed_hex() + "\n")
    out.chmod(0o600)
    if doc is None:
        print(f"{a.actor}: public key {key.public} (key {key.id}), not bound; seed at {out}")
        return
    write_bindings(repo, doc)
    print(f"{a.actor}: key {key.id} bound in .warrant/trust.json with its proof; seed at {out}")


def cmd_pin(repo, a):
    """Pin --actor's role to the public key of seed --key in .warrant/roles.json (a reviewed
    config change: who a role is). Refused for a collective role, or when an admitted binding
    of the actor has another key (ROLE_PIN_CONFLICT)."""
    p = Path(a.key or os.environ.get("WARRANT_CLAIMS_KEY") or "")
    if not p.is_file():
        raise Refused("a seed is needed: --key PATH (its public key is pinned; the seed stays where it is)")
    key = W.Key.from_seed_hex(p.read_text())
    doc = json.loads(repo.roles_path.read_text()) if repo.roles_path.is_file() else {"roles": ROLES, "actors": {}}
    roles, problems = read_roles(doc)
    if problems:
        raise Refused("; ".join(w for _, w in problems), "ROLES_SHAPE")
    if roles.get(a.actor) == COLLECTIVE:
        raise Refused(f"{a.actor} is a collective role: no key signs as it", "BINDING_ROLE_COLLECTIVE")
    other = [pub for act, pub in repo.bindings()[0] if act == a.actor and pub != key.public]
    if other:
        raise Refused(f"{a.actor} is bound to key {K.key_id(other[0])[:12]}", "ROLE_PIN_CONFLICT")
    doc["actors"][a.actor] = key.public
    repo.roles_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"{a.actor}: role pinned to key {key.id} in .warrant/roles.json")


def bound_document(repo, key, actor):
    """The bindings document with `key` bound to `actor` and its proof (binding_proof): an
    entry of the same actor and key gets the proof, otherwise one is appended. Refused, with
    the code `check` would give, when the result would not admit the binding. A trust/2 file
    (before bindings carried proofs) is read as entries without proofs."""
    try:
        R.check_actor(actor)
    except R.Invalid as e:
        raise Refused(f"{actor!r} is not an actor id (SPEC-3-21): {e}", "BINDING_ACTOR_SHAPE") from e
    doc = C.loads(repo.trust_path.read_bytes()) if repo.trust_path.is_file() else {"bindings": BINDINGS, "keys": []}
    if isinstance(doc, dict) and doc.get("warrant") == "trust/2":
        doc = {"bindings": BINDINGS, "keys": [dict(k) for k in doc.get("keys", [])]}
    entry = {"actor": actor, "public": key.public, "proof": binding_proof(key, actor)}
    keys = [entry if isinstance(k, dict) and k.get("actor") == actor and k.get("public") == key.public else k
            for k in doc.get("keys", [])]
    doc = {"bindings": BINDINGS, "keys": keys if entry in keys else keys + [entry]}
    admitted, problems = admit_bindings(doc, roles=repo.roles()[0])
    if (actor, key.public) not in admitted:
        mine = [(c, w) for c, w in problems if f"keys[{doc['keys'].index(entry)}]" in w]
        code, why = mine[0] if mine else ("BINDINGS_SHAPE", "; ".join(w for _, w in problems))
        raise Refused(why, code)
    return doc


def write_bindings(repo, doc):
    repo.trust_path.parent.mkdir(parents=True, exist_ok=True)
    repo.trust_path.write_bytes(C.canon(doc))


def cmd_bind(repo, a):
    """Bind the key of seed --key to --actor with its proof of possession. Nobody admits it:
    `check` does, mechanically (admit_bindings)."""
    p = Path(a.key or os.environ.get("WARRANT_CLAIMS_KEY") or "")
    if not p.is_file():
        raise Refused("a signing seed is needed: --key PATH or WARRANT_CLAIMS_KEY")
    key = W.Key.from_seed_hex(p.read_text())
    write_bindings(repo, bound_document(repo, key, a.actor))
    print(f"{a.actor}: key {key.id} bound in .warrant/trust.json with its proof")


def cmd_trust(repo, a):
    """Print the trust/2 document of the admitted bindings, for `warrant --trust` (stdout)."""
    sys.stdout.write(C.canon(Trust.document(repo.bindings()[0])).decode() + "\n")


def pending_for(rep, did, actor):
    """The PENDING candidates of duty `did` whose acceptance `actor` is still awaited."""
    r = rep["duties"].get(did)
    return [] if r is None else [c for c in r["candidates"]
                                  if c["verdict"] == "PENDING" and actor in (c.get("waiting_for") or [])]


def not_acceptor(actor, what, accept_by):
    return Refused(f"{actor} is not in the accept_by of {what} ({', '.join(accept_by) or 'nobody'}): an acceptance by "
                   "anyone else admits nothing (SPEC §4.2, rule 5). A receiver's profile (SPEC §4.6) chooses whose "
                   "acceptance closes a transition's results and whose challenges count; a duty's closure needs its "
                   "own accept_by in every profile", "NOT_AN_ACCEPTOR")


def accept_targets(repo, model, rep, actor, cids):
    """[(claim id, transition, evidence)] to accept, all validated before anything is filed. A
    BACKED claim's closure is filed with it, so it is pending until every acceptor of its duty
    has accepted: whoever accepted it already has nothing left to accept."""
    table, out, index = None, [], accept_index(model.recs)
    for cid in cids:
        n = model.current.get(cid)
        if n is None or n.retired:
            raise Refused(f"{cid}: no current claim", "NOT_A_CLOSURE")
        if not n.backed:
            raise Refused(f"{cid} is {n.status}: it closes nothing, so nothing awaits acceptance", "NOT_A_CLOSURE")
        accept_by = model.recs[n.doc["duty"]]["body"]["accept_by"]
        if actor not in accept_by:
            raise not_acceptor(actor, f"{cid}'s duty", accept_by)
        if actor in acceptors(model.recs, index, n.tid, 0):
            raise Refused(f"{cid}: {actor} accepted its closure {n.tid[:12]} already "
                          f"({rep['duties'][n.doc['duty']]['disposition']})", "NOT_PENDING")
        table = challenge_table(repo, model) if table is None else table
        low = lowered(table).get(cid)
        if low:
            raise Refused(f"{cid}: a counter that replays lowers its backing (challenge {low[0]['challenge'][:12]} by "
                          f"{low[0]['actor']}); accepting it would accept a refuted closure", "COUNTERED")
        closes = n.rec["body"]["closes"]
        out.append((cid, n.tid, closes[0]["evidence"] if closes else []))
    return out


def cmd_accept(repo, a):
    """File an accept record of exactly each claim's pending closure, signed by --actor's key."""
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    model = author.model()
    rep = assessment(model.snap, repo.trust())
    cids = list(dict.fromkeys(a.claim))
    if a.all:
        status, _ = standing(repo, model)
        cids += sorted((n.id for n in model.current.values() if status[n.id] == "BACKED" and n.id not in cids
                        and any(c["transition"] == n.tid for c in pending_for(rep, n.doc["duty"], a.actor))), key=id_key)
    if not cids:
        raise Refused("name a claim (--claim ID) or --all", "NOT_A_CLOSURE")
    targets = accept_targets(repo, model, rep, a.actor, cids)
    at = author.at()
    for cid, tid, ev in targets:
        print(f"{cid}: accepted {tid[:12]} by {author.put('accept', R.accept(tid, 0, ev), at)}")


def cmd_challenge(repo, a):
    """File a challenge against a claim's current transition, signed by --actor's key, carrying
    --counter-file when given. A counter must replay before anything is written; a challenge
    with none counts only if its filer does (counts_against)."""
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    n = author.model().current.get(a.claim)
    if n is None or n.retired:
        raise Refused(f"{a.claim}: no current claim", "NOT_A_CLOSURE")
    ev = []
    if a.counter_file:
        data = counter_file_bytes(a.counter_file)
        h = C.digest(data)
        author.pending[h] = data
        why = replay_counter(repo, author.model().snap, h, n) if n.backed else "the claim is not BACKED"
        if why:
            raise Refused(f"{a.claim}: the counter does not replay: {why}", "COUNTER_NOT_REPLAYED")
        author.store.put_blob(data)
        author.pending = {}
        ev = [h]
    item = 0 if n.rec["body"]["closes"] else None
    rid = author.put("challenge", R.challenge(n.tid, a.because, ev, item), author.at())
    print(f"{a.claim}: challenge {rid}")


def default_base(repo):
    try:
        return git(repo, "rev-parse", "--verify", "origin/master^{commit}").decode().strip()
    except subprocess.CalledProcessError:
        return None


# ---------------------------------------------------------------- audit (blind witnesses)

MATRIX = "warrant-mutants/matrix@1"
GIT_NO_GC = ("-c", "gc.auto=0")             # no automatic gc while a fixture is cloned (run 39537906378)


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


# ---------------------------------------------------------------- why (a statement's claims, obligations, goals)

WHY_ROOTS = ("warrant", "warrant_agent", "tools")      # where the mutant harnesses edit: the files `why` reads
UNCOVERED_ROOTS = ("warrant", "warrant_agent")          # the code SPEC.md is about: `why --uncovered`'s default
WHY_LINE = re.compile(r"^(.+):([1-9][0-9]{0,6})\Z")     # FILE:LINE; \Z: `$` admits a trailing newline
CLAIMED, NO_CLAIM, NOT_A_STATEMENT = "CLAIMED", "NO_CLAIM", "NOT_A_STATEMENT"


def why_files(repo):
    """{relative path: Path} of the Python files under WHY_ROOTS. A command-line FILE is looked
    up here and never opened as given: `why` reads only files of this list."""
    out = {}
    for top in WHY_ROOTS:
        d = repo.root / top
        if d.is_dir():
            out.update({q.relative_to(repo.root).as_posix(): q for q in sorted(d.rglob("*.py"))
                        if "__pycache__" not in q.parts})
    return out


def _roadmap_links(repo):
    """{duty id: [link]}: each obligation (tools/roadmap.py) whose `serves` or `requires` names
    the duty, with its goal; {} when the repository has no roadmap configuration."""
    sys.modules.setdefault("claims", sys.modules[__name__])      # roadmap.py reads this module as `claims`
    spec = importlib.util.spec_from_file_location("roadmap", Path(__file__).resolve().parent / "roadmap.py")
    rm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rm)
    try:
        m = rm.Roadmap(repo.root).model()
    except rm.Refused:
        return {}
    out = {}
    for did in sorted(m.obligations):
        body, key = m.recs[did]["body"], m.goal_of(did)
        cur = [f for f in m.goals.get(key, []) if f.state == rm.CURRENT] or m.goals.get(key, [])[-1:]
        for rel in ("serves", "requires"):
            for x in body[rel]:
                out.setdefault(x, []).append({
                    "obligation": did, "relation": rel, "statement": m.rep["duties"][did]["statement"],
                    "state": m.rep["duties"][did]["disposition"], "goal": key, "goal_state": m.goal_state(key),
                    "goal_text": cur[0].text if cur else None})
    return out


class Why:
    """From a statement of a source file to the mutants that change it (Repo.mutant_statements,
    a key ("at", i) for unit i: an insertion before a statement changes none), the claims citing
    those mutants that are BACKED in the view (standing: a claim a replaying counter lowered is
    COUNTERED, shown with its counters and never as backing), the roadmap obligations whose
    serves or requires name the backing claims' duties, and the goals those obligations answer.
    Everything is read from the files and the records as they are now."""

    def __init__(self, repo):
        self.repo = repo
        self.files = why_files(repo)
        known = repo.mutants()
        model = Model(repo.snapshot(), repo.trust())
        status, self.low = standing(repo, model)
        self.cited = {}             # mutant id -> [Node]: the current claims citing it that are BACKED in the view
        self.countering = {}        # mutant id -> [Node]: those COUNTERED (a replaying counter lowered them)
        for n in sorted(model.current.values(), key=lambda n: id_key(n.id)):
            index = {"BACKED": self.cited, "COUNTERED": self.countering}.get(status[n.id])
            for mid in n.doc["mutants"] if index is not None else ():
                index.setdefault(mid, []).append(n)
        self.changes = {}           # (path, unit index) -> {mutant id}: the mutants that change unit i
        self.inserts = {}           # (path, unit index) -> {mutant id}: those inserting before it (shown, not counted)
        for mid in sorted(known):
            for path, (kind, i) in repo.mutant_statements(mid):
                (self.changes if kind == "at" else self.inserts).setdefault((os.path.normpath(path), i), set()).add(mid)
        self.links = _roadmap_links(repo)

    def units(self, path):
        """[(scope, function, own lines)] of a file of `files`; Refused WHY_FILE if it does not parse."""
        try:
            return statement_lines(self.files[path].read_text())
        except SyntaxError as e:
            raise Refused(f"{path} does not parse: {e}", "WHY_FILE") from e

    def covered(self, path, i):
        return any(mid in self.cited for mid in self.changes.get((path, i), ()))

    def at(self, path, line):
        """The answer for one line: its statements and what they serve (`why FILE:LINE`)."""
        if path not in self.files:
            raise Refused(f"{path}: not a Python file under {', '.join(r + '/' for r in WHY_ROOTS)} of this repository",
                          "WHY_FILE")
        src = self.files[path].read_text()
        lines = src.splitlines()
        if line > len(lines):
            raise Refused(f"{path} has no line {line}", "WHY_LINE")
        try:
            units = statement_lines(src)
        except SyntaxError as e:
            raise Refused(f"{path} does not parse: {e}", "WHY_FILE") from e
        hits = [i for i, (_, _, own) in enumerate(units) if line in own]
        stmts, claims, countered, obligations, goals = [], {}, {}, {}, {}
        for i in hits:
            scope, fn, own = units[i]
            mids = sorted(self.changes.get((path, i), ()), key=_mid_key)
            stmts.append({"index": i, "function": fn, "lines": [min(own), max(own)], "mutants": mids,
                          "cited": [mid for mid in mids if mid in self.cited],
                          "inserted_before": sorted(self.inserts.get((path, i), ()), key=_mid_key)})
            for mid in mids:
                for n in self.cited.get(mid, []):
                    c = claims.setdefault(n.id, {"claim": n.id, "transition": n.tid, "duty": n.doc["duty"],
                                                 "text": n.doc["text"], "via": []})
                    c["via"] = sorted(set(c["via"]) | {mid}, key=_mid_key)
                for n in self.countering.get(mid, []):
                    c = countered.setdefault(n.id, {"claim": n.id, "transition": n.tid, "duty": n.doc["duty"],
                                                    "status": "COUNTERED", "via": [],
                                                    "challenges": [{"challenge": x["challenge"], "actor": x["actor"],
                                                                    "counters": x["replays"]} for x in self.low[n.id]]})
                    c["via"] = sorted(set(c["via"]) | {mid}, key=_mid_key)
        for c in claims.values():
            for ln in self.links.get(c["duty"], []):
                o = obligations.setdefault(ln["obligation"], dict(ln, claims=[]))
                if c["claim"] not in o["claims"]:
                    o["claims"].append(c["claim"])
                if ln["goal"]:
                    goals[ln["goal"]] = {"goal": ln["goal"], "state": ln["goal_state"], "text": ln["goal_text"]}
        status = NOT_A_STATEMENT if not hits else CLAIMED if claims else NO_CLAIM
        return {"file": path, "line": line, "status": status, "source": (lines[line - 1:line] or [""])[0],
                "statements": stmts, "claims": sorted(claims.values(), key=lambda c: id_key(c["claim"])),
                "countered": sorted(countered.values(), key=lambda c: id_key(c["claim"])),
                "obligations": [obligations[d] for d in sorted(obligations)],
                "goals": [goals[k] for k in sorted(goals, key=lambda k: int(k[1:]))]}

    def uncovered(self, paths):
        """Each statement of `paths` that no cited mutant changes, the functions none of whose
        statements is covered (largest first), and the counts (`why --uncovered`)."""
        stmts, funcs, total, covered, mutated, lowered_only = [], {}, 0, 0, 0, 0
        for path in paths:
            lines = self.files[path].read_text().splitlines()
            for i, (scope, fn, own) in enumerate(self.units(path)):
                ok = self.covered(path, i)
                total, covered, mutated = total + 1, covered + ok, mutated + bool(self.changes.get((path, i)))
                if fn is not None:
                    f = funcs.setdefault((path, fn), {"file": path, "function": fn, "line": min(own), "statements": 0,
                                                      "covered": 0})
                    f["statements"] += 1
                    f["covered"] += ok
                    f["line"] = min(f["line"], min(own))
                if not ok:
                    low = sorted({n.id for mid in self.changes.get((path, i), ()) for n in self.countering.get(mid, [])},
                                 key=id_key)
                    lowered_only += bool(low)
                    stmts.append({"file": path, "line": min(own), "index": i, "function": fn, "countered": low,
                                  "source": lines[min(own) - 1].strip()})
        bare = sorted((f for f in funcs.values() if not f["covered"]), key=lambda f: (-f["statements"], f["file"], f["line"]))
        return {"files": list(paths), "statements": total, "covered": covered, "mutated": mutated,
                "countered_only": lowered_only, "uncovered": stmts,
                "functions": bare, "functions_total": len(funcs)}


def _mid_key(mid):
    return mid[0], int(re.sub(r"\D", "", mid) or 0)


def render_why(d):
    out = [f"{d['file']}:{d['line']} [{d['status']}] {d['source'].strip()}"]
    if d["status"] == NOT_A_STATEMENT:
        out.append("  no statement owns this line (blank, a comment or a docstring)")
    for s in d["statements"]:
        uncited = [m for m in s["mutants"] if m not in s["cited"]]
        out.append(f"  statement {s['index']} of {s['function'] or '<module>'} (lines {s['lines'][0]}-{s['lines'][1]}): "
                   + (f"changed by {', '.join(s['mutants'])}" if s["mutants"] else "no mutant changes it")
                   + (f"; not cited by a BACKED claim: {', '.join(uncited)}" if uncited else "")
                   + (f"; inserting before it (not counted): {', '.join(s['inserted_before'])}" if s["inserted_before"] else ""))
    for c in d["claims"]:
        out.append(f"  claim {c['claim']} (duty {c['duty'][:12]}, via {', '.join(c['via'])}): {c['text']}")
    for c in d["countered"]:
        out.append(f"  claim {c['claim']} [COUNTERED] (via {', '.join(c['via'])}), not backing: lowered by "
                   + "; ".join(f"challenge {x['challenge'][:12]} of {x['actor']} (counter {', '.join(h[:12] for h in x['counters'])})"
                               for x in c["challenges"]))
    for o in d["obligations"]:
        out.append(f"  obligation {o['obligation'][:12]} [{o['state']}] {o['relation']} {', '.join(o['claims'])}: "
                   f"{o['statement']} -> {o['goal'] or 'no goal'}")
    for g in d["goals"]:
        out.append(f"  goal {g['goal']} [{g['state']}] {g['text']}")
    if d["status"] == NO_CLAIM:
        out.append("  no claim: no mutant a claim BACKED in the view cites changes this statement")
    return "\n".join(out) + "\n"


def render_uncovered(d):
    out = [f"UNCOVERED {s['file']}:{s['line']} {s['function'] or '<module>'}: {s['source'][:100]}"
           + (f" (COUNTERED: {', '.join(s['countered'])})" if s["countered"] else "") for s in d["uncovered"]]
    out += [f"FUNCTION {f['file']}:{f['line']} {f['function']}: none of its {f['statements']} statements is covered"
            for f in d["functions"]]
    n, c = d["statements"], d["covered"]
    out.append(f"WHY: {n} statements in {len(d['files'])} files; {c} covered (changed by a mutant a claim BACKED in the view "
               f"cites), {n - c} uncovered ({100 * c // max(n, 1)}% covered), {d['countered_only']} of them changed by a COUNTERED claim's mutant; "
               f"{d['mutated']} changed by some mutant; "
               f"{len(d['functions'])} of {d['functions_total']} functions have no covered statement")
    return "\n".join(out) + "\n"


def _why_path(repo, arg):
    """A command-line FILE as a key of why_files: relative to the repository root."""
    return os.path.normpath(os.path.relpath(arg, repo.root) if os.path.isabs(arg) else arg)


def cmd_why(repo, a):
    if bool(a.target) == bool(a.uncovered is not None):
        raise Refused("give FILE:LINE, or --uncovered [FILE]", "WHY_USAGE")
    w = Why(repo)
    if a.target:
        m = WHY_LINE.match(a.target)
        if not m:
            raise Refused(f"{a.target!r} is not FILE:LINE", "WHY_USAGE")
        d = w.at(_why_path(repo, m.group(1)), int(m.group(2)))
        print(json.dumps(d, indent=1, ensure_ascii=False) if a.json else render_why(d), end="\n" if a.json else "")
        return 0
    if a.uncovered:
        path = _why_path(repo, a.uncovered)
        if path not in w.files:
            raise Refused(f"{a.uncovered}: not a Python file under {', '.join(r + '/' for r in WHY_ROOTS)}", "WHY_FILE")
        paths = [path]
    else:
        paths = [p for p in w.files if p.split("/")[0] in UNCOVERED_ROOTS]
    d = w.uncovered(paths)
    print(json.dumps(d, indent=1, ensure_ascii=False) if a.json else render_uncovered(d), end="\n" if a.json else "")
    return 0


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
    status, _ = standing(repo, model)
    print(f"CLAIMS: {len(live)} current ({sum(status[n.id] == 'BACKED' for n in live)} backed, "
          f"{sum(status[n.id] == 'COUNTERED' for n in live)} countered, "
          f"{sum(n.kind == 'normative' and not n.backed for n in live)} unbacked, "
          f"{sum(n.kind == 'informative' for n in live)} informative), "
          f"{sum(n.retired for n in model.current.values())} retired; base {base[:12] if base else 'none'}; "
          f"{'OK' if not problems else f'{len(problems)} refused'}")
    return 1 if problems else 0


# ---------------------------------------------------------------- selftest

_CASE_RUNNER = None


def _run_registered_case(i):
    return _CASE_RUNNER(i)


def _found(blind, cid, mid):
    return [b for b in blind if b["claim"] == cid and b["mutant"] == mid]


def _clone(fix, d):
    subprocess.run(["git", *GIT_NO_GC, "clone", "-q", "--no-local", str(fix), str(d)], capture_output=True, check=True)
    return Repo(d)


def _audit_pick(r, defs):
    """(claim c, mutant x overlapping c's scopes, mutant y disjoint from them) of the fixture, or None."""
    model = Model(r.snapshot(), r.trust())
    for n in sorted((n for n in model.current.values() if n.backed and not n.retired), key=lambda n: id_key(n.id)):
        mine = {sc for mid in n.doc["mutants"] for sc in r.mutant_scopes(mid)}
        xs = [mid for mid in sorted(defs) if mid not in n.doc["mutants"] and r.mutant_scopes(mid) & mine]
        ys = [mid for mid in sorted(defs) if r.mutant_scopes(mid) and not r.mutant_scopes(mid) & mine]
        if mine and xs and ys:
            return n, xs[0], ys[0]
    return None


def _audit_synthetic(fix, work):
    """(1) Matrices built here over the fixture's own mutants: a planted blind claim and each guard."""
    r = _clone(fix, work / "audit-synthetic")
    r.mutants()
    core = _harness(r, "mutants.py")
    defs = {m[0]: m for name, _ in HARNESSES for m in (core if name == "mutants.py" else _harness(r, name)).MUTANTS}
    pick = _audit_pick(r, defs)
    if pick is None:
        return [("audit: the fixture has a claim with an overlapping and a disjoint mutant", False, "none found")]
    c, x, y = pick
    src = core.source_digest(r.root)
    first = c.doc["witnesses"][0]

    def matrix(result=lambda w: "PASS", drop=(), source=src, definition=None, killer=True):
        runs = {}
        for w in c.doc["witnesses"]:
            test, _, case = w.partition(":")
            if test not in drop:
                runs.setdefault(test, {})[case] = result(w)
        rows = {}
        for mid in (x, y):
            row_runs = json.loads(json.dumps(runs))
            row_runs.setdefault("zz_test", {})["ZZ_KILLER"] = "FAIL" if killer else "PASS"
            rows[mid] = {"definition": definition or core.mutant_digest(defs[mid]), "file": defs[mid][1], "what": defs[mid][2],
                         "test": defs[mid][4], "targets": list(defs[mid][5]), "outcome": "KILLED", "runs": row_runs}
        p = work / f"matrix-{len(list(work.glob('matrix-*.json')))}.json"
        p.write_text(json.dumps({"matrix": MATRIX, "harness": "mutants", "tests": "selftest", "source": source, "mutants": rows}))
        return [str(p)]

    def run(**kv):
        rows, probs = load_matrices(r, matrix(**kv))
        return (*audit(r, rows), rows, probs)

    return _synthetic_found(c, x, y, run) + _synthetic_guards(r, c, x, first, run, matrix)


def _synthetic_found(c, x, y, run):
    """A planted blind claim is reported with its counter; a disjoint mutant is not."""
    out = []
    blind, _, _, probs = run()
    hit = _found(blind, c.id, x)
    out.append(("audit: a claim whose witnesses all pass under an overlapping mutant some case kills is reported",
                bool(hit) and not probs and hit[0]["counter"]["passes"] == sorted(c.doc["witnesses"])
                and hit[0]["counter"]["claim"] == c.id and hit[0]["counter"]["against"] == c.tid
                and hit[0]["counter"]["fails"] == ["zz_test:ZZ_KILLER"], (c.id, x, probs, blind[:2])))
    out.append(("audit: a mutant whose scopes are disjoint from the claim's mutants' is not reported against it",
                not _found(blind, c.id, y), _found(blind, c.id, y)))
    return out


def _synthetic_guards(r, c, x, first, run, matrix):
    """Each guard of audit and load_matrices, one planted matrix at a time."""
    def unknown_only(blind, unknown):
        return not _found(blind, c.id, x) and any(u["claim"] == c.id and u["mutant"] == x for u in unknown)

    out = []
    blind, unknown, _, _ = run(result=lambda w: "FAIL" if w == first else "PASS")
    out.append(("audit: a claim one of whose witnesses fails under the mutant is not reported",
                not _found(blind, c.id, x) and not [u for u in unknown if u["claim"] == c.id and u["mutant"] == x],
                _found(blind, c.id, x)))
    blind, unknown, _, _ = run(drop={first.partition(":")[0]})
    out.append(("audit: a witness whose test file did not run under the mutant is unknown, not blind",
                unknown_only(blind, unknown), (_found(blind, c.id, x), unknown[:1])))
    rows, _ = load_matrices(r, matrix())
    for row in rows.values():
        row["runs"][first.partition(":")[0]].pop(first.partition(":")[2])
    blind, unknown = audit(r, rows)
    out.append(("audit: a witness case absent from its file's results under the mutant is unknown, not blind",
                unknown_only(blind, unknown), (_found(blind, c.id, x), unknown[:1])))
    blind, unknown, _, _ = run(killer=False)
    out.append(("audit: a mutant under which no case fails is not reported (its counter would fail nothing)",
                not _found(blind, c.id, x) and not unknown, (_found(blind, c.id, x), unknown[:1])))
    _, _, _, probs = run(source="0" * 64)
    out.append(("audit: a matrix of another source is refused MATRIX_STALE", [p[0] for p in probs] == ["MATRIX_STALE"], probs))
    _, _, rows, probs = run(definition="0" * 64)
    out.append(("audit: a row of a mutant defined otherwise now is refused MATRIX_STALE",
                not rows and {p[0] for p in probs} == {"MATRIX_STALE"}, probs))
    escaped = []
    for arg in ("/etc/hosts", "../hosts", "sub/../../hosts", ".."):
        try:
            escaped.append((arg, str(confined(arg))))
        except Refused:
            pass
    inside = confined(os.path.join(tempfile.gettempdir(), "m.json"))
    out.append(("audit: a --matrix or --counters path outside the temporary directory is refused; one in it is kept",
                not escaped and inside == Path(os.path.realpath(tempfile.gettempdir())) / "m.json", (escaped, inside)))
    return out


def _audit_e2e(fix, work, key):
    """(2) End to end, a real matrix of M278 and M116: the pre-review SPEC-3.3-8 (X1 A6; M05 M06
    M241) is blind to M278, Gemini's counter, which changes the statement M05 changes: reported,
    and its would-be counter replays; citing A7 clears it. The pre-review SPEC-4.1-5 (U1 U4 U5; M09
    M10 M11) is blind to M116 too, but M116 changes another statement than any of its mutants:
    reported, and not confined."""
    s338, s415 = "SPEC-3.3-8", "SPEC-4.1-5"
    r = _clone(fix, work / "audit-e2e")
    m = Model(r.snapshot(), r.trust())
    n, n5 = m.current.get(s338), m.current.get(s415)
    if n is None or n5 is None or not {"M278", "M116"} <= set(r.mutants()):
        return [("audit e2e: SPEC-3.3-8, SPEC-4.1-5, M278 and M116 exist in the fixture", False, "missing")]
    au = Author(r, key, AUTHOR, validate=False)
    au.claim(n.id, n.doc["text"], ["contract_test:X1", "records_test:A6"], ["M05", "M06", "M241"],
             because="selftest: the claim as it stood before the Gemini review", previous=n)
    au.claim(n5.id, n5.doc["text"], ["contract_test:U1", "contract_test:U4", "contract_test:U5"], ["M09", "M10", "M11"],
             because="selftest: the claim as it stood before the Gemini review", previous=n5)
    mx = work / "matrix-e2e.json"
    run = subprocess.run([sys.executable, str(r.tests / "mutants.py"), "--jobs", "2", "--matrix", str(mx),
                          "--matrix-tests", "assessment_test,contract_test,records_test", "M116", "M278"], cwd=r.root,
                         env=dict(os.environ, WARRANT_IMPL=""), capture_output=True, text=True, timeout=900)
    rows, probs = load_matrices(r, [str(mx)])
    blind, _ = audit(r, rows)
    hit, hit5 = _found(blind, s338, "M278"), _found(blind, s415, "M116")
    now = Model(r.snapshot(), r.trust()).current
    why = _replay_counter(r, hit[0]["counter"], now[s338]) if hit else "not reported"
    why5 = _replay_counter(r, hit5[0]["counter"], now[s415]) if hit5 else None
    out = [("audit e2e: the pre-review SPEC-3.3-8 is reported blind to M278, and its would-be counter replays",
            run.returncode == 0 and not probs and bool(hit) and hit[0]["confined"] and why is None
            and "records_test:A7" in hit[0]["fails"], (run.stdout[-300:], probs, why)),
           ("audit e2e: the pre-review SPEC-4.1-5 is blind to M116, not confined, and its counter is refused per statement",
            bool(hit5) and not hit5[0]["confined"] and bool(why5) and STATEMENT_REFUSAL in why5, (hit5[:1], why5))]
    au.claim(n.id, n.doc["text"], ["contract_test:X1", "records_test:A6", "records_test:A7"], ["M05", "M06", "M241"],
             because="selftest: A7 cited, M278 still not", previous=now[s338])
    blind, _ = audit(r, rows)
    out.append(("audit e2e: cited with A7, which M278 fails, SPEC-3.3-8 is not reported", not _found(blind, s338, "M278"),
                _found(blind, s338, "M278")))
    return out


def why_selftest(fix, work, key):
    """[(name, ok, detail)]: `why` burned on a clone of the selftest fixture `fix` (this
    repository's code, mutants, claims and roadmap), then with a real counter (M234's patch,
    replayed) lowering SPEC-3.2-20 to COUNTERED (AMEND 1 of #171)."""
    r = _clone(fix, work / "why")
    w = Why(r)
    paths = [p for p in w.files if p.split("/")[0] in UNCOVERED_ROOTS]
    out = []
    pick = next(((n, mid, path, i, ln) for mid, ns in sorted(w.cited.items(), key=lambda kv: _mid_key(kv[0]))
                 for n in ns if n.doc["duty"] in w.links
                 for (path, i) in sorted(k for k, ms in w.changes.items() if mid in ms)
                 for ln in w.links[n.doc["duty"]] if ln["goal"]), None)
    if pick is None:
        return [("why: the fixture has a claim whose duty an obligation names and whose mutant changes a statement",
                 False, "none found")]
    n, mid, path, i, ln = pick
    d = w.at(path, min(w.units(path)[i][2]))
    out.append(("why: a statement a cited mutant changes maps to its claim, the obligation naming the claim's duty, "
                "and that obligation's goal",
                d["status"] == CLAIMED and i in [s["index"] for s in d["statements"]]
                and n.id in [c["claim"] for c in d["claims"]] and ln["obligation"] in [o["obligation"] for o in d["obligations"]]
                and ln["goal"] in [g["goal"] for g in d["goals"]], (n.id, mid, path, i, d["status"], d["claims"][:2])))
    lost = [(p, i) for p in paths for i, (_, _, own) in enumerate(w.units(p))
            if i not in [s["index"] for s in w.at(p, min(own))["statements"]]]
    out.append(("why: every statement of warrant/ and warrant_agent/ is found again from its first line", not lost, lost[:3]))
    u = w.uncovered(paths)
    listed = {(s["file"], s["index"]) for s in u["uncovered"]}
    wrong = [s for s in u["uncovered"][:200] if w.at(s["file"], s["line"])["status"] != NO_CLAIM]
    out.append(("why: --uncovered lists exactly the statements no cited mutant changes, each answered NO_CLAIM",
                u["statements"] - u["covered"] == len(listed) and (path, i) not in listed and not wrong and u["covered"] > 0,
                (u["statements"], u["covered"], len(listed), wrong[:2])))
    src = w.files["warrant/engine.py"].read_text().splitlines()
    comment = next(k + 1 for k, t in enumerate(src) if t.strip().startswith("#"))
    out.append(("why: a comment line of warrant/engine.py is not a statement",
                w.at("warrant/engine.py", comment)["status"] == NOT_A_STATEMENT, comment))
    codes = []
    for arg in ("SPEC.md", "../warrant/engine.py", "tests/mutants.py"):
        try:
            w.at(arg, 1)
            codes.append(None)
        except Refused as e:
            codes.append(e.code)
    out.append(("why: a file outside warrant/, warrant_agent/ and tools/ is refused WHY_FILE", codes == ["WHY_FILE"] * 3, codes))
    return out + _why_countered(fix, work, key, w, u, paths)


def _why_countered(fix, work, key, w, u, paths):
    """SPEC-3.2-20 lowered by a counter that replays for real: not backing anywhere `why` looks."""
    r = _clone(fix, work / "why-countered")
    r.mutants()
    p = Model(r.snapshot(), r.trust()).current.get("SPEC-3.2-20")
    if p is None or "M234" not in r.mutant_edits:
        return [("why countered: SPEC-3.2-20 and M234 exist in the fixture", False, "missing")]
    store = Store(r.store_dir)
    h = store.put_json({"counter": COUNTER, "claim": p.id, "against": p.tid, "patch": _mutant_patch(r, "M234"),
                        "passes": sorted(p.doc["witnesses"]), "fails": ["records_test:I5"],
                        "why": "selftest: M234 changes the statement M232 changes; the witnesses pass"})
    at = max(x["at"] for x in Model(r.snapshot(), r.trust()).recs.values()) + 1
    ch = store.put_record(R.record("challenge", AUTHOR, at, R.challenge(p.tid, "selftest: replaying counter", [h], 0)), key)
    w2 = Why(r)
    mine = sorted({(path, i) for mid in p.doc["mutants"] for (path, i), ms in w2.changes.items() if mid in ms})
    answers = {k: w2.at(k[0], min(w2.units(k[0])[k[1]][2])) for k in mine}
    named = all(p.id not in [c["claim"] for c in d["claims"]]
                and [(x["challenge"], x["counters"]) for c in d["countered"] if c["claim"] == p.id for x in c["challenges"]]
                == [(ch, [h])] for d in answers.values())
    only = [k for k in mine if {n.id for mid in w.changes.get(k, ()) for n in w.cited.get(mid, [])} == {p.id}]
    u2 = w2.uncovered(paths)
    listed = {(s["file"], s["index"]): s["countered"] for s in u2["uncovered"]}
    return [("why countered: SPEC-3.2-20 lowered by a replaying counter is named with that counter at each of its "
             "statements and is backing at none", bool(mine) and named and p.id in w2.low, (mine, ch[:12])),
            ("why countered: a statement SPEC-3.2-20 alone covered is uncovered now, listed with the COUNTERED claim",
             bool(only) and u2["covered"] == u["covered"] - len(only)
             and all(p.id in listed.get(k, []) for k in only), (only, u["covered"], u2["covered"]))]


def audit_selftest(fix, work, key):
    """[(name, ok, detail)]: `audit` burned on clones of the selftest fixture `fix`."""
    return _audit_synthetic(fix, work) + _audit_e2e(fix, work, key)


def selftest(jobs=1):
    """Burns `check`: on a copy of this repository's claims, each defect must be refused
    with its own code, and the clean copy, a supersession and a retirement must pass."""
    work = Path(tempfile.mkdtemp(prefix="claims-selftest-"))
    try:
        fix = work / "base"
        (fix / "tests").mkdir(parents=True)
        for p in [ROOT / "SPEC.md", ROOT / "SPEC-CLAIMS.md", ROOT / WITNESSES]:
            shutil.copy2(p, fix / p.name)
        for p in sorted((ROOT / "tests").glob("*.py")):
            shutil.copy2(p, fix / "tests" / p.name)
        shutil.copytree(ROOT / ".warrant", fix / ".warrant")
        for pkg in ("warrant", "warrant_agent"):     # a counter blob's patch is replayed against them
            if (ROOT / pkg).is_dir():
                shutil.copytree(ROOT / pkg, fix / pkg, ignore=shutil.ignore_patterns("__pycache__"))
        repo = Repo(fix)
        # An ephemeral second key for the claim author. The first binding of an actor wins, so it
        # cannot be one of the repository's bindings: the selftest binds it as a receiver binds
        # keys for itself (WARRANT_CLAIMS_TRUST), outside the repository, for this process only.
        key = W.Key.generate()
        local = work / "local-trust.json"
        local.write_bytes(C.canon(Trust.document([(AUTHOR, key.public)])))
        os.environ[LOCAL_TRUST] = str(local)
        # No automatic gc or maintenance: a detached repack after the commit would move the
        # fixture's objects while a case is made from it (run 39537906378).
        g_cfg = ["-c", "user.name=claims-selftest", "-c", "user.email=selftest@invalid", "-c", "commit.gpgsign=false",
                 *GIT_NO_GC, "-c", "maintenance.auto=false"]
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
        # AMEND 1 of #169: counters are confined to the statements of one of the claim's mutants.
        # `sc`: SPEC-3.2-20, whose mutant M232 changes the statement of records._item that M234 changes
        # too (another rule on it): M234's patch is a counter that replays. `sw`: SPEC-3.6-7, whose
        # mutants change another statement of _counting_challenges than M29: that counter replayed
        # per function and is refused per statement.
        repo.mutants()
        m29_fails = ["conditions_test:K2"]
        live_ids = {n.id: n for n in live}
        sc, sw = live_ids.get("SPEC-3.2-20"), live_ids.get("SPEC-3.6-7")
        if sc is None or sw is None or not {"M234", "M29"} <= set(repo.mutant_edits) or not any(
                repo.mutant_statements("M234") <= repo.mutant_statements(m) for m in sc.doc["mutants"]):
            print("FAIL  selftest: SPEC-3.2-20 x M234 (one statement) or SPEC-3.6-7 x M29 is not in the fixture")
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
            prior_local_trust = os.environ.get(LOCAL_TRUST)
            d = work / f"case-{i:03d}"
            # A clone through the pack protocol, never a copy of .git's files: copytree, and a
            # local clone (which copies objects/ too), fail with ENOENT if the fixture is
            # repacked meanwhile; --no-local reads objects through git, consistently.
            try:
                subprocess.run(["git", *GIT_NO_GC, "clone", "-q", "--no-local", str(fix), str(d)],
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
                if prior_local_trust is None:
                    os.environ.pop(LOCAL_TRUST, None)
                else:
                    os.environ[LOCAL_TRUST] = prior_local_trust
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
            t = challenge_table(r, m)
            r.projection.write_bytes(render(r, m, t).encode())
            r.witnesses.write_bytes(render_witnesses(r, m, t).encode())

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
                h = Store(r.store_dir).put_json(stmt_counter_doc(r, n, **kv))
                return [au.put("challenge", R.challenge(n.tid, "selftest: the witnesses pass without the rule", [h], 0), au.at())]
            return f

        def stmt_counter_doc(r, n, mid="M234", fails=("records_test:I5",), **kv):
            """A counter against `n` whose patch is mutant `mid`'s edit (default: M234 against SPEC-3.2-20)."""
            r.mutants()
            doc = {"counter": COUNTER, "claim": n.id, "against": n.tid, "patch": _mutant_patch(r, mid),
                   "passes": sorted(n.doc["witnesses"]), "fails": list(fails), "why": f"selftest: {mid}'s edit"}
            doc.update(kv)
            return doc

        def stmt_counter(**kv):
            def f(r, n):
                return [Store(r.store_dir).put_json(stmt_counter_doc(r, n, **kv))]
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

        def retext(cid, text):
            """Supersede claim `cid` with `text` (no validation), then project."""
            def f(r):
                n = Model(r.snapshot(), r.trust()).current[cid]
                author(r).claim(cid, text, n.doc["witnesses"], n.doc["mutants"], n.doc["reason"] if n.kind == "informative" else None,
                                because="selftest", previous=n,
                                unbacked_because=n.doc["reason"] if n.kind == "normative" and not n.backed else None)
                reproject(r)
            return f

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
        case("a counter blob that replays (its patch changes only a statement a cited mutant changes)", None,
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(), claim=sc))
        # AMEND 1 of #169: per function, M29 was a counter against SPEC-3.6-7; per statement it is not
        case("a counter confined to the claim's function but to another statement (SPEC-3.6-7 by M29)", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", claim=sw,
                      counter=stmt_counter(mid="M29", fails=m29_fails)))
        case("the floats counter: an inserted statement in a function a cited mutant changes", "COUNTER_NOT_REPLAYED",
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
             rebacked([], [], unbacked_because="selftest", counter=challenge_carrying(), claim=sc))
        case("a counter blob whose passes omits a cited witness", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(passes=[]), claim=sc))
        case("a counter blob whose fails case passes under the patch", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(fails=["records_test:E3"]), claim=sc))
        case("a counter blob with an empty patch (nothing fails)", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(patch=""), claim=sc))
        case("a counter blob against another claim", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=stmt_counter(against=b.tid), claim=sc))
        case("a counter blob whose patch reaches outside the packages", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=outside_patch))
        case("a challenge carrying a counter blob that does not replay", "COUNTER_NOT_REPLAYED",
             rebacked([], [], unbacked_because="selftest", counter=challenge_carrying(fails=["records_test:E3"]), claim=sc))
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
        # AMEND 2 of #166 (Codex on 64af5aa): a heading part must render as a heading
        case("Codex's probe: the gap before §3.1's heading replaced by a space (the heading renders inline)",
             "DOCUMENT_HEADING", doc_version(lambda ps: [" " if k == head_of(ps, "3.1") - 1 else q for k, q in enumerate(ps)]))
        case("a heading glued to the previous sentence (no gap at all)", "DOCUMENT_HEADING",
             doc_version(lambda ps: [q for k, q in enumerate(ps) if k != head_of(ps, "6") - 1]))
        case("a heading followed by a sentence on the same line", "DOCUMENT_HEADING",
             doc_version(lambda ps: [" " if k == head_of(ps, "5") + 1 else q for k, q in enumerate(ps)]))
        case("a sentence that renders as an ATX heading line", "SPEC_HEADINGS_MISMATCH",
             retext("SPEC-3-4", "## 4.8 Hidden rule: anyone may release"))
        case("a sentence that renders as a setext underline", "SPEC_HEADINGS_MISMATCH", retext("SPEC-3-4", "---"))
        case("a heading changed through its pin, then `heading --section`", None, heading_through_pin,
             also=lambda r: "## 2. Encoding of values\n" in r.spec.read_text())
        case("a document version whose previous is not a document version", "STRUCTURE", document_bad_previous)
        case("a claim text with a control character (U+0000 would vanish from SPEC.md)", "STRUCTURE", control_text)
        case("the document records deleted", "DOCUMENT_MISSING", delete_document)
        case("a claim id with a trailing newline", "STRUCTURE", newline_id)

        # Open circle of witnesses. A: a binding certifies itself; B: acceptance by the named acceptor;
        # C: a counter from anyone lowers backing, never authorship; D: the ledger is a checked view.
        def set_role(r, actor, value):
            doc = json.loads(r.roles_path.read_text())
            doc["actors"][actor] = value
            r.roles_path.write_text(json.dumps(doc, indent=2) + "\n")

        def bind_entry(r, actor, k, proof=None, first=False, pin=False):
            """Append (or put first) `actor`'s binding of key `k`; `pin` also pins its role to `k`."""
            if pin:
                set_role(r, actor, k.public)
            doc = C.loads(r.trust_path.read_bytes())
            e = {"actor": actor, "public": k.public, "proof": binding_proof(k, actor) if proof is None else proof}
            doc["keys"] = [e] + doc["keys"] if first else doc["keys"] + [e]
            r.trust_path.write_bytes(C.canon(doc))

        def binding(actor="stranger", proof=None, first=False, signer=None):
            """A newcomer's binding; `signer` signs the proof instead of the bound key (and is bound itself)."""
            def f(r):
                k = W.Key.generate()
                if signer:
                    s = W.Key.generate()
                    bind_entry(r, signer, s)
                    proof_ = s.sign(binding_message(actor, k.public))
                else:
                    proof_ = proof
                bind_entry(r, actor, k, proof_, first)
                reproject(r)
            return f

        def raw_claim(r, k, actor, n, text, accept_by=None, cid=None):
            """A claim transition filed by `actor` with no tool guard: superseding `n` (or new, as `cid`)."""
            st = Store(r.store_dir)
            at = author(r).at()
            pins = r.pins()
            cid = cid or n.id
            st.put_blob(text.encode())
            duty = st.put_record(R.record("duty", actor, at, R.duty(actor, statement_for(cid, text), pins["owed_to"],
                                                                     {"attest": {}}, accept_by=pins["accept_by"] if accept_by is None
                                                                     else accept_by, subject=sha(text))), k)
            prev = None if n is None else {"transition": n.tid, "duty": n.doc["duty"], "statement_sha256": sha(n.doc["text"])}
            doc = {"schema": CLAIM, "id": cid, "source": "SPEC.md", "section": ID_RE.match(cid).group(1), "text": text,
                   "kind": "normative", "duty": duty, "witnesses": a.doc["witnesses"], "mutants": a.doc["mutants"],
                   "reason": None, "because": None if n is None else "selftest: a stranger rewrites it", "previous": prev}
            h = st.put_json(doc)
            return st.put_record(R.record("transition", actor, at, R.transition(
                "ATTESTED", [h], closes=[R.item(duty, "discharge", [h])], established=[text], residual=[BACKED_RESIDUAL],
                supersedes=[] if n is None else [n.tid])), k)

        def stranger_supersedes(r):
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            n = Model(r.snapshot(), r.trust()).current[a.id]
            raw_claim(r, k, "stranger", n, n.doc["text"] + " (as the stranger has it)")
            reproject(r)

        def stranger_retires(r):
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            n = Model(r.snapshot(), r.trust()).current[b.id]
            st, at = Store(r.store_dir), author(r).at()
            ev = st.put_blob(b"selftest: the stranger wants it gone")
            ch = st.put_record(R.record("challenge", "stranger", at, R.challenge(n.tid, "selftest", [ev], 0)), k)
            doc = {"schema": RETIRE, "id": b.id, "because": "selftest: gone", "counter": ev, "challenge": ch,
                   "previous": {"transition": n.tid, "duty": n.doc["duty"], "statement_sha256": sha(n.doc["text"])}}
            h = st.put_json(doc)
            st.put_record(R.record("transition", "stranger", at, R.transition(
                "ATTESTED", sorted({ev, ch, h}), established=[f"{b.id} is retired"], supersedes=[n.tid])), k)
            reproject(r)

        def stranger_document(r):
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            d = Document(Model(r.snapshot(), r.trust()))
            st = Store(r.store_dir)
            h = st.put_json({"schema": DOCUMENT, "source": "SPEC.md", "parts": d.current["parts"], "because": "selftest",
                             "previous": {"transition": d.tid, "sha256": d.nodes[d.tid][1]}})
            st.put_record(R.record("transition", "stranger", author(r).at(), R.transition(
                "ATTESTED", [h], residual=[DOCUMENT_RESIDUAL], supersedes=[d.tid])), k)
            reproject(r)

        def stranger_claim_without_acceptor(r):
            """The stranger's duty names its own accomplice as acceptor, not the pinned one (records
            refuse an attested duty with no acceptor besides its holder)."""
            k = W.Key.generate()
            bind_entry(r, "stranger", k)
            cid = f"SPEC-{b.doc['section']}-{id_key(b.id)[1] + 2000}"
            raw_claim(r, k, "stranger", None, "A rule only my accomplice has to accept.", accept_by=["accomplice"], cid=cid)
            reproject(r)

        def challenge_by(actor, counter_kv=None, claim=None, pin=False):
            """`actor` binds a fresh key in this change and challenges `claim` (default SPEC-3.2-20),
            carrying a counter (stmt_counter_doc with `counter_kv`) when given."""
            def f(r):
                k = W.Key.generate()
                bind_entry(r, actor, k, pin=pin)
                n = Model(r.snapshot(), r.trust()).current[(claim or sc).id]
                ev = [] if counter_kv is None else [Store(r.store_dir).put_json(stmt_counter_doc(r, n, **counter_kv))]
                Store(r.store_dir).put_record(R.record("challenge", actor, author(r).at(), R.challenge(
                    n.tid, "selftest: the witnesses pass without the rule", ev, 0)), k)
                reproject(r)
            return f

        def lowered_by(actor, cid, kind):
            def f(r):
                m = Model(r.snapshot(), r.trust())
                t = challenge_table(r, m)
                rows = ledger(m, t, r.bindings()[0])
                mine = [x for x in t.values() if x["actor"] == actor and x["claim"] == cid]
                line = next(ln for ln in r.projection.read_text().splitlines() if ln.startswith(f"| {cid} |"))
                status = line.split(" | ")[4]
                if kind == LOWERS:
                    return ([x["kind"] for x in mine] == [LOWERS] and status.startswith("COUNTERED")
                            and len(rows[actor]["now"]) == 1 and len(rows[actor]["counters"]) == 1)
                return [x["kind"] for x in mine] == [kind] and status.startswith("BACKED") and not rows[actor]["now"]
            return f

        def accepted_by_codex(r):
            """Accept with an ephemeral receiver-local key, without rotating an existing codex binding.
            A real codex binding and its signed records may already be in the copied store."""
            k = W.Key.generate()
            local_c = r.root.parent / f"{r.root.name}-codex-trust.json"
            local_c.write_bytes(C.canon(Trust.document(local_bindings() + [("codex", k.public)])))
            os.environ[LOCAL_TRUST] = str(local_c)     # run_case restores it after check and also()
            seed_c = r.root / ".." / f"{r.root.name}-codex.seed"
            seed_c.write_text(k.seed_hex() + "\n")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                rc = main(["--root", str(r.root), "accept", "--key", str(seed_c), "--actor", "codex", "--claim", a.id])
            seed_c.unlink()
            reproject(r)
            assert rc == 0, rc

        def shows_accepted(r):
            line = next(ln for ln in r.projection.read_text().splitlines() if ln.startswith(f"| {a.id} |"))
            rows = ledger(Model(r.snapshot(), r.trust()), {}, r.bindings()[0])
            return "| DISCHARGED (accepted by codex) |" in line and len(rows["codex"]["accepts"]) == 1

        squat = {}

        def squatter_takes_codex(r):
            """The parent's reproduction on fad382f: a fresh key binds `codex` through the CLI and
            accepts a claim. The binding is written by hand here (bind refuses it now)."""
            k = W.Key.generate()
            bind_entry(r, "codex", k)
            seed_s = r.root / ".." / f"{r.root.name}-squatter.seed"
            seed_s.write_text(k.seed_hex() + "\n")
            import contextlib
            import io
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                squat[r.root.name] = (main(["--root", str(r.root), "bind", "--key", str(seed_s), "--actor", "codex"]),
                                      main(["--root", str(r.root), "accept", "--key", str(seed_s), "--actor", "codex",
                                            "--claim", a.id]))
            seed_s.unlink()
            reproject(r)

        def squatter_refused(r):
            m = Model(r.snapshot(), r.trust())
            return squat.get(r.root.name) == (2, 2) and not [x for x in m.recs.values() if x["type"] == "accept"]

        def pin_against_claude(r):
            set_role(r, AUTHOR, W.Key.generate().public)

        def drop_role(r):
            doc = json.loads(r.roles_path.read_text())
            del doc["actors"]["codex"]
            r.roles_path.write_text(json.dumps(doc) + "\n")

        def legacy_trust(r):
            doc = C.loads(r.trust_path.read_bytes())
            r.trust_path.write_bytes(C.canon(Trust.document([(x["actor"], x["public"]) for x in doc["keys"]])))

        def unproven(r):
            doc = C.loads(r.trust_path.read_bytes())
            doc["keys"].append({"actor": "stranger", "public": W.Key.generate().public})
            r.trust_path.write_bytes(C.canon(doc))

        def drop_claude_binding(r):
            doc = C.loads(r.trust_path.read_bytes())
            doc["keys"] = [x for x in doc["keys"] if x["actor"] != AUTHOR]
            r.trust_path.write_bytes(C.canon(doc))
            binding("stranger")(r)

        case("A: a newcomer binds a fresh key with its proof", None, binding("stranger"))
        case("A: a binding whose proof is forged", "BINDING_PROOF_FORGED", binding("stranger", proof="00" * 64))
        case("A: a binding whose proof another key signed", "BINDING_PROOF_OTHER_KEY", binding("victim", signer="mallory"))
        case("A: a newcomer binds the actor id claude to its own key (pinned role)", "BINDING_ROLE_KEY", binding(AUTHOR))
        case("A: two newcomers bind one unpinned name, the second with another key", "BINDING_ACTOR_TAKEN",
             lambda r: (binding("newcomer")(r), binding("newcomer")(r)))
        case("A: an actor id failing SPEC-3-21 (a trailing newline)", "BINDING_ACTOR_SHAPE", binding("stranger\n"))
        case("A: an actor id failing SPEC-3-21 (white space at an end)", "BINDING_ACTOR_SHAPE", binding(" stranger"))
        case("A: a binding with no proof", "BINDING_UNPROVEN", unproven)
        case("A: the trust file as trust/2, without proofs", "BINDINGS_SHAPE", legacy_trust)
        case("A: claude's binding removed (a newcomer's added instead)", "BINDING_REMOVED", drop_claude_binding)
        case("A: a newcomer's claude binding put before the one at the base", "BINDING_ROLE_KEY", binding(AUTHOR, first=True))
        # AMEND 1 of #170 (parent's reproduction on fad382f): a name with a role is pinned, not first-come
        case("A1: a squatter binds codex with its own key and accepts: refused, nothing accepted", "BINDING_ROLE_KEY",
             squatter_takes_codex, also=squatter_refused)
        case("A1: a squatter binds s0fractal (reserved)", "BINDING_ROLE_RESERVED", binding("s0fractal"))
        case("A1: anyone binds readers (a collective role)", "BINDING_ROLE_COLLECTIVE", binding("readers"))
        case("A1: a fresh pinned role binds with the key its pin names", None,
             lambda r: (bind_entry(r, "selftest-pinned-role", W.Key.generate(), pin=True), reproject(r)))
        case("A1: a pin change that contradicts claude's admitted binding", "ROLE_PIN_CONFLICT", pin_against_claude)
        case("A1: a role named in .warrant/claims.json and missing from .warrant/roles.json", "ROLE_UNPINNED", drop_role)
        case("A1: a role pinned to something that is not a key, null or collective", "ROLES_SHAPE",
             lambda r: set_role(r, "codex", "anyone"))
        case("B: codex accepts with a receiver-local fixture key; the view names the acceptor", None, accepted_by_codex, also=shows_accepted)
        case("C: a newcomer binds in this change and files a counter that replays: admitted, backing lowered", None,
             challenge_by("stranger", {}), also=lowered_by("stranger", "SPEC-3.2-20", LOWERS))
        case("C: a newcomer files a counter that does not replay", "COUNTER_NOT_REPLAYED",
             challenge_by("stranger", {"fails": ["records_test:E3"]}))
        case("C: a newcomer's challenge without a counter: admitted, lowers and blocks nothing", None,
             challenge_by("stranger"), also=lowered_by("stranger", "SPEC-3.2-20", THESIS))
        case("C: the acceptor's challenge without a counter stands", "CHALLENGED", challenge_by("codex", pin=True))
        case("C: a newcomer supersedes claude's claim", "LINEAGE_NOT_AUTHOR", stranger_supersedes)
        case("C: a newcomer retires claude's claim", "LINEAGE_NOT_AUTHOR", stranger_retires)
        case("C: a newcomer files the next document version", "LINEAGE_NOT_AUTHOR", stranger_document)
        case("C: a newcomer files a claim whose duty names its own acceptor", "CLAIM_DUTY_TERMS", stranger_claim_without_acceptor)
        case("D: WITNESSES.md edited by hand", "WITNESSES_STALE",
             lambda r: r.witnesses.write_text(r.witnesses.read_text().replace("| claude |", "| claude (trusted) |", 1)))
        case("D: WITNESSES.md with \\r\\n line ends", "WITNESSES_STALE",
             lambda r: r.witnesses.write_bytes(r.witnesses.read_bytes().replace(b"\n", b"\r\n")))
        case("D: WITNESSES.md deleted", "WITNESSES_MISSING", lambda r: r.witnesses.unlink())

        def statement_reasons():
            """Reasons, not only codes: the statement rule (AMEND 1 of #169) is what refuses M29 against
            SPEC-3.6-7 and the floats insertion against SPEC-2-2 (each replays without it), M234 against
            SPEC-3.2-20 replays, and a fails case that passes is refused by the replay, not by locality."""
            why_sw = _replay_counter(repo, stmt_counter_doc(repo, sw, mid="M29", fails=m29_fails), sw)
            why_sw_off = _replay_counter(repo, stmt_counter_doc(repo, sw, mid="M29", fails=m29_fails), sw,
                                         statements=False)
            why_sc = _replay_counter(repo, stmt_counter_doc(repo, sc), sc)
            why_fl = _replay_counter(repo, counter_doc(repo, a), a)
            why_fl_off = _replay_counter(repo, counter_doc(repo, a), a, statements=False)
            why_e3 = _replay_counter(repo, stmt_counter_doc(repo, sc, fails=["records_test:E3"]), sc)
            return [
                ("statement rule: M29 against SPEC-3.6-7 is refused for its statements, and replays per function",
                 bool(why_sw) and STATEMENT_REFUSAL in why_sw and why_sw_off is None, (why_sw, why_sw_off)),
                ("statement rule: the floats insertion against SPEC-2-2 is refused for its statements, and replays per function",
                 bool(why_fl) and STATEMENT_REFUSAL in why_fl and why_fl_off is None, (why_fl, why_fl_off)),
                ("statement rule: M234 against SPEC-3.2-20 (the statement M232 changes) replays", why_sc is None, why_sc),
                ("statement rule: a fails case that passes is refused by the replay, not by locality",
                 bool(why_e3) and "not FAIL" in why_e3, why_e3)]

        # Gemini review, part C: `audit` names a claim whose witnesses all pass under a mutant of its own
        # code that some case kills, and only such a claim (_audit_synthetic, _audit_e2e); `why` maps this
        # repository's statements to claims, obligations and goals (why_selftest). These groups run as
        # more tasks of the pool, beside the registered cases.
        groups = [statement_reasons, lambda: _audit_synthetic(fix, work), lambda: _audit_e2e(fix, work, key),
                  lambda: why_selftest(fix, work, key)]

        def run_any(i):
            return run_case(i) if i < len(cases) else groups[i - len(cases)]()

        # Run the registered cases and the groups: in `jobs` forked processes (each inherits the fixture
        # and the closures above), results reported in registration order.
        global _CASE_RUNNER
        _CASE_RUNNER = run_any           # a forked worker finds it here; a closure does not pickle
        tasks = range(len(cases) + len(groups))
        if jobs > 1 and "fork" in multiprocessing.get_all_start_methods():
            with concurrent.futures.ProcessPoolExecutor(jobs, mp_context=multiprocessing.get_context("fork")) as ex:
                results = list(ex.map(_run_registered_case, reversed(tasks)))[::-1]     # the long groups first
        else:
            results = [run_any(i) for i in tasks]
        results, grouped = results[:len(cases)], [x for group in results[len(cases):] for x in group]
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
        subprocess.run(["git", *GIT_NO_GC, "clone", "-q", "--no-local", str(fix), str(d)], capture_output=True, check=True)
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
        for name, ok, detail in grouped:
            failures += not ok
            ran.append(name)
            print(("ok    " if ok else "FAIL  ") + name + ("" if ok else f" | {detail}"))
        print(f"CLAIMS SELFTEST: {'OK' if not failures else f'{failures} FAIL'} ({len(ran)} cases)")
        return 1 if failures else 0
    finally:
        os.environ.pop(LOCAL_TRUST, None)
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
    p = sub.add_parser("audit", help="report claims whose witnesses miss a mutant of their own code (blind spots)")
    p.add_argument("--matrix", action="append", required=True, metavar="FILE",
                   help="a matrix from tests/mutants.py --matrix or tests/agent_mutants.py --matrix (repeatable)")
    p.add_argument("--counters", metavar="DIR", help="write each candidate's would-be counter blob there")
    p.add_argument("--refuse", action="store_true", help="exit 1 when any candidate is found")
    p = sub.add_parser("why", help="the claims, obligations and goals a source statement serves, or the statements none does")
    p.add_argument("target", nargs="?", metavar="FILE:LINE")
    p.add_argument("--uncovered", nargs="?", const="", metavar="FILE",
                   help="list the statements of warrant/ and warrant_agent/ (or FILE) that no cited mutant changes")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("keygen", help="make a key: seed outside the repository, its binding and proof in the trust")
    p.add_argument("--out", required=True)
    p.add_argument("--actor", default=AUTHOR)
    p.add_argument("--no-bind", action="store_true", help="only write the seed and print the public key (to pin it first)")
    p = sub.add_parser("pin", help="pin a role's key in .warrant/roles.json (a reviewed change of who the role is)")
    p.add_argument("--key", help="seed file whose public key is pinned (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    p = sub.add_parser("bind", help="bind your key to your actor id, with the key's proof of possession")
    p.add_argument("--key", help="seed file of the key to bind (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    sub.add_parser("trust", help="print the trust/2 document of the admitted bindings")
    p = sub.add_parser("accept", help="accept claims' pending closures, signed by an acceptor their duties name")
    p.add_argument("--key", help="seed file of the acceptor's key (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    p.add_argument("--claim", action="append", default=[], help="a claim id (repeatable)")
    p.add_argument("--all", action="store_true", help="every BACKED claim whose closure awaits --actor, none countered")
    p = sub.add_parser("challenge", help="challenge a claim, with a counter blob that must replay (any bound key)")
    p.add_argument("--key", help="seed file of the challenger's key (or WARRANT_CLAIMS_KEY)")
    p.add_argument("--actor", required=True)
    p.add_argument("--claim", required=True)
    p.add_argument("--because", required=True)
    p.add_argument("--counter-file", help="a counter blob (warrant-claims/counter@1 JSON) against the claim")
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
        if a.cmd == "audit":
            return cmd_audit(repo, a)
        if a.cmd == "why":
            return cmd_why(repo, a)
        {"add": cmd_add, "supersede": cmd_supersede, "retire": cmd_retire, "keygen": cmd_keygen,
         "migrate": cmd_migrate, "heading": cmd_heading, "bind": cmd_bind, "trust": cmd_trust,
         "accept": cmd_accept, "challenge": cmd_challenge, "pin": cmd_pin}[a.cmd](repo, a)
        return 0
    except Refused as e:
        print(f"REFUSED {e.code + ' ' if e.code else ''}{e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
