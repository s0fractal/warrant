"""warrant serve: the records as pages a person reads, and a reaction he signs (v0).

    python -m warrant_agent.serve [--root DIR ...] [--port 8767] [--actor A --key SEED]

The stores read are the repositories registered in Home (`warrant home`), or each `--root`. Every page is a
projection: a pure function of one store's assessment (under that repository's own trust and profile) and the
query, so the same root and lens give the same page; its footer names both. Three projections: the feed (what
happened, as sentences), a lineage (its versions, who accepted, what is challenged and why its state is what it is,
whether it is grounded), and what waits for an actor. Record text is data: every byte of it is escaped, nothing of a
repository runs.

A reaction is an attest with `verdict: "react"` and integer dimensions (agree -100..100; confidence, importance,
evidence 0..100) and an optional note. No guard's match holds `react`, so it credits nothing; it is the reader's own
signed word on a version. It is filed only with `--actor` and `--key` (a seed outside the repository) in a store whose
trust binds that key to that actor. The server listens on 127.0.0.1 only and refuses a request whose Host is not
its own, and a POST without the token of this run (another page in the browser cannot sign as the reader)."""
import argparse
import hashlib
import html
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from warrant import jcs as C
from warrant import graph as G
from warrant import home as H
from warrant import records as R
from warrant.repo import Failed, Repo, load_key
from warrant_agent import glossary as GL
from warrant_agent import changes as CH
from warrant_agent import contract as CT
from warrant_agent import fragile as FR
from warrant_agent import lens as LZ
from warrant_agent import observe as OB
from warrant_agent import overlay as OVL
from warrant_agent import view as VW
from warrant_agent import voices as VC
from warrant_agent.observe import DIMENSIONS, NOTE_MAX
from warrant_agent import scene as SC

MACHINES = ("claims-checker", "review-replayer")        # actors that sign by program; hidden from the feed by default
# The interpreter's identity: every module of this package, by name and bytes (a page depends on lens.py, view.py,
# scene.py and the rest as much as on this file; Codex's observer pack OBS-P02 found the adapter named this file alone).
ADAPTER_FILES = sorted(Path(__file__).parent.glob("*.py"))
ADAPTER = "warrant-serve/0:" + hashlib.sha256(b"".join(
    p.name.encode() + b"\0" + hashlib.sha256(p.read_bytes()).digest() for p in ADAPTER_FILES)).hexdigest()


def is_machine(actor):
    return actor in MACHINES or actor.startswith("checker ")


# ---------------------------------------------------------------- projections: pure over a report

def _root_of(rep, i):
    """The lineage whose version `i` is, or None; the map is built once per report and kept on it."""
    m = rep.get("_rootmap")
    if m is None:
        m = rep["_rootmap"] = {v: L for L, lin in rep["lineages"].items() for v in lin["versions"]}
    return m.get(i)


def _into(rep):
    """G.index(rep)'s edges into each node, built once per report and kept on it."""
    if "_into" not in rep:
        rep["_into"] = G.index(rep)[2]
    return rep["_into"]


def title(rep, i, n=160):
    """What a record is about, in its own words: an entity's statement, text or title (its lineage root's when the
    version has none), a challenge's statement; else the short id."""
    recs = rep["_recs"]
    r = recs.get(i)
    if r is None:
        return i[:12]
    b = r["body"]
    for k in ("statement", "text", "title", "name"):
        if isinstance(b.get(k), str) and b[k].strip() and (k != "name" or r["kind"] == "entity"):
            t = b[k].strip()
            return t if len(t) <= n else t[:n - 1] + "…"
    if r["kind"] == "entity":
        L = _root_of(rep, i)
        if L and L != i:
            return title(rep, L, n)
        if isinstance(b.get("pr"), int):
            return f"PR #{b['pr']}"
    if r["kind"] == "schema":
        return str(b.get("name", i[:12]))
    return i[:12]


def label(rep, i):
    """A short handle: a claim's id, a goal's key, a pull request's number, else the schema."""
    r = rep["_recs"].get(i)
    if r is None:
        return i[:12]
    L = _root_of(rep, i) or i
    root = rep["_recs"].get(L, r)["body"]
    for k in ("id", "key"):
        if isinstance(r["body"].get(k), str):
            return r["body"][k]
    if isinstance(root.get("pr"), int):
        return f"PR #{root['pr']}"
    return (r.get("schema") or r["kind"]).split("@")[0]


dims = OB.dims


ENTITY_VERBS = {("obligation", "open"): "відкрив обов'язок", ("obligation", "done"): "закрив обов'язок",
                ("obligation", "released"): "звільнив обов'язок", ("goal", "open"): "поставив ціль",
                ("pr-head", "open"): "відкрив", ("pr-head", "head"): "подав нову голову", ("pr-head", "merged"): "злив",
                ("lens", "active"): "подав лінзу", ("lens", "retired"): "відкликав лінзу"}
ATTEST_VERBS = {"accept": "прийняв", "react": "відреагував на", "reproduces": "відтворив заперечення",
                "does_not_reproduce": "не відтворив заперечення", "adopt": "прийняв для себе лінзу", "seen": "переглянув"}


def _about(rep, t):
    return f"{label(rep, t)}: «{title(rep, t)}»" if t else ""


def _entity_sentence(rep, i, r):
    b = r["body"]
    s, state = (r.get("schema") or "").split("@")[0], b.get("state")
    verb = ENTITY_VERBS.get((s, state))
    if verb is None:
        verb = (f"подав {s}" if r.get("lineage") is None else f"нова версія {s}") + (f" → {state}" if state else "")
    rest = ""
    if isinstance(b.get("established"), list) and state != "head":
        rest = f"встановлено {len(b['established'])}, залишків {len(b.get('residual') or [])}"
    return r["actor"], verb, _about(rep, i), rest


_dimensions_text = OB.dimensions_text


def sentence(rep, i):
    """One record as one sentence: (actor, verb, what, rest); the page joins them, escaping each."""
    r = rep["_recs"][i]
    a, b, k = r["actor"], r["body"], r["kind"]
    if k == "entity":
        return _entity_sentence(rep, i, r)
    if k == "attest":
        v = b.get("verdict")
        return (a, ATTEST_VERBS.get(v, f"атестував ({v})"), _about(rep, b.get("target")),
                _dimensions_text(b) if v == "react" else "")
    if k == "challenge":
        return a, "заперечив", _about(rep, b.get("target")), title(rep, i)
    if k == "schema":
        return a, "подав схему", title(rep, i), ""
    return a, f"подав {k}", title(rep, i), ""


def _left_out(r, machines):
    """Why the feed leaves a record out: a migration record never drawn, an automatic actor's unless asked; else ""."""
    if r.get("schema") == "v2-transition@1":
        return "transition"
    return "machines" if not machines and is_machine(r["actor"]) else ""


def feed(rep, limit=200, actor=None, machines=False, omitted=None):
    """The newest records first (by `at`, then id): a list of {id, at, kind, actor, sentence, lineage}; `limit=None`
    keeps them all. `omitted` (a dict) counts what it left out of the actor's records and why: migration records
    (`transition`, never drawn) and, unless `machines`, those of automatic actors (`machines`)."""
    out, omitted = [], {} if omitted is None else omitted
    for i, r in rep["_recs"].items():
        if actor and r["actor"] != actor:
            continue
        why = _left_out(r, machines)
        if why:
            omitted[why] = omitted.get(why, 0) + 1
            continue
        t = r["body"].get("target") if r["kind"] in ("attest", "challenge") else i
        out.append({"id": i, "at": r["at"], "kind": r["kind"], "actor": r["actor"], "sentence": sentence(rep, i),
                    "lineage": _root_of(rep, t) if t else None, "target": t})
    out.sort(key=lambda x: (-x["at"], x["id"]))
    return out if limit is None else out[:limit]


reactions_elsewhere = OB.elsewhere          # every observation filed in other stores (observe.py)


def lineage(rep, i):
    """The lineage of record `i` (an entity version, or the target of an attest or a challenge): its state and
    reliance, each version newest first with its guard and the attests and challenges on it, and whether its
    effective (else latest) version is grounded."""
    r = rep["_recs"].get(i)
    if r is not None and r["kind"] in ("attest", "challenge"):
        i = r["body"].get("target", i)
    L = _root_of(rep, i)
    if L is None:
        return None
    lin = rep["lineages"][L]
    into = _into(rep)
    versions = []
    for v in reversed(lin["versions"]):
        on = sorted((x for rel, x in into.get(v, []) if rel in ("attest", "challenge") and x in rep["_recs"]),
                    key=lambda x: (rep["_recs"][x]["at"], x))
        versions.append({"id": v, "record": rep["_recs"][v], "guard": rep["versions"].get(v, {}),
                         "on": [{"id": x, "sentence": sentence(rep, x)[:3] + ((title(rep, x, NOTE_MAX),) if rep["_recs"][x]["kind"] == "challenge"
                                                                               else sentence(rep, x)[3:]), "at": rep["_recs"][x]["at"],
                                 "challenge": rep["challenges"].get(x)} for x in on]})
    focus = lin.get("effective") or lin["leaf"]
    return {"lineage": L, "schema": lin["schema"], "state": lin["state"], "reliance": lin["reliance"],
            "effective": lin.get("effective"), "leaf": lin["leaf"], "title": title(rep, L, 400), "label": label(rep, L),
            "versions": versions, "grounded": G.grounded(rep, focus) if focus else None}


def waiting(rep, actor):
    f = G.frontier(rep, rep["_profile"], actor)
    return {"actor": actor, "roles": f["roles"],
            "attest": [dict(x, title=title(rep, x["version"]), label=label(rep, x["version"])) for x in f["attest"]],
            "pending": [{"version": v, "lineage": _root_of(rep, v), "title": title(rep, v), "label": label(rep, v),
                         "waiting": rep["versions"][v]["waiting"]} for v in f["pending"]],
            "challenged": [{"lineage": L, "title": title(rep, L), "label": label(rep, L)} for L in f["challenged"]]}


def reaction_body(target, form):
    """The body of a reaction from a submitted form, or a reason it is none (observe.py's `react`)."""
    return OB.body("react", None, target, form)


def lens(rep, query):
    return G.answer(rep, query, None, ADAPTER)


# ---------------------------------------------------------------- stores

class Space:
    """The stores read, by name: each a repository root; its report is kept while its store files are unchanged."""

    def __init__(self, roots):
        self.roots = dict(roots)
        self.cache = {}

    @classmethod
    def from_home(cls):
        doc = H.load()
        return cls({n: os.path.expanduser(r["path"]) for n, r in sorted(doc["repositories"].items())})

    def _stamp(self, root):
        dot = Path(root) / ".warrant"
        return tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(dot.glob("*"))
                     if p.is_file() and p.suffix in (".jsonl", ".json"))

    def report(self, name):
        root = self.roots[name]
        stamp = self._stamp(root)
        hit = self.cache.get(name)
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            repo = Repo(root)
            rep = repo.report()
            rep["_trust"], rep["_profile"] = repo.config()[:2]   # named by digest in the report; the frontier and voices read them
        except (Failed, OSError, ValueError) as e:
            rep = {"_error": f"{type(e).__name__}: {e}"}
        self.cache[name] = (stamp, rep)
        return rep


# ---------------------------------------------------------------- pages

E = html.escape
TEXT = "text/plain; charset=utf-8"
END = "</div>"
MISSING = "Немає"
WHATIF = "Що було б"
CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mute:#6b6a65;--line:#e4e1d8;--card:#fff;--ok:#2f7a4b;--warn:#a26a00;--bad:#b3261e;--acc:#3b5bdb}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--mute:#9a988f;--line:#2e2d29;--card:#1e1e1b;--ok:#6cc58f;--warn:#e0a83a;--bad:#f2867d;--acc:#8fa6ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,sans-serif}
header{padding:12px 16px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:center;flex-wrap:wrap}
header a{color:var(--fg);text-decoration:none;font-weight:600}nav a{margin-right:12px;color:var(--acc)}
main{max-width:960px;margin:0 auto;padding:16px}a{color:var(--acc)}
.item{padding:8px 0;border-bottom:1px solid var(--line)}.when{color:var(--mute);font-size:12px;font-variant-numeric:tabular-nums}
.actor{font-weight:600}.store{color:var(--mute);font-size:12px;border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-right:6px}
.rest{color:var(--mute)}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:12px 0}
.tag{display:inline-block;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600;border:1px solid currentColor}
.ELIGIBLE,.MET,.yes{color:var(--ok)}.PENDING,.STALE,.FORK{color:var(--warn)}.CHALLENGED,.no,.INVALID{color:var(--bad)}.NONE{color:var(--mute)}
ul{margin:4px 0 4px 18px;padding:0}.scenes{display:flex;gap:16px;overflow-x:auto}.scene{max-width:none;background:var(--card);border:1px solid var(--line);border-radius:8px}footer{color:var(--mute);font-size:12px;padding:16px;text-align:center;word-break:break-all}
form.react{display:grid;grid-template-columns:120px 1fr 48px;gap:6px 10px;align-items:center}form.react textarea{grid-column:1/4;min-height:60px}
form.react button{grid-column:1/4;justify-self:start}.bar{display:inline-block;height:8px;background:var(--acc);border-radius:4px;vertical-align:middle}
.filters{font-size:13px;color:var(--mute);margin-bottom:8px}code{font-size:12px}
"""


def when(at):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at))


def tag(word):
    tip = GL.TERMS.get(word)
    return f'<span class="tag {E(word)}" title="{E(tip[0]) if tip else ""}">{E(word)}</span>'


def link_l(store, i, text):
    return f'<a href="/l/{quote(store)}/{E(i)}">{text}</a>'


def item(store, x, show_store=True):
    a, verb, what, rest = x["sentence"]
    target = link_l(store, x["lineage"], E(what)) if x["lineage"] and what else E(what)
    return (f'<div class="item" data-r="{E(x["id"])} {E(store)}"><span class="when">{when(x["at"])}</span> '
            + (f'<span class="store">{E(store)}</span>' if show_store else "")
            + f'<span class="actor">{E(a)}</span> {E(verb)} {target}'
            + (f' <span class="rest">— {E(rest)}</span>' if rest else "") + END)


def page(title_, body, footer=""):
    return (f'<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>{E(title_)}</title><style>{CSS}</style></head><body><header><a href="/">warrant</a>'
            f'<nav><a href="/">Стрічка</a><a href="/changes">Що змінилось</a><a href="/whatif">Що було б</a><a href="/fragile">Крихке</a>'
            f'<a href="/overlay">Для мене</a><a href="/wait">Чекає на мене</a>'
            f'<a href="/stores">Сховища</a></nav></header>'
            f'<main>{body}</main><footer>{footer}</footer></body></html>')


def foot(name, rep, query):
    x = lens(rep, query)
    others = query.get("with") or {}
    also = "" if not others else (f' · і ще {len(others)} сховищ <code title="{E(", ".join(f"{n} {r}" for n, r in others.items()))}">'
                                  f'{E(C.doc_id(others)[:12])}</code>')
    return (f'{E(name)} · root <code title="{E(x["root"])}">{E(x["root"][:12])}</code>{also} · '
            f'lens <code title="{E(x["lens"])}">{E(x["lens"][:12])}</code>')


def grounded_html(rep, store, g):
    if g is None:
        return ""
    cls, word = ("yes", "так") if g["grounded"] else ("no", "ні")
    failing = "".join(f"<br>· {link_l(store, v, E(label(rep, v) + ': ' + title(rep, v, 90)))} — {E(why)}"
                      for v, why in g["failing"][:12])
    outside = g.get("outside") or []
    held = (f'<br><span class="rest">тримається й на {len(outside)} записах поза цим сховищем, яких сторінка не перевіряла: '
            + ", ".join(E(x[:12]) for x in outside[:8]) + "</span>") if outside else ""
    return (f'<p>Обґрунтоване: <b class="{cls}">{word}</b> (усе, на чому воно тримається, транзитивно: '
            f'{g["closure"]} версій){failing}{held}</p>')


def challenge_state(c):
    if c is None:
        return ""
    if c.get("outside"):
        return " · голос ззовні: правила цього сховища його не рахують"
    out = " · " + ("зараховане" if c.get("counted") else "не зараховане")
    if c.get("stands"):
        out += ", стоїть"
    if c.get("replays"):
        out += f', відтворень {len(c["replays"])}'
    return out


def who(actor):
    """An actor as a page shows it: a key that names itself (`key:<hex>`) by its first and last characters."""
    return f"{actor[:12]}…{actor[-4:]}" if actor.startswith("key:") and len(actor) > 24 else actor


def on_html(rep, x):
    a, verb, _, rest = x["sentence"]
    a = who(a)
    note = x["note"] if "note" in x else rep["_recs"][x["id"]]["body"].get("note")
    return (f'<div class="item" data-a="{E(x["id"])}"><span class="when">{when(x["at"])}</span> <span class="actor">{E(a)}</span> '
            f'{E(verb)}{E(challenge_state(x["challenge"]))}' + (f' <span class="rest">— {E(rest)}</span>' if rest else "")
            + (f'<div class="rest">{E(note)}</div>' if isinstance(note, str) else "") + END)


def _ul(items):
    return "<ul>" + "".join(f"<li>{E(x)}</li>" for x in items) + "</ul>"


def _drawn(head, v, form):
    """A member's value drawn: as a count when the card says so, else in the form the value has (None: an empty list)."""
    if form == "count":
        return f"<p>{head} {len(v) if isinstance(v, (list, dict)) else 1}</p>"
    if isinstance(v, list):
        return head + _ul(x if isinstance(x, str) else json.dumps(x, ensure_ascii=False) for x in v) if v else None
    if isinstance(v, dict):
        return f"{head}<p><code>{E(json.dumps(v, ensure_ascii=False, sort_keys=True))}</code></p>"
    return f"{head}<p>{E(str(v))}</p>"


def fields_html(body, card, skip_statement=False, rid=""):
    """The members the card draws, each marked `data-f="RID PATH"` (contract.py reads the marks back). A value whose
    form is not the field's `as` is drawn in the form it has: a lens promises the member, not the form it guessed."""
    parts = []
    for f in card["fields"]:
        k, v = f["path"], body.get(f["path"])
        if v is None or (skip_statement and k == "statement"):
            continue
        drawn = _drawn(f"<b>{E(f['label'])}</b>" if f["label"] else "", v, f["as"])
        if drawn is not None:
            parts.append(f'<div data-f="{E(rid)} {E(k)}">{drawn}</div>')
    return "".join(parts)


def heads_statement(rep, d):
    """Whether the page's heading is the lineage root's whole statement (its title, not cut): then the root's card
    need not draw it again, and the heading carries its mark."""
    t = rep["_recs"].get(d["lineage"], {}).get("body", {}).get("statement")
    return isinstance(t, str) and t.strip() != "" and title(rep, d["lineage"], 400) == t.strip()


def version_head(d, v):
    rec, gd = v["record"], v["guard"]
    mark = " (дієва)" if v["id"] == d["effective"] else ""
    accepted = f' · прийняли: {E(", ".join(gd["accepted_by"]))}' if gd.get("accepted_by") else ""
    return (f'<span class="when">{when(rec["at"])}</span> <span class="actor">{E(rec["actor"])}</span> '
            f'версія{E(mark)} · стан <b>{E(str(rec["body"].get("state")))}</b> · охоронець {tag(gd.get("guard", "NONE"))}'
            f'{accepted} · <code>{E(v["id"][:12])}</code>')


def version_html(rep, d, v, card=LZ.card_of(LZ.BUILTIN)):
    gd = v["guard"]
    repeated = v["id"] == d["lineage"] and len(d["versions"]) > 1 and heads_statement(rep, d)
    parts = [f'<div class="card"><div>{version_head(d, v)}{END}', fields_html(v["record"]["body"], card, repeated, v["id"])]
    if gd.get("waiting"):
        parts.append("<p class='rest'>Чекає: " + E("; ".join(gd["waiting"])) + "</p>")
    if card["activity"] == "shown":
        parts += [on_html(rep, x) for x in v["on"]]
    parts.append(END)
    return "".join(parts)


def versions_html(rep, d, card):
    """The versions as the card lays them out: nested (each a card holding its activity) or flat (one stream)."""
    vs = d["versions"] if card["order"] == "newest" else list(reversed(d["versions"]))
    if card["layout"] == "nested":
        return "".join(version_html(rep, d, v, card) for v in vs)
    events = []
    for v in vs:
        events.append((v["record"]["at"], 0, v["id"], f'<div class="item"><div>{version_head(d, v)}{END}'
                       f'{fields_html(v["record"]["body"], card, rid=v["id"])}{END}'))
        if card["activity"] == "shown":
            events += [(x["at"], 1, x["id"], on_html(rep, x)) for x in v["on"]]
    events.sort(key=lambda e: e[:3], reverse=card["order"] == "newest")
    return "".join(e[3] for e in events)


def standing(rep, d):
    """The counted challenges that stand against a version of the lineage: [(challenge id, version)]."""
    vs = {v["id"] for v in d["versions"]}
    return sorted((c, x["target"]) for c, x in rep["challenges"].items()
                  if x["target"] in vs and x.get("counted") and x.get("stands"))


def lens_objections(reports, lens_store, lens_id):
    """[statement] of every challenge filed against the lens version that draws a page, counted or not: a lens has
    no guard, so no challenge against it is counted, and each is shown wherever the lens draws."""
    r = reports.get(lens_store) if lens_store else None
    if not r or "_error" in r:
        return []
    return [title(r, c, LZ.MAX_NAME * 8) for c, x in sorted(r["challenges"].items()) if x["target"] == lens_id]


def _is_view(rep, x):
    return OB.verdict_of(rep, x) == "seen"


def sources(rep, store, d):
    """Who stands behind a lineage: its authors (who filed its versions); the other actors who spoke on one of them
    (an attest or a challenge, here or in another store read); those who only signed that they saw it (`seen`); and the
    stores those records are in. It is the general comparison of two views (view.py) with the sources varied: the page
    holding only its authors' own records, and the page as it is; what appears between them is everyone else. It
    counts voices, never completeness: a source that kept silent leaves nothing to count, a reader who saw does."""
    from warrant_agent import view as VW
    authors = sorted({v["record"]["actor"] for v in d["versions"]})
    items = {x["id"]: x for v in d["versions"] for x in v["on"]}
    full = dict(LZ.card_of(LZ.BUILTIN), activity="shown")
    alone = VW.observe(sys.modules[__name__], rep, d, full, keep=lambda x: x["sentence"][0] in authors)
    others = [items[i] for i, member in VW.difference(alone, VW.observe(sys.modules[__name__], rep, d, full))["appeared"]
              if not member and i in items]
    spoke = sorted({x["sentence"][0] for x in others if not _is_view(rep, x)})
    saw = sorted({x["sentence"][0] for x in others if _is_view(rep, x)})
    stores = sorted({store} | {x["store"] for x in items.values() if x.get("store")})
    return authors, spoke, saw, stores


def voices(rep, store, d, spoke):
    """(groups, notes, independent): the voices behind the lineage joined by key (voices.py), the sentences where names
    mislead, and those of `spoke` who signed and share no key with an author: the voices independent of it. A record
    its store admitted UNSIGNED is a name anyone could write: it is no one's key, and never independent."""
    trust, basis = rep.get("_trust"), rep.get("_basis", {})
    def keys(i, actor):
        return VC.keys_of(trust, actor) if basis.get(i) == "SIGNED" else set()
    vs = [(v["record"]["actor"], store, keys(v["id"], v["record"]["actor"])) for v in d["versions"]]
    authored = len(vs)
    for v in d["versions"]:
        for x in v["on"]:
            a = x["sentence"][0]
            vs.append((a, x.get("store") or store, set(x["keys"]) if "keys" in x else keys(x["id"], a)))
    gs = VC.groups(vs)
    independent = sorted({n for g in gs if min(g["members"]) >= authored and g["keys"] for n in g["names"] if n in spoke})
    return gs, VC.notes(gs), independent


def last_seen(rep, d, reader):
    """(index of the version the reader last signed that they saw, counted from the oldest; how many versions there
    are), or None when the reader signed no view of this lineage."""
    order = sorted(d["versions"], key=lambda v: (v["record"]["at"], v["id"]))
    seen = [i for i, v in enumerate(order) for x in v["on"] if _is_view(rep, x) and x["sentence"][0] == reader]
    return (max(seen), len(order)) if seen else None


def last_view(rep, d, reader):
    """The id of the reader's latest signed view of this lineage, or None."""
    views = [x for v in d["versions"] for x in v["on"] if _is_view(rep, x) and x["sentence"][0] == reader]
    return max(views, key=lambda x: (x["at"], x["id"]))["id"] if views else None


def sources_html(rep, store, d, reader=None):
    authors, spoke, saw, stores = sources(rep, store, d)
    _, notes, independent = voices(rep, store, d, spoke)
    if spoke and not independent:
        spoke_note = ' · <b class="PENDING">усі, хто висловився, підписують ключем автора</b>'
    elif len(independent) < len(spoke):
        spoke_note = f' · незалежних від автора: {len(independent)}'
    else:
        spoke_note = ""
    challenged = sum(1 for v in d["versions"] for x in v["on"] if x["challenge"] is not None)
    if spoke:
        who = f'висловились: {E(", ".join(spoke))}'
    elif saw:
        who = f'<b class="PENDING">лише автор висловився; бачили {len(saw)}, і ніхто не прийняв і не заперечив</b>'
    else:
        who = '<b class="PENDING">лише автор: ніхто інший не прийняв, не заперечив, не відреагував і не підписав, що бачив</b>'
    mine = ""
    ls = last_seen(rep, d, reader) if reader else None
    if reader and ls is None:
        mine = " · ти не підписував, що бачив"
    elif reader and ls[0] == ls[1] - 1:
        mine = " · ти бачив останню версію"
    elif reader:
        mine = f" · <b>ти бачив версію {ls[0] + 1} з {ls[1]}</b>"
    if reader and ls is not None:
        mine += f' (<a href="/l/{quote(store)}/{E(d["lineage"])}?asof={E(last_view(rep, d, reader))}">як бачив тоді</a>)'
    return (f'<p class="rest">джерела: автор {E(", ".join(authors))} · {who} · бачили: {len(saw)} · заперечень: {challenged}'
            f' · сховищ: {len(stores)}{mine}{spoke_note}'
            + (f' · <b class="PENDING">імена вводять в оману</b>: {E("; ".join(notes))}' if notes else "") + '</p>')


def floor_html(rep, store, d, used, note="", objections=(), reader=None, hidden=0, unavailable=()):
    """What no lens decides: state and reliance, every counted challenge that stands with its statement, that
    completeness is UNATTESTED, which lens drew the page (a portal: the same root and lens give this page), and
    every challenge against that lens, and who stands behind the lineage (`sources`)."""
    held = standing(rep, d)
    rows = "".join(f"<li data-c=\"{E(c)}\">{E(title(rep, c, LZ.MAX_NAME * 8))} <span class='rest'>(на {E(v[:12])})</span></li>" for c, v in held)
    lens_id, lens_name = used
    portal = f'/l/{quote(store)}/{E(d["lineage"])}?lens={E(lens_id)}'
    head = f' data-f="{E(d["lineage"])} statement"' if heads_statement(rep, d) else ""
    return (f'<h2{head}>{E(d["label"])}: {E(d["title"])}</h2><p>{E(d["schema"])} · стан <b data-floor="state">{E(str(d["state"]))}</b> · '
            f'опора <span data-floor="reliance">{tag(d["reliance"])}</span> · заперечень, що стоять: <b data-floor="standing">{len(held)}</b> · '
            f'повнота <span data-floor="unattested">{tag("UNATTESTED")}</span></p>'
            + (f'<ul class="standing">{rows}</ul>' if held else "") + sources_html(rep, store, d, reader)
            + f'<p class="rest">вигляд: <span data-floor="lens">лінза «{E(lens_name)}»</span> · <a href="{portal}">відтворити цей вигляд</a> · '
            f'<a href="/s/{quote(store)}/{E(d["lineage"])}?lens={E(lens_id)}">карта</a>{note}'
            + (f' · <b class="CHALLENGED">заперечень на цю лінзу: {len(objections)}</b>' if objections else "")
            + (f' · <b class="PENDING">лінза не показує тут {hidden}</b> з того, що показала б вбудована' if hidden else "")
            + "</p>"
            + (f'<p class="rest"><b class="PENDING">не прочитано сховищ: {len(unavailable)}</b> ('
               + E("; ".join(f"{n}: {why[:80]}" for n, why in unavailable)) + '): чого в них є, сторінка не знає</p>' if unavailable else "")
            + (_ul(objections).replace("<ul>", "<ul class='standing'>", 1) if objections else ""))


CONTRACT = "<!--contract-->"


def contract_html(broken, headline="сторінка не тримає контракт лінзи"):
    """The promises of the lens and the floor this page does not keep (contract.py): a replayable fact, shown on it."""
    if not broken:
        return ""
    names = {"visible": "не показано", "floor": "немає в підлозі", "standing": "не показано заперечення",
             "node": "немає на карті й не згорнуто", "folded": "згорнуто не стільки, скільки сказано",
             "record": "не показано запис", "extra": "показано запис поза запитом", "omit": "не сказано, що пропущено",
             "unread": "не названо непрочитане сховище"}
    rows = "".join(f"<li>{E(names[p])}: {E(x if isinstance(x, str) else (x[0][:12] + (' «' + x[1] + '»' if x[1] else '')))}</li>"
                   for p, x in broken[:30])
    return (f'<div class="card"><b class="CHALLENGED">{E(headline)}: {len(broken)}</b> '
            f'<span class="rest">(python -m warrant_agent.contract відтворює)</span><ul>{rows}</ul>{END}')


OMITTED = {"machines": "автоматичних учасників", "transition": "записів міграції", "limit": "старіших за межу"}


def feed_scope_html(store, actor, omitted, unread):
    """What the feed was asked for and what it leaves out, each with how many: a feed is never silently partial."""
    scope = ([f"сховище <b>{E(store)}</b>"] if store else []) + ([f"лише <b>{E(actor)}</b>"] if actor else [])
    left = [f'<span data-omit="{k} {omitted[k]}">{omitted[k]} {E(OMITTED[k])}</span>' for k in OMITTED if omitted.get(k)]
    return ((f'<p class="rest">запит: {" · ".join(scope)}</p>' if scope else "")
            + (f'<p class="rest">не показано: {" · ".join(left)}</p>' if left else "")
            + (f'<p class="rest"><b class="PENDING">не прочитано сховищ: {len(unread)}</b> ('
               + "; ".join(f'<span data-unread="{E(n)}">{E(n)}</span>: {E(why[:80])}' for n, why in unread)
               + '): чого в них є, стрічка не знає</p>' if unread else ""))


def diff_html(rep, d, names, only_a, only_b, drawn=()):
    """What one lens shows of the page that the other does not; the comparison sees only this store's records."""
    def row(x):
        i, member = x
        r = rep["_recs"].get(i, {})
        what = f"«{E(member)}» версії {E(i[:12])}" if member else f"{E(r.get('actor', '?'))}: {E(' '.join(sentence(rep, i)[1:3]))}"
        return f"<li>{what}</li>"
    a, b = names
    return (f'<div class="card"><b>Порівняння лінз</b> <span class="rest">(лише записи цього сховища)</span>'
            f'<p>Показує лише «{E(a)}»: {len(only_a)}</p><ul>{"".join(row(x) for x in only_a[:50])}</ul>'
            f'<p>Показує лише «{E(b)}»: {len(only_b)}</p><ul>{"".join(row(x) for x in only_b[:50])}</ul>'
            f'<p>Показано інакше: {len(drawn)}</p><ul>'
            + "".join(f"<li>{E(str(w))}: «{E(str(x))}» → «{E(str(y))}»</li>" for w, x, y in drawn) + f"</ul>{END}")


def _floor_moves(f0, f1):
    if f0 is None:
        return ["нова лінія"]
    out = [f"{name}: {E(str(f0[k]))} → {E(str(f1[k]))}" for k, name in
           (("state", "стан"), ("reliance", "опора"), ("grounded", "обґрунтоване")) if f0[k] != f1[k]]
    if f0["standing"] != f1["standing"]:
        out.append(f"заперечень, що стоять: {len(f0['standing'])} → {len(f1['standing'])}")
    return out


def change_html(rep, store, x, reports=None):
    def item(t):
        i, member = t
        if member:
            return f"<li>«{E(member)}» версії {E(i[:12])}</li>"
        where = rep if i in rep["_recs"] else next((r for _, r in sorted((reports or {}).items()) if i in r["_recs"]), None)
        if where is None:
            return f"<li><code>{E(i[:12])}</code></li>"
        a, verb, what, rest = sentence(where, i)
        if where is not rep:
            verb += f" (у {next(n for n, r in sorted(reports.items()) if r is where)})"
            rest = rest + (" — " if rest else "") + str(where["_recs"][i]["body"].get("note") or "")
        return f"<li><span class='actor'>{E(a)}</span> {E(verb)}" + (f" <span class='rest'>— {E(rest)}</span>" if rest else "") + "</li>"
    moves = _floor_moves(x["floor_before"], x["floor_after"])
    return (f'<div class="item">{link_l(store, x["lineage"], E(x["label"] + ": " + x["title"]))}'
            + (f' <span class="rest">· {"; ".join(moves)}</span>' if moves else "")
            + (f'<ul>{"".join(item(t) for t in x["appeared"][:30])}</ul>' if x["appeared"] else "")
            + (f'<p class="rest">зникло: {len(x["vanished"])}</p>' if x["vanished"] else "") + END)


class App:
    def __init__(self, space, actor=None, key=None, reader=None, marks=None, mine=None):
        self.space, self.actor, self.key, self.token = space, actor, key, secrets.token_hex(16)
        self.mine = mine          # the reader's own store: reactions are filed there, whatever store the record is in
        self.reader = reader or actor
        self.marks = marks if marks is not None else CH.Marks()
        self.past = {}

    def past_report(self, store, snap):
        """The store as the reader last marked it (else: its records dated before the last day), assessed."""
        mark = self.marks.get(self.reader, store)
        keep = mark if mark is not None else CH.before(snap, time.time() - CH.DAY)
        key = hashlib.sha256("".join(sorted(keep)).encode()).hexdigest()
        if self.past.get(store, (None,))[0] != key:          # one past per store, kept while its mark is the same
            self.past[store] = (key, CH.report_of(self.space.roots[store], CH.subset(snap, keep)))
        return self.past[store][1], mark is not None

    def page_changes(self, q):
        card = lambda schema: LZ.card_of(self.pick(schema, None)[1])
        now, past, marked = {}, {}, False
        for n, root in self.space.roots.items():
            rep1 = self.space.report(n)
            if "_error" not in rep1:
                now[n] = rep1
                past[n], marked = self.past_report(n, Repo(root).store.snapshot())
        new = {n: set(now[n]["_recs"]) - set(past[n]["_recs"]) for n in now}
        results, accounted = {}, set()
        for n in now:
            pointing = [(i, now[m]["_recs"][i]["body"].get("target")) for m in now if m != n for i in new[m]
                        if now[m]["_recs"][i]["kind"] == "attest" and now[m]["_recs"][i]["body"].get("verdict") == "react"]
            rows, acc = CH.delta(sys.modules[__name__], past[n], now[n], card,
                                 foreign_a=lambda d, n=n: reactions_elsewhere(past, n, d),
                                 foreign_b=lambda d, n=n: reactions_elsewhere(now, n, d), touched_from_elsewhere=pointing)
            results[n] = rows
            accounted |= acc
        h, foots = "", []
        schemas = sorted({x["schema"] for rows in results.values() for x in rows})
        moved = [(sc, LZ.choose(past, self.reader, sc), LZ.choose(now, self.reader, sc)) for sc in schemas]
        moved = [(sc, a, b) for sc, a, b in moved if (a and a[1]) != (b and b[1])]
        if moved:
            name = lambda c: c[2]["name"] if c else LZ.BUILTIN["name"]
            h += ('<p><b class="PENDING">твоя лінза змінилась відтоді</b>: ' + "; ".join(
                f"{E(sc)}: «{E(name(a))}» → «{E(name(b))}»" for sc, a, b in moved)
                + '. Обидва стани нижче порівняно під теперішньою лінзою.</p>')
        for n in now:
            rows, quiet = results[n], len(new[n] - accounted)
            if not new[n] and not rows:
                continue
            h += (f'<div class="card"><b>{E(n)}</b> <span class="rest">нових записів {len(new[n])}; змінилось для тебе ліній: '
                  f'{len(rows)}; не змінили нічого, що ти бачиш: {quiet}</span>' + "".join(change_html(now[n], n, x, now) for x in rows) + END)
            foots.append(f'{E(n)} · було <code title="{E(past[n]["snapshot"])}">{E(past[n]["snapshot"][:12])}</code> · '
                         f'стало <code title="{E(now[n]["snapshot"])}">{E(now[n]["snapshot"][:12])}</code>')
        top = (f'<h2>Що змінилось для {E(self.reader or "читача")}</h2><p class="rest">з {E(CH.since_text(marked))}, '
               f'під твоїми лінзами; повнота {tag("UNATTESTED")}</p>'
               f'<form method="post" action="/seen"><input type="hidden" name="token" value="{self.token}">'
               f'<button type="submit">Позначити все як переглянуте</button></form>')
        return page("Що змінилось", top + (h or "<p>Нічого не змінилось у тому, що ти бачиш.</p>"), "<br>".join(foots))

    def seen(self, form):
        ok = secrets.compare_digest(form.get("token", ""), self.token)
        if not ok:
            return 403, "the token of this run is missing or wrong"
        self.marks.set(self.reader, {n: set(Repo(r).store.snapshot().lines) for n, r in self.space.roots.items()})
        return 303, "/changes"

    def reports(self):
        return {n: self.space.report(n) for n in self.space.roots}

    FEED_LIMIT = 300

    def page_feed(self, q):
        """The newest records of the stores asked, and what the page leaves out, named with how many: the records of
        automatic actors (unless asked), migration records, those past the limit, the stores it could not read. The
        feed's contract (contract.feed_check) is checked on the page drawn and a broken promise is named on it."""
        store, actor, machines = q.get("store"), q.get("actor") or None, q.get("machines") == "1"
        rows, foots, omitted, unread = [], [], {}, []
        reports = self.reports()
        for n, rep in reports.items():
            if store and n != store:
                continue
            if "_error" in rep:
                unread.append((n, rep["_error"]))
                continue
            rows += [(n, x) for x in feed(rep, None, actor, machines, omitted)]
            foots.append(foot(n, rep, {"op": "feed", "actor": actor, "machines": machines}))
        rows.sort(key=lambda nx: (-nx[1]["at"], nx[0], nx[1]["id"]))
        if len(rows) > self.FEED_LIMIT:
            omitted["limit"] = len(rows) - self.FEED_LIMIT
        opts = " · ".join(f'<a href="/?store={quote(n)}">{E(n)}</a>' for n in self.space.roots)
        flt = (f'<div class="filters">сховище: <a href="/">усі</a> · {opts} · '
               + ('<a href="/?machines=0">сховати автоматичні</a>' if machines else '<a href="/?machines=1">показати автоматичні</a>')
               + "</div>")
        h = "<h2>Стрічка</h2>" + flt + feed_scope_html(store, actor, omitted, unread) + CONTRACT
        h += "".join(item(n, x) for n, x in rows[:self.FEED_LIMIT])
        broken = CT.feed_check(reports, h, store, actor, machines, self.FEED_LIMIT)
        self.last_feed_contract = broken
        h = h.replace(CONTRACT, contract_html(broken, "стрічка не тримає свій контракт"), 1)
        return page("Стрічка", h, "<br>".join(foots))

    def pick(self, schema, asked):
        """(lens id, body, note): the lens named by the page (`?lens=ID` or `builtin`), else the one the reader
        adopted last for this schema, else the built-in; a lens this interpreter cannot draw is UNSUPPORTED and the
        built-in draws the page, saying so. A lens's own lineage is always drawn by the built-in."""
        builtin = ("builtin", LZ.BUILTIN, "", None)
        if schema == LZ.LENS or asked == "builtin":
            return builtin
        reports = self.reports()
        if asked:
            hit = LZ.find(reports, asked)
            found = None if hit is None else (asked, hit[1], hit[0])
            if found is None:
                return builtin[:2] + (f" · лінзи <code>{E(asked[:12])}</code> тут немає", None)
        else:
            got = LZ.choose(reports, self.reader, schema)
            found = None if got is None else (got[1], got[2], got[0])
        if found is None:
            return builtin
        why = LZ.problem(found[1])
        if why:
            return builtin[:2] + (f" · лінза <code>{E(found[0][:12])}</code> не підтримується: {E(why)}", None)
        return found[0], found[1], "", found[2]

    def others(self, schema):
        """[(lens id, name)] of every lens version this interpreter draws that applies to `schema`, and the built-in."""
        out = [("builtin", LZ.BUILTIN["name"])]
        for _, rep in sorted(self.reports().items()):
            if "_error" not in rep:
                out += sorted((v, b["name"]) for v, b in LZ.lenses(rep).items()
                              if b.get("applies") in (schema, "*") and LZ.problem(b) is None)
        return out

    def seen_then(self, store, seen_id):
        """(report, lens id, note) of the store as the reader's view `seen_id` recorded it: the records dated no later
        than that view, assessed by the same engine, under the lens it names. Its root is checked against the root the
        view recorded: the same root says the page is the one seen; another, that the dates do not rebuild it."""
        r = next((x["_recs"][seen_id] for x in self.reports().values() if "_error" not in x and seen_id in x["_recs"]), None)
        if r is None or r["body"].get("verdict") != "seen":
            return None
        snap = Repo(self.space.roots[store]).store.snapshot()
        past = CH.report_of(self.space.roots[store], CH.subset(snap, CH.before(snap, r["at"] + 1)))
        same = past["snapshot"] == r["body"].get("root")
        note = (f' · як ти бачив {when(r["at"])}: '
                + ("відтворено точно (той самий root)" if same else
                   f'<b class="PENDING">наближено</b>: тоді root був <code>{E(str(r["body"].get("root"))[:12])}</code>, '
                   f'записи до тієї дати дають <code>{E(past["snapshot"][:12])}</code>'))
        return past, r["body"].get("lens", "builtin"), note

    def page_lineage(self, store, i, q=None):
        q = q or {}
        then = self.seen_then(store, q["asof"]) if q.get("asof") else None
        if then is not None:
            q = dict(q, lens=then[1])
        rep = then[0] if then else self.space.report(store)
        if "_error" in rep:
            return 404, page(MISSING, f"<p>{E(rep['_error'])}</p>")
        d = lineage(rep, i)
        if d is None:
            return 404, page(MISSING, f"<p>Немає лінії з записом <code>{E(i)}</code> у {E(store)}.</p>")
        lens_id, body, note, lens_store = self.pick(d["schema"], q.get("lens"))
        if then is not None:
            note += then[2]
        self.with_elsewhere(store, d)
        full = VW.observe(sys.modules[__name__], rep, d, dict(LZ.card_of(LZ.BUILTIN), activity="shown"))
        hidden = len(VW.difference(VW.observe(sys.modules[__name__], rep, d, LZ.card_of(body)), full)["appeared"])
        h = (floor_html(rep, store, d, (lens_id, body["name"]), note, lens_objections(self.reports(), lens_store, lens_id),
                        self.reader, hidden, self.unavailable()) + CONTRACT + grounded_html(rep, store, d["grounded"]))
        if q.get("vs") and d["schema"] != LZ.LENS:
            other = LZ.find(self.reports(), q["vs"])
            if other is not None and LZ.problem(other[1]) is None:
                h += diff_html(rep, d, (body["name"], other[1]["name"]), *LZ.diff(d, body, other[1]),
                               LZ.presentation(body, other[1]))
        if d["schema"] != LZ.LENS:
            alts = [(v, n) for v, n in self.others(d["schema"]) if v != lens_id]
            if alts:
                h += ('<p class="rest">порівняти з: ' + " · ".join(
                    f'<a href="/l/{quote(store)}/{E(d["lineage"])}?lens={E(lens_id)}&amp;vs={E(v)}">{E(n)}</a>' for v, n in alts) + "</p>")
        if d["schema"] == LZ.LENS and d["leaf"]:
            why = LZ.problem(rep["_recs"][d["leaf"]]["body"])
            h += f'<p>Ця лінза {"малюється" if why is None else "не підтримується: " + E(why)}.</p>'
            if self.actor and self.key and why is None:
                h += self.adopt_form(store, d["leaf"])
        if self.actor and self.key and d["leaf"]:
            h += self.read_form(store, d["leaf"], lens_id) + self.form(store, d["leaf"])
        h += versions_html(rep, d, LZ.card_of(body))
        broken = CT.check(d, LZ.card_of(body), standing(rep, d), h)
        self.last_contract = {"lens": lens_id, "broken": broken}
        h = h.replace(CONTRACT, contract_html(broken), 1)
        query = {"op": "lineage", "target": d["lineage"], "lens": lens_id, "with": self.other_roots(store)}
        return 200, page(d["label"], h, foot(store, rep, query))

    def with_elsewhere(self, store, d):
        """`d` with, among each version's activity, the reactions on it filed in other stores."""
        elsewhere = reactions_elsewhere(self.reports(), store, d)
        for v in d["versions"]:
            v["on"] = sorted(v["on"] + elsewhere.get(v["id"], []), key=lambda x: (x["at"], x["id"]))
        return d

    def unavailable(self):
        """[(store, why)] of every store this server was asked to read and could not."""
        return [(n, r["_error"]) for n, r in sorted(self.reports().items()) if "_error" in r]

    def other_roots(self, store):
        """{store: [snapshot root, trust, profile]} of every other store a page read (the lens chosen, the observations
        filed elsewhere, the challenges against the lens): a page is a function of all of them, so its lens names them."""
        return {n: [r["snapshot"], r["trust"], r["profile"]] for n, r in sorted(self.reports().items())
                if n != store and "_error" not in r}

    def page_scene(self, store, i, q=None):
        """The lineage as a map under the reader's lens (or `?lens=`), the floor above it; `?vs=` sets a second lens's
        map beside it and names what moved and which bindings differ."""
        rep = self.space.report(store)
        d = None if "_error" in rep else lineage(rep, i)
        if d is None:
            return 404, page(MISSING, f"<p>Немає лінії з записом <code>{E(i)}</code> у {E(store)}.</p>")
        q = q or {}
        lens_id, body, note, lens_store = self.pick(d["schema"], q.get("lens"))
        self.with_elsewhere(store, d)
        describe = lambda x: " ".join(str(t) for t in (sentence(rep, x) if x in rep["_recs"] else (x[:12],)) if t)
        h = (floor_html(rep, store, d, (lens_id, body["name"]), note, lens_objections(self.reports(), lens_store, lens_id),
                        unavailable=self.unavailable()) + CONTRACT)
        drawn, legend = SC.svg(rep, store, d, LZ.card_of(body), describe)
        other = LZ.find(self.reports(), q["vs"]) if q.get("vs") else None
        if other is not None and LZ.problem(other[1]) is None:
            drawn2, legend2 = SC.svg(rep, store, d, LZ.card_of(other[1]), describe)
            moves, binds = SC.moved(rep, d, LZ.card_of(body), LZ.card_of(other[1]))
            h += (f'<div class="card"><b>Дві карти</b>: «{E(body["name"])}» і «{E(other[1]["name"])}» · переміщено вузлів: '
                  f'{len(moves)} · прив\'язки: ' + (", ".join(f"{E(k)}: {E(a)} → {E(b)}" for k, a, b in binds) or "однакові")
                  + f'</div><div class="scenes"><div>{drawn}{legend}</div><div>{drawn2}{legend2}</div></div>')
        else:
            h += f'<div class="scenes"><div>{drawn}{legend}</div></div>'
        alts = [(v, n) for v, n in self.others(d["schema"]) if v != lens_id]
        if alts:
            h += ('<p class="rest">поруч із: ' + " · ".join(
                f'<a href="/s/{quote(store)}/{E(d["lineage"])}?lens={E(lens_id)}&amp;vs={E(v)}">{E(n)}</a>' for v, n in alts) + "</p>")
        broken = CT.map_check(standing(rep, d), SC.nodes_of(rep, d), h)
        self.last_contract = {"lens": lens_id, "broken": broken}
        h = h.replace(CONTRACT, contract_html(broken, "карта не тримає контракт"), 1)
        query = {"op": "scene", "target": d["lineage"], "lens": lens_id, "vs": q.get("vs"), "with": self.other_roots(store)}
        return 200, page(d["label"], h, foot(store, rep, query))

    def read_form(self, store, v, lens_id):
        return (f'<form method="post" action="/read"><input type="hidden" name="token" value="{self.token}">'
                f'<input type="hidden" name="store" value="{E(store)}"><input type="hidden" name="target" value="{E(v)}">'
                f'<input type="hidden" name="lens" value="{E(lens_id)}">'
                f'<button type="submit">Прочитав: підписати, що бачив цю версію</button></form>')

    def adopt_form(self, store, v):
        return (f'<form method="post" action="/adopt"><input type="hidden" name="token" value="{self.token}">'
                f'<input type="hidden" name="store" value="{E(store)}"><input type="hidden" name="target" value="{E(v)}">'
                f'<button type="submit">Прийняти цю лінзу для себе</button></form>')

    def form(self, store, v):
        rows = "".join(f'<label for="{k}">{E(n)}</label><input type="range" id="{k}" name="{k}" min="{lo}" max="{hi}" '
                       f'value="{0 if lo < 0 else 50}"><span class="rest">{lo}..{hi}</span>'
                       for k, lo, hi, n in DIMENSIONS)
        return (f'<details class="card"><summary>Відреагувати як <b>{E(self.actor)}</b> на останню версію</summary>'
                f'<form class="react" method="post" action="/react"><input type="hidden" name="token" value="{self.token}">'
                f'<input type="hidden" name="store" value="{E(store)}"><input type="hidden" name="target" value="{E(v)}">'
                f'{rows}<textarea name="note" placeholder="нотатка (необов\'язково)"></textarea>'
                f'<button type="submit">Підписати реакцію</button></form></details>')

    def page_wait(self, q):
        actor = q.get("actor") or self.actor or "s0fractal"
        h, foots = f"<h2>Чекає на {E(actor)}</h2>", []
        for n, rep in self.reports().items():
            if "_error" in rep:
                h += f'<div class="card"><b>{E(n)}</b>: {E(rep["_error"])}</div>'
                continue
            w = waiting(rep, actor)
            rows = ([f"<li>прийняти або заперечити: {link_l(n, x['lineage'], E(x['label'] + ': ' + x['title']))}"
                     f" <span class='rest'>— {E('; '.join(x['waiting']))}</span></li>" for x in w["attest"]]
                    + [f"<li>твоє, чекає: {link_l(n, x['lineage'], E(x['label'] + ': ' + x['title']))}"
                       f" <span class='rest'>— {E('; '.join(x['waiting']))}</span></li>" for x in w["pending"]]
                    + [f"<li>заперечено: {link_l(n, x['lineage'], E(x['label'] + ': ' + x['title']))}</li>" for x in w["challenged"]])
            h += (f'<div class="card"><b>{E(n)}</b> <span class="rest">ролі: {E(", ".join(w["roles"]) or "немає")}</span>'
                  + (f"<ul>{''.join(rows)}</ul>" if rows else "<p class='rest'>нічого</p>") + "</div>")
            foots.append(foot(n, rep, {"op": "frontier", "actor": actor}))
        return page("Чекає", h, "<br>".join(foots))

    def hypothesis(self, store, without):
        """view.what_if of one store under hypothesis `without`, or None when the store or the hypothesis is unknown."""
        rep = self.space.report(store) if store in self.space.roots else {"_error": "no such store"}
        drop = None if "_error" in rep else VW.dropped(rep, without)
        if drop is None:
            return None
        card = lambda schema: LZ.card_of(self.pick(schema, None)[1])
        return VW.what_if(sys.modules[__name__], self.space.roots[store], Repo(self.space.roots[store]).store.snapshot(),
                          drop, card, now=rep)

    def page_whatif(self, q):
        """What would follow if a store held none of some records: assessed by the same engine on a candidate, nothing
        filed (view.what_if, after minds' what_if)."""
        store, without = q.get("store"), q.get("without", "challenges")
        presets = " · ".join(f'<a href="/whatif?store={quote(n)}&amp;without=challenges">{E(n)}: без заперечень</a>'
                             for n in self.space.roots)
        h = ('<h2>Що було б, якби…</h2><p class="rest">Сховище без деяких записів, оцінене тим самим рушієм на кандидаті: '
             'нічого не записано і нічого не зрушено. Показано кожну лінію, чий вигляд змінюється, зі свідком; однакові '
             f'наслідки дають однаковий дайджест (як what_if у minds).</p><p class="rest">{presets}</p>')
        if not store:
            return 200, page(WHATIF, h)
        found = self.hypothesis(store, without)
        if found is None:
            return 404, page(WHATIF, h + f"<p>Невідоме сховище або гіпотеза: {E(store)}, {E(without)}.</p>")
        h += (f'<div class="card"><b>{E(store)}</b> {E(VW.HYPOTHESES.get(without.split(":")[0], without))}'
              f'{E(without[6:]) if without.startswith("actor:") else ""} · прибрано записів: {found["dropped"]} · '
              f'змінилось ліній: {len(found["rows"])} · дайджест <code>{E(found["digest"][:12])}</code>'
              '<p class="rest">кожна лінія: від гіпотези до того, як є</p>'
              + "".join(change_html(self.space.report(store), store, x, self.reports()) for x in found["rows"][:300]) + END)
        return 200, page(WHATIF, h, foot(store, self.space.report(store),
                                              {"op": "whatif", "without": without, "with": self.other_roots(store)}))

    def page_overlay(self, q):
        """A store as the reader reads it with the other stores the reader chose, under the reader's own trust and roles
        (overlay.py): beside the store's own verdict, never in its place; each lineage that reads otherwise, why."""
        h = ('<h2>Для мене: з усіма джерелами, за моїми правилами</h2><p class="rest">Сховище читається разом із вибраними '
             'тобою сховищами, за довірою й ролями з твого власного сховища. Вердикт сховища за його правилами лишається; '
             'поруч — твій, з власною ідентичністю. Чого нема у вибраних сховищах, тут нема.</p>')
        if self.mine not in self.space.roots:
            return 400, page("Для мене", h + "<p>Потрібне твоє сховище (<code>--mine</code>): його довіра й ролі — твої правила.</p>")
        store = q.get("store") or next((n for n in self.space.roots if n != self.mine), None)
        readable = [n for n, r in self.reports().items() if "_error" not in r]
        if store not in readable:
            return 404, page("Для мене", h + f"<p>Немає такого сховища: {E(str(store))}.</p>")
        chosen = [n for n in (q.get("with").split(",") if q.get("with") else readable) if n in readable and n != store]
        names = [store] + chosen
        snaps = {n: Repo(self.space.roots[n]).store.snapshot() for n in names}
        trust, profile, _ = Repo(self.space.roots[self.mine]).config()
        t, p, conflicts = OVL.receiver(trust, profile, {n: Repo(self.space.roots[n]).config()[0] for n in names})
        over = OVL.assess(snaps, t, p)
        base = self.space.report(store)
        card = lambda schema: LZ.card_of(self.pick(schema, None)[1])
        rows = [x for x in VW.delta(sys.modules[__name__], base, over, card)[0] if x["lineage"] in base["lineages"]]
        ident = OVL.identity(snaps, t, p, over["code"])
        asked = sorted({r for v in base["versions"].values() for r in v.get("roles", [])})
        unnamed = [r for r in asked if not p["roles"].get(r)]
        picks = " · ".join(f'<a href="/overlay?store={quote(n)}">{E(n)}</a>' for n in readable if n != self.mine)
        h += (f'<p class="rest">сховище: {picks}</p><div class="card"><b>{E(store)}</b> разом із {E(", ".join(chosen) or "нічим")} · '
              f'за правилами сховища <b>{E(self.mine)}</b> · змінилось для тебе ліній: {len(rows)} · ідентичність '
              f'<code title="{E(ident)}">{E(ident[:12])}</code><p class="rest">кожна лінія: у {E(store)} за його правилами → для тебе</p>'
              + (f'<p><b class="PENDING">твої правила не називають, хто має ці ролі: {E(", ".join(unnamed))}</b>: '
                 f'версії, яких вони чекають, для тебе не прийняті (впиши ролі в .warrant/v3.json сховища {E(self.mine)})</p>'
                 if unnamed else "")
              + (f'<p><b class="PENDING">не прийнято прив\'язок ключів: {len(conflicts)}</b> ('
                 + E("; ".join(f"{a}: {', '.join(sorted(by))}" for a, by in conflicts)) + '): сховища не згодні, чий це ключ</p>'
                 if conflicts else "")
              + "".join(change_html(over, store, x, self.reports()) for x in rows[:200]) + END)
        return 200, page("Для мене", h, foot(store, base, {"op": "overlay", "with": self.other_roots(store), "overlay": ident}))

    def page_fragile(self, q=None):
        """Where attention went and where one objection holds against it (warrant_agent/fragile.py)."""
        found = FR.rows(sys.modules[__name__], self.reports())
        moves = {}
        for n in sorted({r["store"] for r in found}):
            hyp = self.hypothesis(n, "challenges")
            for x in (hyp or {"rows": []})["rows"]:
                moves[(n, x["lineage"])] = _floor_moves(x["floor_before"], x["floor_after"])
        def status(c):
            if c["reproduced"]:
                return '<b class="CHALLENGED">відтворене</b>'
            if c["counted"] and c["stands"]:
                return '<b class="CHALLENGED">зараховане, стоїть</b>'
            return "зараховане, не стоїть" if c["counted"] else "не зараховане"
        h = ('<h2>Крихке популярне</h2><p class="rest">Лінії, проти яких хтось заперечив, від найбільш уважених. Один '
             'відтворений контрприклад важить більше за будь-яку кількість згод; тут вони стоять поруч і ніколи не '
             'складаються в один бал. Увага рахується лише з ключів, яким довіряє якесь із прочитаних сховищ.</p>')
        for r in found[:200]:
            a = r["attention"]
            h += (f'<div class="card">{link_l(r["store"], r["lineage"], E(r["label"] + ": " + r["title"]))} '
                  f'<span class="rest">({E(r["store"])}) · увага: {len(a["all"])} (бачили {len(a["saw"])}, прийняли '
                  f'{len(a["accepted"])}, відреагували {len(a["reacted"])})</span>'
                  + (f'<p class="rest">що зрушують заперечення (без них → з ними): {"; ".join(moves[(r["store"], r["lineage"])])}</p>'
                     if moves.get((r["store"], r["lineage"])) else "") + '<ul>'
                  + "".join(f'<li><span class="actor">{E(c["actor"])}</span> заперечив · {status(c)} — {E(c["statement"][:300])}</li>'
                            for c in r["challenges"]) + "</ul></div>")
        who = FR.finders(found)
        if who:
            h += ('<h3>Хто вказав</h3><p class="rest">Визнання, прочитане з записів, а не рейтинг: заперечення, відтворене '
                  'на своїй цілі або зараховане й чинне, з увагою, яку мало те, проти чого воно стоїть. Жоден охоронець '
                  'цього не читає.</p><ul>'
                  + "".join(f'<li><span class="actor">{E(actor)}</span>: ' + "; ".join(
                      f'{link_l(r["store"], r["lineage"], E(r["label"]))} ×{n} (увага {len(r["attention"]["all"])})' for r, n in items[:12])
                      + "</li>" for actor, items in who) + "</ul>")
        return page("Крихке", h, "<br>".join(foot(n, r, {"op": "fragile", "with": self.other_roots(n)})
                                             for n, r in self.reports().items() if "_error" not in r))

    def page_stores(self):
        h = "<h2>Сховища</h2>"
        for n, root in self.space.roots.items():
            rep = self.space.report(n)
            if "_error" in rep:
                h += f'<div class="card"><b>{E(n)}</b> <code>{E(root)}</code><br>{E(rep["_error"])}</div>'
                continue
            states = {}
            for lin in rep["lineages"].values():
                states[lin["reliance"]] = states.get(lin["reliance"], 0) + 1
            h += (f'<div class="card"><b><a href="/?store={quote(n)}">{E(n)}</a></b> <code>{E(root)}</code><br>'
                  f'{len(rep["_recs"])} записів · {len(rep["lineages"])} ліній · '
                  + " ".join(f"{tag(k)} {v}" for k, v in sorted(states.items()))
                  + f'<br><span class="rest">повнота: {E(str(rep.get("completeness")))} · проблем: {len(rep["problems"])}'
                  f' · відкинуто: {len(rep["rejected"])}</span></div>')
        return page("Сховища", h)

    def _file(self, form, body_of, into=None):
        if not secrets.compare_digest(form.get("token", ""), self.token):
            return 403, "the token of this run is missing or wrong"
        if not (self.actor and self.key):
            return 403, "this server was started without --actor and --key"
        store, target = form.get("store", ""), form.get("target", "")
        if store not in self.space.roots:
            return 400, "no such store"
        rep = self.space.report(store)
        if "_error" in rep or target not in rep["_recs"]:
            return 400, "no such record in that store"
        body, why = body_of(rep, target, form)
        if body is None:
            return 400, why
        try:
            Repo(self.space.roots[into or store]).file(self.actor, self.key, [R.record("attest", self.actor, 0, body, refs=[target])])
        except (Failed, ValueError) as e:
            return 400, f"{type(e).__name__}: {e}"
        return 303, f"/l/{quote(store)}/{target}"

    def mine_lost(self):
        """(400, why) when the reader named an own store this server does not read: nothing is filed (fail closed)."""
        if self.mine is not None and self.mine not in self.space.roots:
            return 400, f"the reader's own store {self.mine!r} is not read by this server: nothing is filed"
        return None

    def observe(self, form, kind):
        """File the reader's observation of `kind` (observe.py): in the reader's own store for a `mine` kind (refused when
        that store is not read: nothing is filed), else in the store holding the record."""
        mine = OB.KINDS[kind].into == "mine"
        lost = self.mine_lost() if mine else None
        if lost:
            return lost
        return self._file(form, lambda rep, target, f: OB.body(kind, rep, target, f), into=self.mine if mine else None)

    def read(self, form):
        return self.observe(form, "seen")

    def react(self, form):
        return self.observe(form, "react")

    def adopt(self, form):
        return self.observe(form, "adopt")


def handler(app, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass                # a request line names records the reader opened: it stays out of the terminal

        def send(self, code, text, ctype="text/html; charset=utf-8", location=None):
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; form-action 'self'")
            self.send_header("X-Frame-Options", "DENY")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(data)

        def host_ok(self):
            if self.headers.get("Host") not in hosts:
                self.send(421, "this server answers only on its own host", TEXT)
                return False
            return True

        def do_GET(self):
            if not self.host_ok():
                return
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            parts = [p for p in u.path.split("/") if p]
            try:
                if not parts:
                    self.send(200, app.page_feed(q))
                elif parts == ["changes"]:
                    self.send(200, app.page_changes(q))
                elif parts == ["overlay"]:
                    self.send(*app.page_overlay(q))
                elif parts == ["whatif"]:
                    self.send(*app.page_whatif(q))
                elif parts == ["fragile"]:
                    self.send(200, app.page_fragile(q))
                elif parts == ["wait"]:
                    self.send(200, app.page_wait(q))
                elif parts == ["stores"]:
                    self.send(200, app.page_stores())
                elif parts[0] == "s" and len(parts) == 3 and parts[1] in app.space.roots:
                    self.send(*app.page_scene(parts[1], parts[2], q))
                elif parts[0] == "l" and len(parts) == 3 and parts[1] in app.space.roots:
                    self.send(*app.page_lineage(parts[1], parts[2], q))
                else:
                    self.send(404, page(MISSING, "<p>Немає такої сторінки.</p>"))
            except Exception as e:      # one page's failure is that page's answer, never the server's end
                self.send(500, page("Помилка", f"<pre>{E(type(e).__name__)}: {E(str(e))}</pre>"))

        def do_POST(self):
            if not self.host_ok():
                return
            path = urlparse(self.path).path
            if path not in ("/react", "/adopt", "/seen", "/read"):
                return self.send(404, "no such endpoint", TEXT)
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                return self.send(413, "too large", TEXT)
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace")).items()}
            code, out = {"/react": app.react, "/adopt": app.adopt, "/seen": app.seen, "/read": app.read}[path](form)
            if code == 303:
                self.send(303, "", location=out)
                return
            # a signature not filed is said where the reader looks (the page) and where the operator looks (the terminal)
            sys.stderr.write(f"warrant serve: {path} not filed ({code}): {out}\n")
            back = f'/l/{quote(form.get("store", ""))}/{quote(form.get("target", ""))}' if form.get("target") else "/"
            self.send(code, page("Не підписано", f'<h2>Не підписано</h2><p>{E(out)}</p><p><a href="{E(back)}">назад</a></p>'))
    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(prog="warrant serve", description=__doc__.split("\n\n")[0])
    p.add_argument("--root", action="append", help="a repository to read (repeatable); default: every one Home registers")
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--actor", help="who signs reactions")
    p.add_argument("--key", help="the actor's seed, a file outside every repository read")
    p.add_argument("--reader", help="whose adopted lenses draw the pages (default: --actor)")
    p.add_argument("--mine", help="the store a reaction is filed in, whatever store its record is in "
                                   "(default: the one registered as `space`, if any; else the record's own store)")
    a = p.parse_args(argv)
    space = Space({Path(r).resolve().name: str(Path(r).resolve()) for r in a.root}) if a.root else Space.from_home()
    if not space.roots:
        space = Space({Path.cwd().name: str(Path.cwd())})
    key = None
    if a.key:
        if not a.actor:
            p.error("--key needs --actor")
        key = load_key(a.key, next(iter(space.roots.values())))
        for root in space.roots.values():
            if Path(a.key).expanduser().resolve().is_relative_to(Path(root).resolve()):
                p.error(f"the seed lies inside {root}")
    if a.mine and a.mine not in space.roots:
        p.error(f"--mine {a.mine}: no store of that name is read ({', '.join(space.roots)})")
    mine = a.mine or ("space" if "space" in space.roots else None)
    app = App(space, a.actor, key, a.reader, mine=mine)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), handler(app, a.port))
    mode = "; read only"
    if key:
        mode = f"; reactions signed as {a.actor}" + (f", filed in {mine}" if mine else "")
    print(f"warrant serve: http://127.0.0.1:{a.port}/ over {', '.join(space.roots)}{mode}", flush=True)  # NOSONAR S5332: the loopback address this server binds; no TLS on 127.0.0.1
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
