"""`check`: the records, SPEC.md, the tests, the pins and the views agree, and against a base
revision nothing was deleted or changed and no claim lost its backing without a proof."""
import json
import subprocess
from pathlib import Path

from warrant import jcs as C
from warrant.store import Snapshot

from . import by_replay
from .base import AUTHOR, git, id_key
from .bindings import admit_bindings, bindings_kept, local_bindings, pin_conflicts, read_roles, trust_of, unpinned
from .repo import witness_problems
from .model import Model
from .counters import BaseTests, challenge_table, COUNTED, lost_backing, new_counters, standing
from .document import Document, render_spec, rendered_headings
from .views import render, render_witnesses


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
    out += why + unpinned(roles, [AUTHOR] + pins_["owed_to"] + pins_["accept_by"] + pins_.get("checkers", []),
                          ".warrant/claims.json")
    model = Model(snap, trust)
    table = challenge_table(repo, model)
    for rid, why in sorted(model.bad.items()):
        code = "NOT_CANONICAL" if why.startswith("not canonical") else \
            "RECORD_MISNAMED" if why.startswith("id does not match") else "UNAUTHENTIC"
        out.append((code, f"records/{rid}.json: {why}"))
    out += model.problems
    out += repo.harness_problems()
    pins = repo.pins()
    out += by_replay.problems(repo, model, pins)
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
    out += by_replay.new_problems(repo, model, set(recs))
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


def duty_terms(model, n, pins):
    """Why claim `n`'s duty is not held by its author, owed to and accepted by whom
    .warrant/claims.json pins, with no release_by; or None. A key anyone may bind must not
    file a claim that only its own accomplice has to accept. The acceptor is the pinned
    `accept_by`, or, for a BACKED claim only, one checker the pins adopt (`checkers`, G4): a
    replay can accept what witnesses and mutants back, never a thesis."""
    if n.retired or n.kind != "normative":
        return None
    b = model.recs[n.doc["duty"]]["body"]
    acceptors = [pins["accept_by"]] + ([[c] for c in pins.get("checkers", [])] if n.backed else [])
    got = (b["holder"], b["owed_to"], b["accept_by"], b["release_by"])
    if got[0] == n.rec["actor"] and got[1] == pins["owed_to"] and got[2] in acceptors and got[3] == []:
        return None
    return (f"its duty has holder {got[0]!r}, owed_to {got[1]}, accept_by {got[2]}, release_by {got[3]}; pinned: "
            f"owed_to {pins['owed_to']}, accept_by one of {acceptors}, no release_by")


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
    status, _ = standing(repo, model)
    print(f"CLAIMS: {len(live)} current ({sum(status[n.id] == 'BACKED' for n in live)} backed, "
          f"{sum(status[n.id] == 'COUNTERED' for n in live)} countered, "
          f"{sum(n.kind == 'normative' and not n.backed for n in live)} unbacked, "
          f"{sum(n.kind == 'informative' for n in live)} informative), "
          f"{sum(n.retired for n in model.current.values())} retired; base {base[:12] if base else 'none'}; "
          f"{'OK' if not problems else f'{len(problems)} refused'}")
    return 1 if problems else 0
