"""The bridge: a voice from someone who has a GitHub account and nothing else.

    WARRANT_BRIDGE_SEED=... python -m warrant.bridge file --event EVENT.json --store DIR [--reader URL --voices URL]
    WARRANT_BRIDGE_SEED=... python -m warrant.bridge public

Exit status of `file`: 0 filed (or already filed for this issue), 3 refused (the issue is not a voice: the answer for
the issue is in `comment`), 2 the bridge itself cannot file (no seed, a store that is not its own).

`warrant say` (warrant/commons.py) asks its speaker for Python, a key and a repository of their own. The bridge asks
for none of them: an issue opened through this repository's form (.github/ISSUE_TEMPLATE/voice.yml) names one record
id, a stance (objection or support) and a statement, and a workflow (.github/workflows/voice-bridge.yml) files it as
one record in a store of voices of its own, signed by the bridge's key.

What such a record says, and all it says: **the bridge's key states that GitHub delivered an issue with this text, opened
by this account.** It is not the account's signature: whoever holds the bridge's key, or the account, can make one. The
record carries the issue's address and the SHA-256 of its body as delivered, so that anyone can compare it with what
GitHub shows. "Account" means whoever controls it: a person, or an agent acting under a person's login.

The store trusts one name, `github-bridge`, bound to the bridge's key, and gives nobody a role. An objection is a
`challenge`, a support an `attest` with `stance: "support"` and never a `verdict`: no rule of any store counts either,
and a reader who reads the store beside another sees them as voices from outside, not counted. Nothing here can move
a store's verdict. A voice nobody can refuse to carry stays `warrant say` in a repository of one's own: the bridge is
a convenience this repository hosts, and it may stop hosting.

Everything read from the issue is data. The statement is stored, never interpreted, and no text of the issue reaches a
refusal's wording: a refusal names its reason in words written here.

Limits: one record per issue (a second run for the same issue files nothing); the issue as opened, not as edited later;
the body is exactly the form's three fields in order; the statement is 1..4000 characters."""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

from . import keys as K
from . import records as R
from .engine import head
from .store import Refused as StoreRefused
from .store import Store

ACTOR = "github-bridge"
SEED_ENV = "WARRANT_BRIDGE_SEED"
STATEMENT_MAX = 4000
V3 = "v3.json"
STANCES = {"objection": "challenge", "support": "attest"}
# The body an issue form delivers: each field under `### <its label>`, a blank line either side. The statement is the
# last field and takes the rest, so no text in it can pass for another field.
FORM = re.compile(r"### Record\n\n([0-9a-f]{64})\n\n### Stance\n\n(objection|support)\n\n### Statement\n\n(.+)", re.S)
LOGIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\[bot\])?")
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
ACCOUNTS = ("User", "Bot")
NO_RESPONSE = "_No response_"      # what a form delivers for a field left empty


class Refused(Exception):
    """The issue is not a voice the bridge files; the reason is answered on the issue."""


class Broken(Exception):
    """The bridge itself cannot file (its seed, its store): an error of the run, never answered on the issue."""


def _positive(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 < v < 2 ** 53


def voice(event):
    """(kind, body) of the one record an `issues: opened` event becomes, or Refused with a reason written here. The
    issue's address is built from the repository's name and the issue's number, never copied from the event."""
    if not (isinstance(event, dict) and event.get("action") == "opened"):
        raise Refused("the bridge files an issue when it is opened, and nothing else")
    issue, repo = event.get("issue"), event.get("repository")
    if not isinstance(issue, dict) or "pull_request" in issue:
        raise Refused("the event carries no issue")
    full = repo.get("full_name") if isinstance(repo, dict) else None
    if not (isinstance(full, str) and REPOSITORY.fullmatch(full) and _positive(issue.get("number"))):
        raise Refused("the event names no repository and issue number")
    user = issue.get("user")
    if not (isinstance(user, dict) and isinstance(user.get("login"), str) and LOGIN.fullmatch(user["login"])
            and _positive(user.get("id")) and user.get("type") in ACCOUNTS):
        raise Refused("the issue's author is not a GitHub account with a login and an id")
    raw = issue.get("body")
    if not isinstance(raw, str):
        raise Refused("the issue has no body")
    m = FORM.fullmatch(raw.replace("\r\n", "\n").strip())
    if m is None:
        raise Refused("the issue's body is not the form's three fields in order: a record id of 64 lowercase hex "
                      "digits, a stance (objection or support) and a statement")
    target, stance, statement = m.group(1), m.group(2), m.group(3).strip()
    if not 0 < len(statement) <= STATEMENT_MAX or statement == NO_RESPONSE:
        raise Refused(f"the statement is 1..{STATEMENT_MAX} characters")
    github = {"login": user["login"], "id": user["id"], "account": user["type"], "repository": full,
              "issue": issue["number"], "url": f"https://github.com/{full}/issues/{issue['number']}",
              "body_sha256": hashlib.sha256(raw.encode()).hexdigest()}
    return STANCES[stance], {"target": target, "stance": stance, "statement": statement, "github": github}


def doc_for(public):
    """The configuration of a bridge's store: one name bound to one key, no roles."""
    return {"warrant": "repository/3", "repository": "voices/github-bridge",
            "trust": {"warrant": "trust/3", "keys": {ACTOR: [public]}}, "profile": {"warrant": "profile/3", "roles": {}}}


def is_bridge_store(doc, public):
    """Whether a store's configuration is this bridge's: it trusts the one name, bound to this key among its keys, and
    gives nobody a role."""
    if not (isinstance(doc, dict) and doc.get("warrant") == "repository/3" and isinstance(doc.get("trust"), dict)
            and isinstance(doc.get("profile"), dict) and doc["profile"].get("roles") == {}):
        return False
    keys = doc["trust"].get("keys")
    return isinstance(keys, dict) and set(keys) == {ACTOR} and isinstance(keys[ACTOR], list) and public in keys[ACTOR]


def init(store, key):
    """The bridge's store at `store` (a directory holding `.warrant/`), made when absent. An existing store is used
    only when it is this bridge's: a voice is never written into a store that trusts anyone else or gives a role."""
    dot = Path(store).resolve() / ".warrant"   # NOSONAR S8707: the workflow names its own checkout of the voices branch; any other store is refused below
    if (dot / V3).exists():
        try:
            doc = json.loads((dot / V3).read_text())
        except ValueError:
            doc = None
        if not is_bridge_store(doc, key.public):
            raise Broken("the store is not this bridge's: its trust is not the one name github-bridge bound to this "
                         "key, or it gives a role")
        return dot, doc
    dot.mkdir(parents=True, exist_ok=True)
    doc = doc_for(key.public)
    (dot / V3).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    Store(dot).init()
    return dot, doc


def filed_for(dot, repository, number):
    """The id of the record the store already holds for this issue, or None."""
    for rid, envs in Store(dot).snapshot().lines.items():
        r = envs[0]["record"]
        g = r["body"].get("github") if r["actor"] == ACTOR and isinstance(r["body"], dict) else None
        if isinstance(g, dict) and g.get("repository") == repository and g.get("issue") == number:
            return rid
    return None


def file(store, event, key, at=None):
    """File the event's voice in the bridge's store: {"filed": id, "kind", "target", "stance", "already"}. A second
    call for the same issue files nothing and answers with the first record."""
    kind, body = voice(event)
    dot, doc = init(store, key)
    g = body["github"]
    had = filed_for(dot, g["repository"], g["issue"])
    out = {"kind": kind, "target": body["target"], "stance": body["stance"]}
    if had is not None:
        return dict(out, filed=had, already=True)
    if at is None:                  # a runner's clock behind the chain's last record must not stop the next voice
        at = max(int(time.time()), head(Store(dot).snapshot(), doc["trust"], ACTOR)["at"] or 0)
    try:
        record = R.record(kind, ACTOR, at, body, refs=[body["target"]])
    except R.Invalid:
        raise Refused("the statement does not fit a record's body") from None
    try:
        return dict(out, filed=Store(dot).extend([record], key, doc["trust"])[0], already=False)
    except StoreRefused as e:
        raise Broken(f"the store did not take the record: {e}") from None


def comment(result=None, why=None, reader=None, voices=None):
    """What the bridge answers on the issue: the record's id and where to read it, or why nothing was filed. Built from
    ids and words written here; no text of the issue is repeated."""
    if why is not None:
        return (f"Nothing was filed: {why}.\n\nThe form asks for a record id (64 lowercase hex digits, as the reader "
                "shows it), a stance and a statement. Open a new issue through the form to try again; an edit of this "
                "one is not read.")
    stance = "an objection" if result["stance"] == "objection" else "a support"
    where = (f"\n\nTo see it, read the bridge's store beside the store that holds the record: {reader}?with={quote(voices, safe='')} "
             "reads it beside this repository's own store; the voice is listed on the record's lineage." if reader and voices else "")
    again = " (filed when this issue was opened; nothing was filed now)" if result["already"] else ""
    return (f"Filed as record `{result['filed']}`{again}: {stance} on `{result['target']}`.\n\n"
            "It is a voice from outside. The bridge's key states that GitHub delivered this issue, opened by this "
            "account; it is not the account's signature, and no rule of any store counts it. Later edits of this issue "
            f"are not read.{where}")


def _key():
    seed = os.environ.get(SEED_ENV, "").strip()
    if not seed:
        raise Broken(f"no {SEED_ENV} in the environment")
    return K.Key.from_seed_hex(seed)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m warrant.bridge", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("file", help="file the voice of one `issues: opened` event")
    f.add_argument("--event", required=True, help="the event's JSON file (GITHUB_EVENT_PATH)")
    f.add_argument("--store", required=True, help="the directory holding the bridge's store (.warrant/)")
    f.add_argument("--reader", help="the reader's address, for the answer on the issue (with --voices)")
    f.add_argument("--voices", help="the address the bridge's store is published at, for the answer on the issue")
    sub.add_parser("public", help="the bridge's public key")
    a = ap.parse_args(argv)
    try:
        key = _key()
    except Broken as e:
        print(json.dumps({"error": str(e)}, sort_keys=True))
        return 2
    if a.cmd == "public":
        print(key.public)
        return 0
    try:
        event = json.loads(Path(a.event).read_text())   # NOSONAR S8707: the runner's own event file
    except (OSError, ValueError):
        print(json.dumps({"error": "the event file is not readable JSON"}, sort_keys=True))
        return 2
    try:
        out = file(a.store, event, key)
    except Refused as e:
        print(json.dumps({"refused": str(e), "comment": comment(why=str(e))}, sort_keys=True))
        return 3
    except Broken as e:
        print(json.dumps({"error": str(e)}, sort_keys=True))
        return 2
    print(json.dumps(dict(out, comment=comment(out, reader=a.reader, voices=a.voices)), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
