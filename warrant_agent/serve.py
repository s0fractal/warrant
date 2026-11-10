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
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from warrant import graph as G
from warrant import home as H
from warrant import records as R
from warrant.repo import Failed, Repo, load_key
from warrant_agent import glossary as GL

DIMENSIONS = (("agree", -100, 100, "згода"), ("confidence", 0, 100, "впевненість"),
              ("importance", 0, 100, "важливість"), ("evidence", 0, 100, "якість доказу"))
MACHINES = ("claims-checker", "review-replayer")        # actors that sign by program; hidden from the feed by default
ADAPTER = "warrant-serve/0:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
NOTE_MAX = 4000


def is_machine(actor):
    return actor in MACHINES or actor.startswith("checker ")


# ---------------------------------------------------------------- projections: pure over a report

def _root_of(rep, i):
    for L, lin in rep["lineages"].items():
        if i in lin["versions"]:
            return L
    return None


def title(rep, i, n=160):
    """What a record is about, in its own words: an entity's statement, text or title (its lineage root's when the
    version has none), a challenge's statement; else the short id."""
    recs = rep["_recs"]
    r = recs.get(i)
    if r is None:
        return i[:12]
    b = r["body"]
    for k in ("statement", "text", "title"):
        if isinstance(b.get(k), str) and b[k].strip():
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


def dims(body):
    return {k: body[k] for k, lo, hi, _ in DIMENSIONS if R.is_int(body.get(k)) and lo <= body[k] <= hi}


def sentence(rep, i):
    """One record as one sentence: (actor, verb, what, rest); the page joins them, escaping each."""
    r = rep["_recs"][i]
    a, b, k = r["actor"], r["body"], r["kind"]
    if k == "entity":
        s, state = (r.get("schema") or "").split("@")[0], b.get("state")
        what = f"{label(rep, i)}: «{title(rep, i)}»"
        first = r.get("lineage") is None
        verbs = {("obligation", "open"): "відкрив обов'язок", ("obligation", "done"): "закрив обов'язок",
                 ("obligation", "released"): "звільнив обов'язок", ("goal", "open"): "поставив ціль",
                 ("pr-head", "open"): "відкрив", ("pr-head", "head"): "подав нову голову", ("pr-head", "merged"): "злив"}
        verb = verbs.get((s, state)) or (f"подав {s}" if first else f"нова версія {s}") + (f" → {state}" if state else "")
        rest = ""
        if isinstance(b.get("established"), list) and state != "head":
            rest = f"встановлено {len(b['established'])}, залишків {len(b.get('residual') or [])}"
        return a, verb, what, rest
    if k == "attest":
        t, v = b.get("target"), b.get("verdict")
        tw = f"{label(rep, t)}: «{title(rep, t)}»" if t else ""
        if v == "accept":
            return a, "прийняв", tw, ""
        if v == "react":
            d = dims(b)
            return a, "відреагував на", tw, ", ".join(f"{n} {d[x]:+d}" if x == "agree" else f"{n} {d[x]}"
                                                     for x, _, _, n in DIMENSIONS if x in d)
        if v == "reproduces":
            return a, "відтворив заперечення", tw, ""
        if v == "does_not_reproduce":
            return a, "не відтворив заперечення", tw, ""
        return a, f"атестував ({v})", tw, ""
    if k == "challenge":
        t = b.get("target")
        return a, "заперечив", f"{label(rep, t)}: «{title(rep, t)}»" if t else "", title(rep, i)
    if k == "schema":
        return a, "подав схему", title(rep, i), ""
    return a, f"подав {k}", title(rep, i), ""


def feed(rep, limit=200, actor=None, machines=False):
    """The newest records first (by `at`, then id): a list of {id, at, kind, actor, sentence, lineage}."""
    out = []
    for i, r in rep["_recs"].items():
        if (actor and r["actor"] != actor) or (not machines and is_machine(r["actor"])):
            continue
        if r.get("schema") == "v2-transition@1":
            continue
        t = r["body"].get("target") if r["kind"] in ("attest", "challenge") else i
        out.append({"id": i, "at": r["at"], "kind": r["kind"], "actor": r["actor"], "sentence": sentence(rep, i),
                    "lineage": _root_of(rep, t) if t else None, "target": t})
    out.sort(key=lambda x: (-x["at"], x["id"]))
    return out[:limit]


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
    _, _, into = G.index(rep)
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
    """The body of a reaction from a submitted form, or a reason it is none."""
    body = {"target": target, "verdict": "react"}
    for k, lo, hi, _ in DIMENSIONS:
        raw = form.get(k, "")
        if raw == "":
            continue
        try:
            n = int(raw)
        except ValueError:
            return None, f"{k} is not an integer"
        if not lo <= n <= hi:
            return None, f"{k} lies outside {lo}..{hi}"
        body[k] = n
    note = form.get("note", "").strip()
    if len(note) > NOTE_MAX:
        return None, f"a note is at most {NOTE_MAX} characters"
    if note:
        body["note"] = note
    if len(body) == 2:
        return None, "a reaction names one dimension or a note"
    return body, None


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
            rep["_profile"] = repo.config()[1]      # the report names its profile by digest; the frontier reads it
        except (Failed, OSError, ValueError) as e:
            rep = {"_error": f"{type(e).__name__}: {e}"}
        self.cache[name] = (stamp, rep)
        return rep


# ---------------------------------------------------------------- pages

E = html.escape
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
ul{margin:4px 0 4px 18px;padding:0}footer{color:var(--mute);font-size:12px;padding:16px;text-align:center;word-break:break-all}
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
    return (f'<div class="item"><span class="when">{when(x["at"])}</span> '
            + (f'<span class="store">{E(store)}</span>' if show_store else "")
            + f'<span class="actor">{E(a)}</span> {E(verb)} {target}'
            + (f' <span class="rest">— {E(rest)}</span>' if rest else "") + "</div>")


def page(title_, body, footer=""):
    return (f'<!doctype html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
            f'initial-scale=1"><title>{E(title_)}</title><style>{CSS}</style></head><body><header><a href="/">warrant</a>'
            f'<nav><a href="/">Стрічка</a><a href="/wait">Чекає на мене</a><a href="/stores">Сховища</a></nav></header>'
            f'<main>{body}</main><footer>{footer}</footer></body></html>')


def foot(name, rep, query):
    x = lens(rep, query)
    return f'{E(name)} · root <code>{E(x["root"])}</code> · lens <code>{E(x["lens"])}</code>'


class App:
    def __init__(self, space, actor=None, key=None):
        self.space, self.actor, self.key, self.token = space, actor, key, secrets.token_hex(16)

    def reports(self):
        return {n: self.space.report(n) for n in self.space.roots}

    def page_feed(self, q):
        store, actor, machines = q.get("store"), q.get("actor") or None, q.get("machines") == "1"
        rows, foots = [], []
        for n, rep in self.reports().items():
            if (store and n != store) or "_error" in rep:
                continue
            rows += [(n, x) for x in feed(rep, 300, actor, machines)]
            foots.append(foot(n, rep, {"op": "feed", "actor": actor, "machines": machines}))
        rows.sort(key=lambda nx: (-nx[1]["at"], nx[0], nx[1]["id"]))
        opts = " · ".join(f'<a href="/?store={quote(n)}">{E(n)}</a>' for n in self.space.roots)
        flt = (f'<div class="filters">сховище: <a href="/">усі</a> · {opts} · '
               + ('<a href="/?machines=0">сховати автоматичні</a>' if machines else '<a href="/?machines=1">показати автоматичні</a>')
               + "</div>")
        return page("Стрічка", "<h2>Стрічка</h2>" + flt + "".join(item(n, x) for n, x in rows[:300]), "<br>".join(foots))

    def page_lineage(self, store, i):
        rep = self.space.report(store)
        if "_error" in rep:
            return 404, page("Немає", f"<p>{E(rep['_error'])}</p>")
        d = lineage(rep, i)
        if d is None:
            return 404, page("Немає", f"<p>Немає лінії з записом <code>{E(i)}</code> у {E(store)}.</p>")
        g = d["grounded"]
        gr = "" if g is None else (
            f'<p>Обґрунтоване: <b class="{"yes" if g["grounded"] else "no"}">{"так" if g["grounded"] else "ні"}</b> '
            f'(усе, на чому воно тримається, транзитивно: {g["closure"]} версій)'
            + ("".join(f"<br>· {link_l(store, v, E(label(rep, v) + ': ' + title(rep, v, 90)))} — {E(why)}" for v, why in g["failing"][:12]))
            + "</p>")
        h = (f'<h2>{E(d["label"])}: {E(d["title"])}</h2><p>{E(d["schema"])} · стан <b>{E(str(d["state"]))}</b> · '
             f'опора {tag(d["reliance"])}</p>' + gr)
        if self.actor and self.key and d["leaf"]:
            h += self.form(store, d["leaf"])
        for v in d["versions"]:
            rec, gd = v["record"], v["guard"]
            mark = " (дієва)" if v["id"] == d["effective"] else ""
            body = rec["body"]
            parts = [f'<div class="card"><div><span class="when">{when(rec["at"])}</span> <span class="actor">{E(rec["actor"])}</span> '
                     f'версія{E(mark)} · стан <b>{E(str(body.get("state")))}</b> · охоронець {tag(gd.get("guard", "NONE"))}'
                     + (f' · прийняли: {E(", ".join(gd["accepted_by"]))}' if gd.get("accepted_by") else "")
                     + f' · <code>{E(v["id"][:12])}</code></div>']
            for k in ("statement", "text"):
                if isinstance(body.get(k), str) and (k != "statement" or v["id"] != d["lineage"] or len(d["versions"]) == 1):
                    parts.append(f"<p>{E(body[k])}</p>")
            for k, name in (("established", "Встановлено"), ("residual", "Залишки")):
                if isinstance(body.get(k), list) and body[k]:
                    parts.append(f"<b>{name}</b><ul>" + "".join(f"<li>{E(str(x))}</li>" for x in body[k]) + "</ul>")
            if gd.get("waiting"):
                parts.append("<p class='rest'>Чекає: " + E("; ".join(gd["waiting"])) + "</p>")
            for x in v["on"]:
                a, verb, _, rest = x["sentence"]
                c = x["challenge"]
                st = "" if c is None else (" · " + ("зараховане" if c.get("counted") else "не зараховане")
                                           + (", стоїть" if c.get("stands") else "") + (f', відтворень {len(c["replays"])}' if c.get("replays") else ""))
                note = self.space.report(store)["_recs"][x["id"]]["body"].get("note")
                parts.append(f'<div class="item"><span class="when">{when(x["at"])}</span> <span class="actor">{E(a)}</span> '
                             f'{E(verb)}{E(st)}' + (f' <span class="rest">— {E(rest)}</span>' if rest else "")
                             + (f'<div class="rest">{E(note)}</div>' if isinstance(note, str) else "") + "</div>")
            parts.append("</div>")
            h += "".join(parts)
        return 200, page(d["label"], h, foot(store, rep, {"op": "lineage", "target": d["lineage"]}))

    def form(self, store, v):
        rows = "".join(f'<label for="{k}">{E(n)}</label><input type="range" id="{k}" name="{k}" min="{lo}" max="{hi}" '
                       f'value="{0 if lo < 0 else 50}" oninput="this.nextElementSibling.value=this.value"><output>{0 if lo < 0 else 50}</output>'
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

    def react(self, form):
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
        body, why = reaction_body(target, form)
        if body is None:
            return 400, why
        try:
            Repo(self.space.roots[store]).file(self.actor, self.key, [R.record("attest", self.actor, 0, body, refs=[target])])
        except (Failed, ValueError) as e:
            return 400, f"{type(e).__name__}: {e}"
        return 303, f"/l/{quote(store)}/{target}"


def handler(app, port):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def send(self, code, text, ctype="text/html; charset=utf-8", location=None):
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'")
            self.send_header("X-Frame-Options", "DENY")
            if location:
                self.send_header("Location", location)
            self.end_headers()
            self.wfile.write(data)

        def host_ok(self):
            if self.headers.get("Host") not in hosts:
                self.send(421, "this server answers only on its own host", "text/plain; charset=utf-8")
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
                elif parts == ["wait"]:
                    self.send(200, app.page_wait(q))
                elif parts == ["stores"]:
                    self.send(200, app.page_stores())
                elif parts[0] == "l" and len(parts) == 3 and parts[1] in app.space.roots:
                    self.send(*app.page_lineage(parts[1], parts[2]))
                else:
                    self.send(404, page("Немає", "<p>Немає такої сторінки.</p>"))
            except Exception as e:      # one page's failure is that page's answer, never the server's end
                self.send(500, page("Помилка", f"<pre>{E(type(e).__name__)}: {E(str(e))}</pre>"))

        def do_POST(self):
            if not self.host_ok():
                return
            if urlparse(self.path).path != "/react":
                return self.send(404, "no such endpoint", "text/plain; charset=utf-8")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 64 * 1024:
                return self.send(413, "too large", "text/plain; charset=utf-8")
            form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8", "replace")).items()}
            code, out = app.react(form)
            if code == 303:
                self.send(303, "", location=out)
            else:
                self.send(code, out, "text/plain; charset=utf-8")
    return Handler


def main(argv=None):
    p = argparse.ArgumentParser(prog="warrant serve", description=__doc__.split("\n\n")[0])
    p.add_argument("--root", action="append", help="a repository to read (repeatable); default: every one Home registers")
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--actor", help="who signs reactions")
    p.add_argument("--key", help="the actor's seed, a file outside every repository read")
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
    app = App(space, a.actor, key)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), handler(app, a.port))
    print(f"warrant serve: http://127.0.0.1:{a.port}/ over {', '.join(space.roots)}"
          + (f"; reactions signed as {a.actor}" if key else "; read only"), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
