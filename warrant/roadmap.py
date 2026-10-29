"""The roadmap: goals (goal@1) and the obligations that answer them (obligation@1), as records in
.warrant/records.jsonl. The rules (who closes, who accepts, who releases) are the schema records'; this
tool shows them, lists what waits for an acceptor, and files obligations and their closures.

    python3 -m warrant.roadmap [--root DIR] view [--out FILE]        # Markdown, a build artifact (build/views/)
    python3 -m warrant.roadmap [--root DIR] due --actor A [--json]   # versions waiting for A's verdict (the waker's)
    python3 -m warrant.roadmap [--root DIR] check                    # every obligation answers a goal; none forks
    python3 -m warrant.roadmap oblige --goal G --statement S [--serves ID ...] --actor A --key SEED
    python3 -m warrant.roadmap close --obligation ID [--evidence ID ...] [--ref TEXT ...] [--established TEXT ...]
                                      [--residual TEXT ...] [--requires ID ...] --actor A --key SEED

`due` is what the review waker reads at the base: a goal or obligation version whose guard waits only for
attests by a role the actor holds (nothing it requires is open), not the actor's own, neither attested nor
challenged by it (warrant.gate due_for, the same rule the merge gate admits a verdict pull request by)."""
import argparse
import sys

from . import records as R
from .gate import due_for
from .repo import Failed, Repo, dump, emit, env_root, load_key, main

GOAL, OBLIGATION = "goal@1", "obligation@1"
SCHEMAS = (GOAL, OBLIGATION)


def goals(rep):
    """{goal version id: goal key} for every version of every goal lineage."""
    recs = rep["_recs"]
    return {v: recs[L]["body"]["key"] for L, lin in rep["lineages"].items() if lin["schema"] == GOAL for v in lin["versions"]}


def due(rep, profile, actor):
    recs, keys = rep["_recs"], goals(rep)
    out = []
    for d in due_for(rep, profile, actor, SCHEMAS):
        b = recs[d["version"]]["body"]
        g = recs[d["version"]]["guard"] or {}
        out.append({"closure": d["version"], "item": 0, "duty": d["lineage"], "schema": d["schema"],
                    "goal": keys.get(b.get("answers")) or b.get("key"), "statement": b.get("statement") or b.get("text"),
                    "evidence": sorted(b.get("evidence") or []), "refs": list(b.get("refs") or []),
                    "subject": b.get("subject"), "requires": g.get("requires", [])})
    return out


def check(rep):
    recs, keys, out = rep["_recs"], goals(rep), []
    for L, lin in sorted(rep["lineages"].items()):
        if lin["schema"] not in SCHEMAS:
            continue
        if lin["verdict"] == "FORK":
            out.append(f"{L[:12]} ({lin['schema']}) forks")
        for v in lin["versions"]:
            a = recs[v]["body"].get("answers")
            if lin["schema"] == OBLIGATION and a is not None and a not in keys:
                out.append(f"obligation version {v[:12]} answers {a[:12]}, which is no goal version")
    return out


def view(rep):
    recs, keys = rep["_recs"], goals(rep)
    lines = ["# Roadmap", "", f"Generated from `.warrant/records.jsonl` (snapshot `{rep['snapshot'][:12]}`, assessment "
             f"`{rep['assessment'][:12]}`); a build artifact, never committed. Completeness: {rep['completeness']}.", ""]
    by_goal = {}
    for L, lin in rep["lineages"].items():
        if lin["schema"] == OBLIGATION:
            leaf = recs[lin["leaf"]]["body"] if lin["leaf"] else recs[L]["body"]
            by_goal.setdefault(keys.get(leaf.get("answers")), []).append((L, lin, leaf))
    for L, lin in sorted(((L, lin) for L, lin in rep["lineages"].items() if lin["schema"] == GOAL),
                         key=lambda x: int(recs[x[0]]["body"]["key"].lstrip("G") or 0)):
        g = recs[lin["effective"] or L]["body"]
        lines += [f"## {g['key']} ({lin['state']}): {g['text']}", ""]
        lines += [_obligation_view(rep, O, olin, b)
                  for O, olin, b in sorted(by_goal.get(g["key"], []), key=lambda x: (x[1]["state"] or "", recs[x[0]]["at"]))]
        lines.append("")
    loose = by_goal.get(None, [])
    if loose:
        lines += ["## Obligations that answer no goal", ""]
        lines += [f"- `{O[:12]}` **{olin['state']}** {b['statement']}" for O, olin, b in loose]
    return "\n".join(lines) + "\n"


def _obligation_view(rep, o, olin, b):
    v = rep["versions"][olin["leaf"]] if olin["leaf"] else {"guard": "FORK", "waiting": []}
    wait = f"; leaf {v['guard']}: {'; '.join(v['waiting'])}" if v["guard"] == "PENDING" else ""
    return f"- `{o[:12]}` **{olin['state']}** ({olin['reliance']}{wait}) {b['statement']}"


def run(argv=None):
    root, argv = env_root(list(sys.argv[1:] if argv is None else argv))
    ap = argparse.ArgumentParser(prog="warrant.roadmap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("view")
    v.add_argument("--out")
    d = sub.add_parser("due")
    d.add_argument("--actor", required=True)
    d.add_argument("--json", action="store_true")
    sub.add_parser("check")
    o = sub.add_parser("oblige")
    o.add_argument("--goal", required=True)
    o.add_argument("--statement", required=True)
    o.add_argument("--serves", action="append", default=[])
    c = sub.add_parser("close")
    c.add_argument("--obligation", required=True)
    for f in ("evidence", "ref", "established", "residual", "requires"):
        c.add_argument(f"--{f}", action="append", default=[])
    for p in (o, c):
        p.add_argument("--actor", required=True)
        p.add_argument("--key", required=True)
    a = ap.parse_args(argv)
    repo = Repo(root)
    rep = repo.report()
    _, profile, _ = repo.config()
    if a.cmd == "due":
        _print_due(due(rep, profile, a.actor), a.json)
        return 0
    if a.cmd == "check":
        bad = check(rep)
        for x in bad:
            print(f"PROBLEM {x}")
        print(f"roadmap: {sum(1 for x in rep['lineages'].values() if x['schema'] in SCHEMAS)} lineages, {len(bad)} problem(s)")
        return 1 if bad else 0
    if a.cmd == "view":
        emit(view(rep), a.out, root)
        return 0
    key = load_key(a.key, root)
    rec = _obligation(rep, a) if a.cmd == "oblige" else _closure(rep, a)
    dump({"filed": repo.file(a.actor, key, [rec])})
    return 0


def _print_due(got, as_json):
    if as_json:
        dump({"due": got})
    for x in [] if as_json else got:
        print(f"DUE {x['closure'][:12]} {x['schema']} {x['goal']}: {x['statement'][:100]}")


def _obligation(rep, a):
    """The obligation `oblige` files: the root of a lineage answering the goal's leaf."""
    g = next((rep["lineages"][L]["leaf"] for L, lin in rep["lineages"].items()
              if lin["schema"] == GOAL and rep["_recs"][L]["body"]["key"] == a.goal), None)
    if g is None:
        raise Failed("GOAL", f"no goal {a.goal}")
    return R.record("entity", a.actor, 0, {"state": "open", "statement": a.statement, "answers": g, "serves": sorted(a.serves)},
                    OBLIGATION, refs=[g, *a.serves])


def _closure(rep, a):
    """The `done` version `close` files on an obligation's leaf, with the schema's guard and what it requires."""
    L = a.obligation if a.obligation in rep["lineages"] else None
    if L is None or rep["lineages"][L]["schema"] != OBLIGATION or not rep["lineages"][L]["leaf"]:
        raise Failed("OBLIGATION", f"{a.obligation[:12]} is not an obligation lineage without a fork")
    prev = rep["_recs"][rep["lineages"][L]["leaf"]]["body"]
    body = {"state": "done", "statement": prev["statement"], "answers": prev.get("answers"), "serves": prev.get("serves", []),
            "evidence": sorted(a.evidence), "refs": a.ref, "established": a.established, "residual": a.residual}
    g = dict(rep["_recs"][rep["schemas"][OBLIGATION]]["body"]["states"]["done"], requires=sorted(a.requires))
    return R.record("entity", a.actor, 0, {k: v for k, v in body.items() if v is not None}, OBLIGATION,
                    lineage=rep["lineages"][L]["leaf"], refs=[*a.evidence, *a.requires] + ([body["answers"]] if body["answers"] else [])
                    + body["serves"], guard=g)


def entry():
    """The console script `warrant-roadmap`."""
    return main(run)


if __name__ == "__main__":
    sys.exit(main(run))
