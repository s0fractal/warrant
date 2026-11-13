"""The board: a roadmap's goals and obligations as rows of a public project board (GitHub Projects), one way.

The records stay the source; the board decides nothing. Each row is one lineage (a goal@1 or an obligation@1) as its
store's own assessment reads it, under that store's own trust and profile, and the board carries the identity of what
it was drawn from (each store's snapshot and assessment). A hand edit on the board is no record: the next sync puts
the row back and counts it.

    python3 -m warrant.board manifest [--root DIR ...] [--reader URL]            # the rows, canonical JSON; no network
    python3 -m warrant.board plan --owner LOGIN --project N [--root DIR ...]     # what a sync would change; changes nothing
    python3 -m warrant.board sync --owner LOGIN --project N [--root DIR ...]     # make the board the manifest

`manifest` is a pure function of the stores: the same stores give the same bytes, with no clock in them. `plan` and
`sync` talk to GitHub through the `gh` command of whoever runs them (a token with the `project` scope); this module
handles no token. The date of a sync is the caller's (`--today`, else today's, UTC) and is on the board, not in the
manifest.

Two words the board keeps apart, because one green "Done" would hide the difference:
    Claimed, not accepted   the item's author filed its closing version; nobody the profile counts has accepted it
    Accepted                that version's guard is met: an actor holding the role accepted exactly it
Neither says "verified": a roadmap item has no checker of its own. What a program verified at a commit is a claim's
acceptance (docs/V3.md §15), and claims are not on this board. Nor does a row say whether what it rests on holds:
warrant.graph.grounded reads an obligation's `answers` as a ground, so a met goal that cites its obligations reads as
a cycle with each of them (every such item of minds, 2026-11-13), and a column of that would mislead.

What a record says is data. In a row's body it lies inside a code fence longer than any run of backticks in it, so
the board's renderer mentions nobody, links nothing and draws no markup from it; its lines are wrapped for reading and
are otherwise the record's. The exact bytes are the record's, behind the row's link."""
import argparse
import datetime
import json
import re
import subprocess
import sys
import textwrap
import urllib.parse
from pathlib import Path

from . import jcs as C
from .repo import Failed, Repo, dump, main

GOAL, OBLIGATION = "goal@1", "obligation@1"
KIND = {GOAL: "Goal", OBLIGATION: "Obligation"}
OPEN, CLAIMED, ACCEPTED, RELEASED, WITHDRAWN, CHALLENGED, FORKED, OTHER = (
    "Open", "Claimed, not accepted", "Accepted", "Released", "Withdrawn", "Challenged", "Forked", "Other")
STATUSES = (OPEN, CLAIMED, ACCEPTED, RELEASED, WITHDRAWN, CHALLENGED, FORKED, OTHER)
BY_STATE = {"open": OPEN, "done": ACCEPTED, "met": ACCEPTED, "released": RELEASED, "withdrawn": WITHDRAWN}
COLOR = {OPEN: "GRAY", CLAIMED: "YELLOW", ACCEPTED: "GREEN", RELEASED: "PURPLE", WITHDRAWN: "PURPLE", CHALLENGED: "RED",
         FORKED: "RED", OTHER: "GRAY"}
TITLE_MAX, WRAP = 200, 96
ZWSP = "\u200b"
PR_REF = re.compile(r"([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+)#([0-9]+)\Z")
# (field name, data type, the row member it shows); ID is the key a row is found by on the board
ID, SYNCED = "Warrant ID", "Last sync"
FIELDS = [("Warrant status", "SINGLE_SELECT", "status"), ("Kind", "TEXT", "kind"), ("Repository", "TEXT", "repository"),
          ("Goal", "TEXT", "goal"), ("Filed by", "TEXT", "filed_by"), ("Accepted by", "TEXT", "accepted_by"),
          ("Waits for", "TEXT", "waits_for"), ("Standing challenges", "NUMBER", "challenges"), ("Reliance", "TEXT", "reliance"),
          ("Assessment", "TEXT", "assessment"), (ID, "TEXT", "id")]


def status(rep, lin):
    """The one word a board column shows, from the lineage's verdict, its standing challenges and its versions."""
    if lin["verdict"] == "FORK":
        return FORKED
    at = [v for v in (lin["effective"], lin["leaf"]) if v]
    if any(rep["versions"][v]["challenged_by"] for v in at):
        return CHALLENGED
    if lin["leaf"] != lin["effective"] and rep["versions"][lin["leaf"]]["guard"] == "PENDING":
        return CLAIMED                                  # a later version waits for an acceptor: said, not accepted
    return BY_STATE.get(lin["state"], OTHER)


def one_line(text):
    """A row's title: the text on one line, cut at TITLE_MAX, with no `@` that a renderer could read as a mention."""
    t = " ".join(str(text).split()).replace("@", "@" + ZWSP)
    return t if len(t) <= TITLE_MAX else t[:TITLE_MAX - 1].rstrip() + "…"


def fenced(text):
    """`text` as data in Markdown: wrapped for reading, inside a fence longer than any run of backticks it holds."""
    runs = re.findall(r"`+", text)
    fence = "`" * max(3, 1 + max((len(r) for r in runs), default=0))
    lines = [w for line in str(text).splitlines() or [""]
             for w in (textwrap.wrap(line, WRAP, break_long_words=False, break_on_hyphens=False) or [""])]
    return "\n".join([fence + "text", *lines, fence])


def _links(refs):
    """A pull request reference of the exact shape owner/name#N as a link; any other string stays record text."""
    out = []
    for r in refs:
        m = PR_REF.match(r) if isinstance(r, str) else None
        if m:
            out.append(f"- https://github.com/{m.group(1)}/{m.group(2)}/pull/{m.group(3)}")
    return out


def body(row, rec, leaf, reader):
    """A row's body in Markdown: what the board cannot say in a column, the record's text as data, and its links."""
    b, lb = rec["body"], leaf["body"]
    parts = [f"**{row['kind']} of {row['repository']}** · state `{row['state'] or 'none'}` · reliance `{row['reliance']}`"
             f" · status **{row['status']}**", "",
             "A projection of signed records (Warrant 3). This row decides nothing: its state is the store's own "
             "assessment under the store's own trust and profile, and an edit made here is undone by the next sync.", "",
             "Statement, as recorded:", "", fenced(b.get("statement") or b.get("text") or "")]
    for name, member in (("Established", "established"), ("Left open", "residual")):
        if lb.get(member):
            parts += ["", f"{name}, as recorded in its latest version:", "", fenced("\n".join(f"- {x}" for x in lb[member]))]
    if row["waits_for"]:
        parts += ["", "Waits for:", "", fenced(row["waits_for"])]
    links = _links(lb.get("refs") or [])
    if reader and row["base"]:
        links.insert(0, f"- [Read and assess this lineage yourself]({reader}?base={urllib.parse.quote(row['base'], safe='')}&l={row['id']})")
    if links:
        parts += ["", "Links:", "", *links]
    other = [r for r in (lb.get("refs") or []) if not (isinstance(r, str) and PR_REF.match(r))]
    if other:
        parts += ["", "Other references, as recorded:", "", fenced("\n".join(str(x) for x in other))]
    parts += ["", f"Lineage `{row['id']}` · version shown `{row['version']}` · assessment `{row['assessment']}`"]
    return "\n".join(parts) + "\n"


def rows(rep, repository, base=None, reader=None):
    """One row per goal and obligation lineage of one assessed store, in the order of their ids."""
    recs = rep["_recs"]
    key_of = {v: recs[L]["body"].get("key", "") for L, lin in rep["lineages"].items() if lin["schema"] == GOAL for v in lin["versions"]}
    out = []
    for L, lin in sorted(rep["lineages"].items()):
        if lin["schema"] not in KIND:
            continue
        shown = lin["effective"] or lin["leaf"] or L
        rec, leaf = recs[shown], recs[lin["leaf"] or shown]
        b = rec["body"]
        row = {"id": L, "repository": repository, "kind": KIND[lin["schema"]],
               "goal": b.get("key") or key_of.get(leaf["body"].get("answers"), ""),
               "title": one_line(b.get("statement") or b.get("text") or ""), "status": status(rep, lin),
               "state": lin["state"], "reliance": lin["reliance"], "filed_by": lin["actor"],
               "accepted_by": ", ".join(rep["versions"][lin["effective"]]["accepted_by"]) if lin["effective"] else "",
               "waits_for": "; ".join(rep["versions"][lin["leaf"]]["waiting"]) if lin["leaf"] else "",
               "challenges": sum(len(rep["versions"][v]["challenged_by"]) for v in lin["versions"]),
               "version": shown, "assessment": rep["assessment"][:12], "base": base or ""}
        row["body"] = body(row, rec, leaf, reader)
        out.append(row)
    return out


def manifest(roots, reader=None):
    """{warrant: board/1, stores, rows, digest}: every root's roadmap rows and the identity of what they were read from."""
    stores, out = [], []
    for root in roots:
        repo = Repo(root)
        _, _, name = repo.config()
        rep = repo.report()
        merge = Path(repo.root) / ".warrant" / "merge.json"
        branch = json.loads(merge.read_text()).get("base") if merge.is_file() else None
        base = f"https://raw.githubusercontent.com/{name}/{branch}/" if name and isinstance(branch, str) else None
        stores.append({"repository": name or "", "snapshot": rep["snapshot"], "assessment": rep["assessment"],
                       "trust": rep["trust"], "profile": rep["profile"], "completeness": rep["completeness"]})
        out += rows(rep, name or "", base, reader)
    doc = {"warrant": "board/1", "stores": sorted(stores, key=lambda s: s["repository"]),
           "rows": sorted(out, key=lambda r: (r["repository"], r["id"]))}
    return dict(doc, digest=C.doc_id(doc))


def readme(man, today):
    stores = "\n".join(f"| `{s['repository']}` | `{s['snapshot'][:12]}` | `{s['assessment'][:12]}` | {s['completeness']} |"
                       for s in man["stores"])
    return ("This board is a one-way projection of signed records (Warrant 3). It decides nothing.\n\n"
            "- Each row is one goal or obligation, as its repository's own records read under that repository's own "
            "trust and profile. Another reader, with other rules, gets another answer from the same bytes.\n"
            "- **Claimed, not accepted**: the author says it is done. **Accepted**: an actor holding the role accepted "
            "exactly that version. Neither says verified, and the two are never one \"Done\".\n"
            "- An edit made on this board is no record; the next sync puts the row back.\n"
            "- Completeness is UNATTESTED: an objection held in a store this board does not read is not shown.\n\n"
            f"Synced {today} from manifest `{man['digest'][:12]}`:\n\n| store | snapshot | assessment | completeness |\n"
            f"| --- | --- | --- | --- |\n{stores}\n")


# ---------------------------------------------------------------- the board's side (GitHub Projects, through `gh`)

def gh(query, variables):
    """One GraphQL call through the caller's `gh`; its `data`, or a refusal with GitHub's words."""
    p = subprocess.run(["gh", "api", "graphql", "--input", "-"], input=json.dumps({"query": query, "variables": variables}),
                       capture_output=True, text=True, check=False)
    try:
        out = json.loads(p.stdout)
    except ValueError:
        raise Failed("GITHUB", (p.stderr or p.stdout).strip()[:400] or "gh answered nothing") from None
    if p.returncode != 0 or out.get("errors"):
        raise Failed("GITHUB", "; ".join(e.get("message", "") for e in out.get("errors", [])) or p.stderr.strip()[:400])
    return out["data"]


# A project belongs to an organization or to a user; the same selection under either root (OWNER is replaced).
PROJECT = """query($owner: String!, $number: Int!, $after: String) { OWNER(login: $owner) { projectV2(number: $number) {
  id title public
  fields(first: 100) { nodes { ... on ProjectV2FieldCommon { id name dataType }
                               ... on ProjectV2SingleSelectField { options { id name } } } }
  items(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { id isArchived
    content { ... on DraftIssue { id title body } }
    fieldValues(first: 50) { nodes {
      ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
      ... on ProjectV2ItemFieldNumberValue { number field { ... on ProjectV2FieldCommon { name } } }
      ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
      ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } } } } } } } } }"""
OWNERS = ("organization", "user")
ADD_FIELD = """mutation($project: ID!, $name: String!, $type: ProjectV2CustomFieldType!, $options: [ProjectV2SingleSelectFieldOptionInput!]) {
  createProjectV2Field(input: {projectId: $project, name: $name, dataType: $type, singleSelectOptions: $options}) {
    projectV2Field { ... on ProjectV2FieldCommon { id name dataType } ... on ProjectV2SingleSelectField { options { id name } } } } }"""
ADD_ITEM = """mutation($project: ID!, $title: String!, $body: String!) { addProjectV2DraftIssue(input: {projectId: $project, title: $title, body: $body}) {
  projectItem { id content { ... on DraftIssue { id } } } } }"""
SET_TEXT = """mutation($draft: ID!, $title: String!, $body: String!) { updateProjectV2DraftIssue(input: {draftIssueId: $draft, title: $title, body: $body}) {
  draftIssue { id } } }"""
SET_FIELD = """mutation($project: ID!, $item: ID!, $field: ID!, $value: ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field, value: $value}) { projectV2Item { id } } }"""
CLEAR = """mutation($project: ID!, $item: ID!, $field: ID!) {
  clearProjectV2ItemFieldValue(input: {projectId: $project, itemId: $item, fieldId: $field}) { projectV2Item { id } } }"""
ARCHIVE = """mutation($project: ID!, $item: ID!) { archiveProjectV2Item(input: {projectId: $project, itemId: $item}) { item { id } } }"""
DESCRIBE = """mutation($project: ID!, $readme: String!, $short: String!) { updateProjectV2(input: {projectId: $project, readme: $readme, shortDescription: $short}) {
  projectV2 { id } } }"""


def read_board(call, owner, number):
    """{id, fields: {name: field}, items: [{item, draft, title, body, archived, values: {field name: value}}]}."""
    after, items, proj, kind = None, [], None, None
    while True:
        for k in ([kind] if kind else OWNERS):          # an organization's first: a token bound to one organization reads no user
            try:
                proj = (call(PROJECT.replace("OWNER", k), {"owner": owner, "number": number, "after": after}).get(k) or {}).get("projectV2")
            except Failed:
                proj = None                             # GitHub answers a login of the other kind with an error, not with null
            if proj:
                kind = k
                break
        if not proj:
            raise Failed("PROJECT", f"no project {number} of {owner} (an organization or a user) that this token can read")
        for n in proj["items"]["nodes"]:
            values = {}
            for v in n["fieldValues"]["nodes"]:
                name = (v.get("field") or {}).get("name")
                if name:
                    values[name] = next((v[k] for k in ("text", "number", "date", "name") if k in v), None)
            c = n.get("content") or {}
            items.append({"item": n["id"], "draft": c.get("id"), "title": c.get("title"), "body": c.get("body"),
                          "archived": n["isArchived"], "values": values})
        if not proj["items"]["pageInfo"]["hasNextPage"]:
            break
        after = proj["items"]["pageInfo"]["endCursor"]
    return {"id": proj["id"], "fields": {f["name"]: f for f in proj["fields"]["nodes"] if f.get("name")}, "items": items}


def _same(dtype, on_board, wanted):
    """Whether a board cell shows a row member: an empty cell is the empty text and the number 0."""
    if dtype == "NUMBER":
        return float(on_board or 0) == float(wanted or 0)
    return (on_board or "") == (wanted or "")


def plan(man, board, today):
    """What a sync would do, and nothing done: the fields to add, the rows to create, the members of each present row
    that differ (a hand edit among them), the rows to archive (ours, no longer in the manifest) and the items that are
    not ours (no Warrant ID: left alone)."""
    missing = [name for name, _, _ in FIELDS if name not in board["fields"]] + ([] if SYNCED in board["fields"] else [SYNCED])
    ours = {i["values"].get(ID): i for i in board["items"] if i["values"].get(ID) and not i["archived"]}
    want = {r["id"]: r for r in man["rows"]}
    update = {}
    for rid, row in want.items():
        item = ours.get(rid)
        if item is None:
            continue
        diff = [m for m in ("title", "body") if item[m] != row[m]]
        diff += [name for name, dtype, member in FIELDS if not _same(dtype, item["values"].get(name), row[member])]
        if diff:
            update[rid] = diff
    return {"fields": missing, "create": sorted(set(want) - set(ours)), "update": update,
            "archive": sorted(set(ours) - set(want)),
            "foreign": sum(1 for i in board["items"] if not i["values"].get(ID)), "today": today, "manifest": man["digest"]}


def _value(field, member, row):
    v = row[member]
    if field["dataType"] == "SINGLE_SELECT":
        opt = next((o["id"] for o in field.get("options", []) if o["name"] == v), None)
        if opt is None:
            raise Failed("FIELD", f"the board's field {field['name']!r} has no option {v!r}")
        return {"singleSelectOptionId": opt}
    return {"number": float(v)} if field["dataType"] == "NUMBER" else {"text": str(v)}


def sync(man, board, call, today):
    """Make the board the manifest: what plan() names, done. The plan it executed, with what it changed."""
    todo = plan(man, board, today)
    for name in todo["fields"]:
        kind = next((t for n, t, _ in FIELDS if n == name), "DATE")
        options = [{"name": s, "color": COLOR[s], "description": ""} for s in STATUSES] if kind == "SINGLE_SELECT" else None
        f = call(ADD_FIELD, {"project": board["id"], "name": name, "type": kind, "options": options})["createProjectV2Field"]["projectV2Field"]
        board["fields"][f["name"]] = f
    want = {r["id"]: r for r in man["rows"]}
    ours = {i["values"].get(ID): i for i in board["items"] if i["values"].get(ID) and not i["archived"]}
    for rid in todo["create"]:
        row = want[rid]
        made = call(ADD_ITEM, {"project": board["id"], "title": row["title"], "body": row["body"]})["addProjectV2DraftIssue"]["projectItem"]
        ours[rid] = {"item": made["id"], "draft": made["content"]["id"], "title": row["title"], "body": row["body"], "values": {}}
        todo["update"][rid] = [name for name, _, _ in FIELDS]
    for rid, diff in sorted(todo["update"].items()):
        row, item = want[rid], ours[rid]
        if "title" in diff or "body" in diff:
            call(SET_TEXT, {"draft": item["draft"], "title": row["title"], "body": row["body"]})
        for name, dtype, member in FIELDS:
            if name not in diff or (rid in todo["create"] and _same(dtype, None, row[member])):
                continue                                # a new row's empty cells are empty already
            where = {"project": board["id"], "item": item["item"], "field": board["fields"][name]["id"]}
            if dtype == "TEXT" and row[member] == "":
                call(CLEAR, where)                      # an empty text is no value: the cell is cleared, not set to ""
            else:
                call(SET_FIELD, dict(where, value=_value(board["fields"][name], member, row)))
        call(SET_FIELD, {"project": board["id"], "item": item["item"], "field": board["fields"][SYNCED]["id"], "value": {"date": today}})
    for rid in todo["archive"]:
        call(ARCHIVE, {"project": board["id"], "item": ours[rid]["item"]})
    if todo["create"] or todo["update"] or todo["archive"] or todo["fields"]:
        call(DESCRIBE, {"project": board["id"], "readme": readme(man, today),
                        "short": f"A projection of signed records (Warrant 3); it decides nothing. Manifest {man['digest'][:12]}, synced {today}."})
    return todo


def run(argv=None):
    ap = argparse.ArgumentParser(prog="warrant.board")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("manifest", "plan", "sync"):
        p = sub.add_parser(name)
        p.add_argument("--root", action="append", default=[])
        p.add_argument("--reader", help="the address of a reader page (site/reader.html) for each row's link")
        if name != "manifest":
            p.add_argument("--owner", required=True)
            p.add_argument("--project", type=int, required=True)
            p.add_argument("--today", help="the date a sync writes (YYYY-MM-DD); today's, UTC, when absent")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    man = manifest(a.root or [None], a.reader)
    if a.cmd == "manifest":
        dump(man)
        return 0
    today = a.today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    board = read_board(gh, a.owner, a.project)
    dump(plan(man, board, today) if a.cmd == "plan" else sync(man, board, gh, today))
    return 0


if __name__ == "__main__":
    sys.exit(main(run))
