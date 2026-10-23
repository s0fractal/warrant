"""Authoring: the commands that file records (add, supersede, retire, migrate, heading, accept,
challenge), bind or pin keys, and regenerate the views. Each validates before it writes; a
refused command leaves the store byte-identical."""
import copy
import json
import os
import sys
import time
import unicodedata
from pathlib import Path

import warrant as W
from warrant import jcs as C
from warrant import keys as K
from warrant import records as R
from warrant.store import Snapshot, Store, Trust

from .base import (AUTHOR, BACKED_RESIDUAL, CLAIM, COUNTER, id_key, ID_RE, norm, Refused, RETIRE, sha,
                   statement_for, UNBACKED_RESIDUAL)
from .bindings import bound_document, COLLECTIVE, read_roles, ROLES, write_bindings
from .repo import witness_problems
from .model import accept_index, acceptors, Model
from . import by_replay, counters
from . import replay as RP
from .counters import challenge_table, counter_candidates, counter_file_bytes, lowered, standing
from .document import DOCUMENT, Document, DOCUMENT_RESIDUAL, heading_section, parse_spec, render_spec, SECTION_RE
from .check import default_base
from .views import assessment, render, render_witnesses


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
            whys = [why for c in cands for why in [counters.replay_counter(self.repo, model.snap, c, previous)]]
            if not cands or all(whys):
                raise Refused(f"{cid} is BACKED; losing its backing needs a counter blob ({COUNTER}) that replays, "
                              f"via --counter-file or a challenge carrying it: "
                              + ("; ".join(whys) if cands else "none given"))
        bad = witness_problems(self.repo, witnesses, mutants) + [
            (c, w) for c, w in self.repo.harness_problems() if any(w.startswith(f"{x} ") for x in mutants)]
        if bad:
            raise Refused(f"{cid}: " + "; ".join(f"{c} {w}" for c, w in bad))

    def placement(self, cid, after=None, paragraph=False, because=None, item=False):
        """The document version that places a new sentence `cid` after claim `after`, or first
        under the heading of its own section when `after` is that section's number, as
        (parts, because), or None when `cid` is already placed or no document exists yet
        (before the migration). `paragraph` starts a new paragraph, `item` a list item (both:
        a list after a blank line). Raises Refused, writing nothing, when a new sentence names
        no position or a position that is not a placed claim or the heading of its own section."""
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
            raise Refused(f"{cid} is a new sentence: name its position (--after <claim id or its section> "
                          "[--paragraph] [--item])")
        section = ID_RE.match(cid).group(1)
        if SECTION_RE.match(after):
            if after != section:
                raise Refused(f"{cid}: --after {after} is another section")
            i = [k for k, p in enumerate(parts) if isinstance(p, dict) and "heading" in p
                 and heading_section(p["heading"], self.pins.get("headings", {})) == section]
            if len(i) != 1:
                raise Refused(f"{cid}: the document has {len(i)} headings of §{section} (heading --section {section} "
                              "files a pinned section's heading first)")
            sep, where = "\n\n" + ("- " if item else ""), f"first in §{section}"
        else:
            i = [k for k, p in enumerate(parts) if isinstance(p, dict) and p.get("claim") == after]
            if not i:
                raise Refused(f"{cid}: --after {after} is not a claim the document places")
            if ID_RE.match(after) is None or ID_RE.match(after).group(1) != section:
                raise Refused(f"{cid}: --after {after} is in another section")
            sep = ("\n\n" if paragraph else "\n") + "- " if item else "\n\n" if paragraph else " "
            where = f"after {after}" + (" as a new paragraph" if paragraph else "") + (" as a list item" if item else "")
        k = i[0] + 1
        new = parts[:k] + [sep, {"claim": cid, "layout": None}] + parts[k:]
        return new, f"{cid} placed {where}" + (f": {because}" if because else "")

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
              unbacked_because=None, counter=(), after=None, paragraph=False, item=False):
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
        placed = self.placement(cid, after, paragraph, because if previous is None else None, item)
        at = self.at()
        duty = None
        backed = kind == "normative" and witnesses and mutants
        if kind == "normative":
            accept_by = self.acceptors(backed)
            if previous is not None and previous.kind == "normative" and previous.doc["text"] == text \
                    and self.model().recs[previous.doc["duty"]]["body"]["accept_by"] == accept_by:
                duty = previous.doc["duty"]
            else:
                self.store.put_blob(text.encode())
                duty = self.put("duty", R.duty(self.actor, statement_for(cid, text), self.pins["owed_to"], {"attest": {}},
                                               accept_by=accept_by, subject=sha(text)), at)
        prev = None if previous is None else {
            "transition": previous.tid, "duty": previous.doc["duty"], "statement_sha256": sha(previous.doc["text"])}
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

    def acceptors(self, backed):
        """The accept_by of a new claim duty: the last checker .warrant/claims.json adopts for a
        BACKED claim (G4: its closure is accepted by replay), the pinned accept_by otherwise. A
        supersession keeps its claim's duty only when that duty already names this acceptor: a
        duty is never superseded, so a lineage moves to the checker on its next supersession."""
        checkers = self.pins.get("checkers", [])
        return [checkers[-1]] if backed and checkers else list(self.pins["accept_by"])

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
             "after": a.after, "paragraph": a.paragraph, "item": a.item}]


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
                           after=s.get("after"), paragraph=bool(s.get("paragraph")), item=bool(s.get("item")))
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
    if not at and a.section in author.pins["sections"]:
        print(f"document: {author.file_document(new_section(parts, a.section, want, author.pins), a.because, author.at())}")
        return
    if len(at) != 1:
        raise Refused(f"the document has {len(at)} headings of §{a.section}; this command changes one in place, "
                      "or adds the heading of a section .warrant/claims.json pins and the document lacks")
    if parts[at[0]]["heading"] == want:
        raise Refused(f"the heading of §{a.section} is already {want!r}")
    parts[at[0]] = {"heading": want}
    print(f"document: {author.file_document(parts, a.because, author.at())}")


def new_section(parts, section, line, pins):
    """`parts` with the heading `line` of a new pinned `section` on a line of its own: before the
    heading of the first later pinned section the document has, else at its end. Its sentences
    are placed afterwards (add --after SECTION)."""
    pinned, order = pins.get("headings", {}), pins["sections"]
    later = set(order[order.index(section) + 1:])
    j = next((k for k, q in enumerate(parts) if isinstance(q, dict) and "heading" in q
              and heading_section(q["heading"], pinned) in later), None)
    if j is not None:
        return parts[:j] + [{"heading": line}, "\n\n"] + parts[j:]
    if not (isinstance(parts[-1], str) and parts[-1].endswith("\n")):
        raise Refused("the document does not end in a line break; a new section's heading cannot follow it")
    return parts[:-1] + [parts[-1] + "\n", {"heading": line}, "\n"]


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
        why = counters.replay_counter(repo, author.model().snap, h, n) if n.backed else "the claim is not BACKED"
        if why:
            raise Refused(f"{a.claim}: the counter does not replay: {why}", "COUNTER_NOT_REPLAYED")
        author.store.put_blob(data)
        author.pending = {}
        ev = [h]
    item = 0 if n.rec["body"]["closes"] else None
    rid = author.put("challenge", R.challenge(n.tid, a.because, ev, item), author.at())
    print(f"{a.claim}: challenge {rid}")


def cmd_rehome(repo, a):
    """G4's migration, once per adopted checker: every current BACKED claim of --actor whose duty
    does not name the last checker .warrant/claims.json adopts gets a supersession with the same
    sentence, witnesses, mutants and residuals, and a new duty that names the checker. A duty is
    never superseded: the old one stays in the store, OPEN, as history, and the views follow the
    lineage's current duty."""
    author = Author(repo, load_key(repo, a.key, a.actor), a.actor)
    if not author.pins.get("checkers"):
        raise Refused(".warrant/claims.json adopts no checker (`checkers`)", "NO_CHECKER")
    want, model = author.acceptors(True), author.model()
    status, _ = standing(repo, model)
    todo = [n for n in sorted(model.current.values(), key=lambda n: id_key(n.id))
            if status[n.id] == "BACKED" and n.rec["actor"] == a.actor and model.recs[n.doc["duty"]]["body"]["accept_by"] != want]
    for n in todo:
        extra = [x for x in n.rec["body"]["residual"] if x not in (BACKED_RESIDUAL, UNBACKED_RESIDUAL)]
        tid = author.claim(n.id, n.doc["text"], n.doc["witnesses"], n.doc["mutants"], because=a.because, residual=extra,
                           previous=n)
        print(f"{n.id}: {tid}")
    print(f"REHOMED {len(todo)} claims onto duties accepted by {want[0]}")


def cmd_replay(repo, a):
    """The replay checker (replay.py): accept --claim IDs, or every current BACKED claim whose duty
    names this checker and awaits it, by replaying their witnesses and mutants at HEAD; with
    --verify, re-execute instead the acceptances new since --base (by_replay.verify). Exit 1 when
    anything is refused."""
    model = Model(repo.snapshot(), repo.trust())
    if a.verify:
        base = a.base or default_base(repo)
        if base is None:
            raise Refused("no --base given and origin/master is not available", "BASE_UNREADABLE")
        problems = by_replay.verify(repo, model, base, a.rjobs)
        for code, detail in problems:
            print(f"REFUSED {code} {detail}")
        print(f"REPLAY VERIFY: {len(by_replay.accepts(model))} checker acceptances; those new since {base[:12]} "
              f"re-executed; {'OK' if not problems else f'{len(problems)} refused'}")
        return 1 if problems else 0
    me = RP.actor()
    key = load_key(repo, a.key, me)
    status, _ = standing(repo, model)
    if a.claim:
        unknown = [c for c in a.claim if c not in model.current]
        if unknown:
            raise Refused(f"no current claim {', '.join(unknown)}", "NOT_A_CLOSURE")
        nodes = [model.current[c] for c in dict.fromkeys(a.claim)]
    else:
        done = {r["body"]["transition"] for r in model.recs.values() if r["type"] == "accept" and r["actor"] == me}
        nodes = [n for n in sorted(model.current.values(), key=lambda n: id_key(n.id)) if status[n.id] == "BACKED"
                 and me in model.recs[n.doc["duty"]]["body"]["accept_by"] and n.tid not in done]
    try:
        filed, refused = RP.run(repo.root, Store(repo.store_dir), repo.trust(), key, [n.tid for n in nodes], a.rjobs)
    except RP.Refusal as e:
        raise Refused(str(e), e.code) from e
    ids = {n.tid: n.id for n in nodes}
    for tid, rid in filed:
        print(f"{ids[tid]}: accepted by replay {rid[:12]}")
    for tid, e in refused:
        print(f"REFUSED {e.code} {ids[tid]}: {e}")
    print(f"REPLAY: {len(filed)} accepted by {me[:28]}…, {len(refused)} refused")
    return 1 if refused else 0
