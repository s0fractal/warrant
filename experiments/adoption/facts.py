"""The one table of facts per task (PLAN.md). Both renderers read it: fixture.notes() writes it as NOTES.md prose
(arm N) and fixture.store() files it as signed records (arms S and A). The self-test holds the two to this table
(fixture.facts_from_notes, fixture.facts_from_store).

A fact is one of:
  claim      {key, id, text, by, on, accepted: [(actor, date)], check: {by, on, at, files} | None}
             a statement filed by `by` on date `on`; each acceptance by an actor on a date; `check`: a program run at
             commit `at` (a name of the task's history: C1, C2) whose acceptance names the files it ran, as they were.
  objection  {key, by, on, against, text, counterexample}: an objection to the claim `against`.
Commit names (C1, C2) are resolved to the fixture's commit ids when rendered: both arms name the same commits.

The receiver's rules are the same in every task (ROLES): whose sign-off counts, whose objection counts. `dev` files
the statements; `intern-bot` holds no role; `claims-checker` is a program that records which bytes a check ran on and
holds no role either (docs: warrant.drift reads only its acceptances to say STALE).
"""

ACTORS = ("dev", "lead", "auditor", "intern-bot", "claims-checker")
SIGN_OFF = ["lead"]              # profile claim/verifier
OBJECTION = ["auditor"]          # profile challenger
ROLES = {"schema/author": ["lead"], "claim/verifier": SIGN_OFF, "challenger": OBJECTION}
REPOSITORY = {"T1": "acme/ledger", "T2": "acme/pipeline", "T3": "acme/migrations"}


def claim(key, cid, text, on, accepted, check=None, by="dev"):
    return {"type": "claim", "key": key, "id": cid, "text": text, "by": by, "on": on,
            "accepted": [list(a) for a in accepted], "check": check}


def objection(key, by, on, against, text, counterexample):
    return {"type": "objection", "key": key, "by": by, "on": on, "against": against, "text": text,
            "counterexample": counterexample}


FACTS = {
    "T1": [
        claim("report-sum", "LED-1", "ledger.report sums the amount column of a CSV and prints the total", "2026-09-28",
              [("lead", "2026-09-29")]),
        claim("amount-thousands", "LED-2", 'parse_amount handles thousands separators ("1,200.50" is 1200.50)',
              "2026-10-02", [("lead", "2026-10-03")],
              check={"by": "claims-checker", "on": "2026-10-03", "at": "C1",
                     "files": ["ledger/amount.py", "tests/test_amount.py"]}),
        claim("csv-utf8", "LED-3", "ledger.report reads the CSV as UTF-8", "2026-10-04", [("lead", "2026-10-05")]),
    ],
    "T2": [
        claim("load-json", "PIP-1", "pipeline.run loads data.json as a list of rows with an id", "2026-09-30",
              [("lead", "2026-10-01")]),
        claim("dedupe-idempotent", "PIP-2", "dedupe() is idempotent: dedupe(dedupe(rows)) == dedupe(rows)",
              "2026-10-02", [("lead", "2026-10-03")]),
        claim("output-sorted", "PIP-3", "pipeline.run writes rows ordered by id", "2026-10-06",
              [("lead", "2026-10-07")]),
        objection("dedupe-case", "auditor", "2026-10-12", "dedupe-idempotent",
                  "dedupe() is not idempotent when ids differ only in case",
                  'rows with ids ["a", "B", "A"]: one pass returns 3 rows, a second pass returns 2'),
        claim("counts-logged", "PIP-4", "pipeline.run prints how many rows it kept", "2026-10-14",
              [("lead", "2026-10-15")]),
    ],
    "T3": [
        claim("idempotent", "MIG-1", "migrate_0042 is idempotent: running up() twice leaves the same schema and data",
              "2026-10-05", [("lead", "2026-10-06")],
              check={"by": "claims-checker", "on": "2026-10-06", "at": "C1",
                     "files": ["migrations/migrate_0042.py", "tests/test_migrate_0042.py"]}),
        claim("rerun", "MIG-2", "migrate_0042 is safe to re-run on prod", "2026-10-05", [("intern-bot", "2026-10-07")]),
        claim("rollback", "MIG-3", "migrate_0042's rollback is tested", "2026-10-05", [("lead", "2026-10-06")],
              check={"by": "claims-checker", "on": "2026-10-06", "at": "C1",
                     "files": ["migrations/rollback.py", "tests/test_rollback.py"]}),
        claim("naming", "MIG-4", "migration files are named migrate_NNNN.py", "2026-09-20", [("lead", "2026-09-21")]),
    ],
}


def canonical(task, commits):
    """The task's facts as a sorted list of tuples, commit names resolved: what each renderer must carry exactly."""
    out = []
    for f in FACTS[task]:
        if f["type"] == "claim":
            out.append(("claim", f["key"], f["text"], f["by"], f["on"]))
            out += [("accept", f["key"], a, d) for a, d in f["accepted"]]
            if f["check"]:
                c = f["check"]
                out.append(("check", f["key"], c["by"], c["on"], commits[c["at"]], tuple(sorted(c["files"]))))
        else:
            out.append(("objection", f["against"], f["by"], f["on"], f["text"], f["counterexample"]))
    out.append(("roles", tuple(SIGN_OFF), tuple(OBJECTION)))
    return sorted(out)
