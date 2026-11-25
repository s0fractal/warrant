"""`warrant-agent rely ADDRESS WHAT`: may I rely on it? One command for an agent that has only a repository's address.

    warrant-agent rely github.com/OWNER/NAME "warrant-graph==3.0.0a9"     # a release duty, by the ref it names
    warrant-agent rely github.com/OWNER/NAME 6ea2d499                     # a record, by 8 or more hex digits of its id
    warrant-agent rely github.com/OWNER/NAME G12 --json                   # a goal by its key; the whole answer as JSON

ADDRESS is a GitHub repository (`github.com/OWNER/NAME`, optionally `/tree/BRANCH`) or any HTTPS root that serves
`.warrant/v3.json` and `.warrant/records.jsonl`. Nothing is cloned or written: the store is read over HTTPS with the
sources it declares (warrant_agent/remote.py), assessed in process under the PUBLISHER's own rules (its v3.json: a name
means what that file binds it to), and each matching lineage is answered:

    RELY            its version in force is accepted as its guard requires, and nothing counted stands against it
    RELY ON RECORDS the same, but its acceptances pin file bytes no one compared here (PINS_NOT_CHECKED): clone it and
                    run `warrant status` to compare them
    WAITING         its version waits for the attests its guard names
    NOT DONE        accepted, but in a state its schema does not close (an obligation `open`, a goal `open`): the
                    record stands; what it promises is not yet so
    SUPERSEDED      the version named by id is not the one in force in its lineage (that one is named)
    DO NOT RELY     a counted challenge stands against it, its bytes changed (STALE), or its lineage forks

WHAT is 8 or more hex digits of a record's id, or text: first the records that name it exactly (a ref such as
`warrant-graph==3.0.0a9`, a goal's key, a claim's id), else those whose statement contains it. At most five lineages
are answered, the rest counted. A version named by id is answered as itself; text answers each lineage on its
version in force. Why it exists: an agent with no context, asked whether a release of this repository
was admitted (2026-11-22), answered right in 27 turns by grepping records.jsonl with a script of its own; the store
already held the answer in one record. Exit 0 when every answered lineage reads RELY or RELY ON RECORDS, 1 otherwise,
2 when nothing could be answered."""
import argparse
import json
import re
import sys

from . import api
from . import remote as RM
from .config import DEFAULT_LIMITS
from warrant import shapes as S

from .errors import AgentError

GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?"
                    r"(?:/tree/([A-Za-z0-9_./-]+?))?/?\Z")
MAX = 5


def is_id(text):
    """8 to 64 lowercase hex digits: a record's id or a prefix of one (the agent API's rule, api._resolve)."""
    return 8 <= len(text) <= 64 and S.HEX.match(text) is not None
WORDS = {"ELIGIBLE": "RELY", "PINS_NOT_CHECKED": "RELY ON RECORDS", "PENDING": "WAITING"}
FIELDS = ("refs", "key", "id", "name", "ref", "title")      # where a record names a thing exactly


def address(text):
    """The HTTPS root a store is served at, for a GitHub repository address or an HTTPS root as given."""
    m = GITHUB.match(text.strip())
    if m:
        owner, name, branch = m.group(1), m.group(2), m.group(3) or "HEAD"
        return f"https://raw.githubusercontent.com/{owner}/{name}/{branch}/"
    return text if text.endswith("/") else text + "/"


def _names(body):
    """The strings a body names exactly: a member of FIELDS, or an item of one that is a list."""
    out = set()
    for k in FIELDS:
        v = body.get(k)
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str):
                out.add(x)
    return out


def matches(recs, what):
    """The ids of the records `what` names: by id prefix; else exactly, by a ref, key, id or name; else by statement."""
    w = what.strip()
    if is_id(w.lower()):
        return sorted(i for i in recs if i.startswith(w.lower()))
    body = lambda r: r.get("body") if isinstance(r.get("body"), dict) else {}  # noqa: E731
    exact = sorted(i for i, r in recs.items() if r.get("kind") == "entity" and w in _names(body(r)))
    if exact:
        return exact
    low = w.lower()
    return sorted(i for i, r in recs.items() if r.get("kind") == "entity"
                  and low in str(body(r).get("statement", "")).lower())


def _standing(cap):
    return sorted(c for c, x in (cap.get("challenges") or {}).items() if x.get("counted") and x.get("stands", True))


def _waits(cap):
    return ", ".join(map(str, (cap.get("guard") or {}).get("waiting") or ["attests"]))


def _not_in_force(cap, lin, standing):
    """(word, why) when the version is not its lineage's version in force: a newer one waiting, or superseded."""
    t, eff = cap.get("id"), lin.get("effective")
    if t == lin.get("leaf") and (cap.get("guard") or {}).get("guard") == "PENDING" and not standing:
        return "WAITING", (f"this newest version waits for its guard: {_waits(cap)}"
                           + (f"; the version in force is {eff[:12]}" if eff else ""))
    return "SUPERSEDED", (f"this version is not in force; the version in force is {eff[:12]}"
                          + (f"; challenged: {', '.join(c[:12] for c in standing)}" if standing else ""))


WHY = {"RELY": "accepted as its guard requires; nothing counted stands against it",
       "RELY ON RECORDS": "accepted as its guard requires, but the file bytes its acceptances pin were not compared "
                          "here (PINS_NOT_CHECKED): clone it and run `warrant status`"}


def verdict(cap, closed=()):
    """(word, why) of one version as context describes it; `closed` are the states its schema closes."""
    lin = cap.get("lineage") or {}
    rel, state = lin.get("reliance"), lin.get("state")
    standing = _standing(cap)
    if lin.get("effective") not in (None, cap.get("id")):
        return _not_in_force(cap, lin, standing)
    if rel == "CHALLENGED" or standing:
        return "DO NOT RELY", "challenged: " + ", ".join(c[:12] for c in standing or ["a counted challenge"])
    if rel not in WORDS:
        return "DO NOT RELY", f"its lineage reads {rel}"
    word = WORDS[rel]
    if word != "WAITING" and closed and state not in closed:
        return "NOT DONE", (f"the record stands (accepted as its guard requires), but its state is {state!r}, which "
                            f"its schema does not close ({', '.join(closed)}): what it states is not yet so")
    return word, WHY.get(word) or f"its guard waits for {_waits(cap)}"


def _roots(rep, ids):
    """The lineages the matched ids are versions of, in order (None for a record in no lineage)."""
    roots = []
    for i in ids:
        r = next((L for L, lin in rep["lineages"].items() if i in lin["versions"]), None)
        if r not in roots:
            roots.append(r)
    return roots


def _targets(rep, ids, roots, by_id):
    """One version per lineage: the one asked about by id, else the version in force (or a newer one waiting)."""
    targets = []
    for r in roots[:MAX]:
        if r is None:                              # a record in no lineage (an attest, a challenge)
            targets.extend(i for i in ids if not any(i in lin["versions"] for lin in rep["lineages"].values()))
        elif by_id:                                # the version asked about, as itself
            targets.extend(i for i in ids if i in rep["lineages"][r]["versions"])
        else:                                      # its version in force, or a newer one waiting for its guard
            lin = rep["lineages"][r]
            leaf = lin["leaf"]
            pending = leaf and leaf != lin["effective"] and (rep["versions"].get(leaf) or {}).get("guard") == "PENDING"
            targets.append(leaf if pending else (lin["effective"] or leaf or r))
    return targets


def _row(t, cap, closed):
    lin = cap.get("lineage") or {}
    word, why = (verdict(cap, closed.get(cap.get("schema"), ())) if lin
                 else ("NOT A VERSION", f"a {cap.get('kind', 'record')}, in no lineage"))
    b = (cap.get("record") or {}).get("body") or {}
    return {"verdict": word, "why": why, "version": t, "lineage": lin.get("root"), "schema": cap.get("schema"),
            "state": lin.get("state"), "accepted_by": (cap.get("guard") or {}).get("accepted_by", []),
            "statement": str(b.get("statement") or b.get("text") or b.get("title") or "")[:240],
            "challenges": sorted(cap.get("challenges") or {}), "grounded": (cap.get("grounded") or {}).get("grounded")}


def answer(url, what, limits=None):
    """{address, store, what, matched, answered: [...]}: the verdict on each lineage `what` names in the store at `url`."""
    ws = RM.Remote(url, dict(limits or DEFAULT_LIMITS))
    snap, view, _, _ = api._assess(ws)
    rep = api._report(ws, view)
    ids = matches(view.recs, what)
    # the states each COUNTED schema closes: a schema short of its quorum (a proposal) decides nothing here, as in the
    # engine (Codex fbbca8cc on #595: eve's pending obligation@1 closing `open` made an open duty read RELY)
    closed = {name: (view.recs[sid].get("body") or {}).get("closed") or [] for name, sid in rep["schemas"].items()
              if sid in view.recs}
    roots = _roots(rep, ids)
    targets = _targets(rep, ids, roots, is_id(what.strip().lower()))
    caps = api.context(RM._Cfg(ws), {"workspace": "remote", "targets": sorted(set(targets))[:64]})["targets"] if targets else {}
    return {"address": url, "what": what, "matched": len(ids), "lineages": len(roots),
            "answered": [_row(t, caps.get(t) or {}, closed) for t in targets],
            "store": {"snapshot": rep["snapshot"], "records": len(snap.lines), "repository": ws.doc.get("repository"),
                      "sources": [{"name": s["name"], "commit": s["commit"], "records": s["records"]} for s in ws.sources],
                      "sources_not_read": ws.sources_not_read, "rules": "the publisher's own (.warrant/v3.json)"}}


def _header(a):
    st = a["store"]
    return [f"{a['address']}  {st['repository'] or ''}  snapshot {st['snapshot'][:12]}, {st['records']} records"
            + (f", sources {', '.join(s['name'] for s in st['sources'])}" if st["sources"] else "")
            + (f"; NOT READ: {', '.join(st['sources_not_read'])}" if st["sources_not_read"] else ""),
            "under the publisher's own rules: a name means what its .warrant/v3.json binds it to"]


def _lines(x):
    out = ["", f"{x['verdict']}: {x['statement'] or x['version'][:12]}", f"  {x['why']}"]
    if x["lineage"]:
        out.append(f"  {x['schema']} {x['state']}; version {x['version'][:12]} of lineage {x['lineage'][:12]}"
                   + (f"; accepted by {', '.join(x['accepted_by'])}" if x["accepted_by"] else "")
                   + ("" if x["grounded"] in (None, True) else "; NOT grounded: something it rests on does not stand"))
    if x["challenges"]:
        out.append(f"  challenges on this version: {', '.join(c[:12] for c in x['challenges'])}")
    return out


def text(a):
    out = _header(a)
    if not a["answered"]:
        out.append(f"nothing in this store names {a['what']!r}")
    for x in a["answered"]:
        out.extend(_lines(x))
    if a["lineages"] > len(a["answered"]):
        out.append(f"\n{a['lineages'] - len(a['answered'])} more lineage(s) match: name one by its id")
    if a["answered"]:
        v = a["answered"][0]["version"][:12]
        out.append(f"\ncheck it yourself: git clone, then `python3 -m warrant show {v}` (signatures, guard, challenges)")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="warrant-agent rely", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("address")
    ap.add_argument("what")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        url = RM._checked(address(a.address), set())
        res = answer(url, a.what)
    except AgentError as e:
        sys.stdout.write(json.dumps(e.to_json(), sort_keys=True) + "\n")
        return 2
    sys.stdout.write(json.dumps(res, sort_keys=True, indent=1, ensure_ascii=False) + "\n" if a.json else text(res))
    if not res["answered"]:
        return 2
    return 0 if all(x["verdict"].startswith("RELY") for x in res["answered"]) else 1      # NOT DONE, WAITING, ...: 1


if __name__ == "__main__":
    sys.exit(main())
