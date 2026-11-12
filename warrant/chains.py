"""Which of a writer's chain forks the writer itself took in (docs/V3.md §7 lists every fork and excludes none).

A writer that files on two Git branches forks its own chain: each branch chains from the head it had where the
branches parted, and the merge holds both. That is not a writer showing two histories to two readers, but §7
cannot tell the two apart, so every fork reads alike, and a real one is lost among them. A writer takes a branch
in by an attest of its own, on its own line, with body {"verdict": "joined"} and the branch's tip as target.

Taken in by an actor: the records its head reaches through `prev` (§7's head, the same rule as engine.head),
and, for every `joined` attest by that actor among them, the records its target reaches, until nothing is added.
A fork is joined iff every record naming its `prev` is taken in by its actor; otherwise it is open. A joined fork
stays a fork (§7 lists it): this says only that its writer, on the line it continues, named every branch. Nothing
here is read by a guard or the gate."""
from . import records as R

JOINED = "joined"


def _mine(view, actor):
    return {i: r for i, r in view.recs.items() if view.basis[i] == "SIGNED" and r["actor"] == actor}


def tips(view, actor):
    """[(at, id)] of the actor's chained records no other of its records names, oldest first; the last is its head."""
    mine = _mine(view, actor)
    named = {r["prev"] for r in mine.values()}
    chained = {i for i, r in mine.items() if r["prev"] is None or (r["prev"] in mine and mine[r["prev"]]["at"] <= r["at"])}
    return sorted((mine[i]["at"], i) for i in chained if i not in named)


def taken_in(view, actor):
    """The ids the actor's head reaches, through `prev` and through the targets of its own `joined` attests."""
    mine, ts = _mine(view, actor), tips(view, actor)
    seen, todo = set(), [ts[-1][1]] if ts else []
    while todo:
        i = todo.pop()
        while i in mine and i not in seen:
            seen.add(i)
            r = mine[i]
            if r["kind"] == "attest" and r["body"].get("verdict") == JOINED and r["body"].get("target") in mine:
                todo.append(r["body"]["target"])
            i = r["prev"]
    return seen


def forks(view):
    """{"open": [[actor, prev, ids]], "joined": [...]}: §7's forks (engine order), split by whether their writer took
    every branch in."""
    taken, out = {}, {"open": [], "joined": []}
    for f in view.chain_forks:
        a = f[0]
        if a not in taken:
            taken[a] = taken_in(view, a)
        out["joined" if all(i in taken[a] for i in f[2]) else "open"].append(f)
    return out


def loose(view, actor):
    """The actor's tips its head does not take in: what `join` names, oldest first."""
    t = taken_in(view, actor)
    return [i for _, i in tips(view, actor) if i not in t]


def join_records(view, actor):
    """One `joined` attest per loose tip of the actor (records.record dicts, dated and chained by the filer)."""
    return [R.record("attest", actor, 0, {"verdict": JOINED, "target": i}, refs=[i]) for i in loose(view, actor)]
