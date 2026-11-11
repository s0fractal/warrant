"""Fragile popularity: where attention went, and where one objection holds against it.

A lineage's attention is how many other actors signed that they saw it, accepted it or reacted to it (its authors
aside; a challenge itself is no attention, a challenger's later acceptance is), here and in the other stores read. A lineage with a challenge filed against one of its
versions is listed with that attention beside the challenge and what became of it: counted by the receiver's rules,
standing, reproduced by a replayer on its own target. One reproduced counterexample outweighs any number of
agreements; the page puts them side by side so the weight is visible, and never adds them up into one score.

The finders: whoever filed a challenge that is reproduced on its own target, or counted and standing, is named with the
attention of what it held against. It is recognition read from the records, not a rank, a reward or a rule: no guard
reads it, and an unreproduced, uncounted objection is shown without being credited. Attention counts only keys some
store's trust binds, so each receiver's numbers are its own."""


def challenges_on(rep, d):
    """[{id, actor, statement, counted, stands, reproduced, version}] of every challenge on a version of `d`."""
    out = []
    for v in d["versions"]:
        for x in v["on"]:
            c = x["challenge"]
            if c is None:
                continue
            r = rep["_recs"].get(x["id"]) or {"actor": x["sentence"][0], "body": {"statement": x["sentence"][3]}}
            out.append({"id": x["id"], "actor": r["actor"], "statement": r["body"].get("statement", ""),
                        "counted": bool(c.get("counted")), "stands": bool(c.get("stands")), "version": v["id"],
                        "reproduced": any(on == c["target"] and verdict == "reproduces" for on, verdict, _ in c["replays"])})
    return out


def credited(ch):
    """Whether a challenge is credited: reproduced on its own target, or counted and standing."""
    return ch["reproduced"] or (ch["counted"] and ch["stands"])


def attention(rep, d, is_view):
    """{"saw", "accepted", "reacted"}: the actors other than its authors who did each, and their union."""
    authors = {v["record"]["actor"] for v in d["versions"]}
    out = {"saw": set(), "accepted": set(), "reacted": set()}
    for v in d["versions"]:
        for x in v["on"]:
            a = x["sentence"][0]
            if a in authors or x["challenge"] is not None:
                continue
            r = rep["_recs"].get(x["id"])
            verdict = (r["body"].get("verdict") if r else None) or ("seen" if is_view(rep, x) else "react")
            key = {"seen": "saw", "accept": "accepted", "react": "reacted"}.get(verdict)
            if key:
                out[key].add(a)
    out["all"] = out["saw"] | out["accepted"] | out["reacted"]
    return out


def rows(serve, reports):
    """[{store, lineage, label, title, attention, challenges}] of every lineage with a challenge, the most attended first."""
    out = []
    for name, rep in sorted(reports.items()):
        if "_error" in rep:
            continue
        for L in sorted(rep["lineages"]):
            d = serve.lineage(rep, L)
            if d is None:
                continue
            elsewhere = serve.reactions_elsewhere(reports, name, d)      # observations and voices from other stores
            for v in d["versions"]:
                v["on"] = sorted(v["on"] + elsewhere.get(v["id"], []), key=lambda x: (x["at"], x["id"]))
            if not any(x["challenge"] is not None for v in d["versions"] for x in v["on"]):
                continue
            out.append({"store": name, "lineage": L, "label": d["label"], "title": d["title"],
                        "attention": attention(rep, d, serve._is_view), "challenges": challenges_on(rep, d)})
    out.sort(key=lambda r: (-len(r["attention"]["all"]), -sum(credited(c) for c in r["challenges"]), r["store"], r["lineage"]))
    return out


def finders(found):
    """[(actor, [(row, how many credited challenges of theirs on it)])] of whoever filed a credited challenge: each
    lineage once, the most attended first, the actors by the attention of what they held against."""
    by = {}
    for r in found:
        for c in r["challenges"]:
            if credited(c):
                mine = by.setdefault(c["actor"], {})
                mine[r["lineage"]] = (r, mine.get(r["lineage"], (r, 0))[1] + 1)
    out = [(a, sorted(m.values(), key=lambda rc: (-len(rc[0]["attention"]["all"]), rc[0]["lineage"]))) for a, m in by.items()]
    return sorted(out, key=lambda am: (-sum(len(r["attention"]["all"]) for r, _ in am[1]), am[0]))
