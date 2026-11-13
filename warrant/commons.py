"""The commons: where an agent with no rights says «фе» to any record of the ecosystem.

    python -m warrant_agent.commons init [--store DIR]
    python -m warrant_agent.commons say TARGET "why it is wrong" [--seed FILE] [--store DIR]
    python -m warrant_agent.commons list [--store DIR]

Voice without authority. The agent needs no key any store binds, no role and no part in the record it objects to: its
identity is its own key (`key:<public key>`, docs/V3.md §5): the signature verifies under that key whether or not any
trust binds it, so nobody can sign in its name and it needs nobody's admission. Only a challenge may name its actor
so; it is a thesis like any stranger's until a replayer some reader trusts reproduces it.

The commons store trusts nobody and gives nobody a role: it holds the voices, never a verdict. Every lineage page
shows the challenges filed against it in the commons (and in any other store read) as voices from outside, not counted
by that store's rules; a reader's overlay counts one only when the reader's own rules do (a replay by a replayer the
reader trusts). Nothing here can move a store's verdict, and nothing here can be silenced by the store it objects to.

Limits: the target is one record id (64 hex); the statement is 1..4000 characters; the agent's seed lives in a file of
its own (0600), `~/.config/warrant/commons/NAME.seed`, made on first use; the command line names it, never a path."""
import re
import json
import os
import time
from pathlib import Path

from . import keys as K
from . import records as R
from . import shapes as S
from .store import Store

STATEMENT_MAX = 4000
DEFAULT_STORE = Path.home() / "Projects" / "commons"
SEEDS = Path.home() / ".config" / "warrant" / "commons"      # an agent's seeds live here, one file per name
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
V3 = "v3.json"
DOC = {"warrant": "repository/3", "repository": "s0fractal/commons",
       "trust": {"warrant": "trust/3", "keys": {}}, "profile": {"warrant": "profile/3", "roles": {}}}


class Refused(Exception):
    pass


def is_commons(doc):
    """Whether a store's configuration is a commons: it trusts nobody and gives nobody a role."""
    return (isinstance(doc, dict) and doc.get("warrant") == "repository/3" and isinstance(doc.get("trust"), dict)
            and doc["trust"].get("keys") == {} and isinstance(doc.get("profile"), dict) and doc["profile"].get("roles") == {})


def init(store, repository=None):
    """A commons store at `store` (a directory holding `.warrant/`): trusting nobody, no roles. An existing store is used
    only when it is a commons: a voice is never written into a store that trusts someone (an agent pointing `--store` at
    a project's store is refused, not appended to)."""
    dot = Path(store).resolve() / ".warrant"   # NOSONAR S8707: the agent names its own commons; any other store is refused below
    if (dot / V3).exists():
        try:
            doc = json.loads((dot / V3).read_text())
        except ValueError:
            doc = None
        if not is_commons(doc):
            raise Refused(f"{dot.parent} is no commons: its store trusts someone or gives a role; a voice goes to a commons")
        return dot
    dot.mkdir(parents=True, exist_ok=True)
    doc = dict(DOC, repository=repository) if repository else DOC
    (dot / V3).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    Store(dot).init()
    return dot


def seed(path, store=None):
    """The agent's key from its seed file, made (0600) on first use; refused when the file is a link, or lies inside the
    store it would write to (a seed lives outside every store)."""
    p = Path(path)   # NOSONAR S8707: the agent's own seed file, refused below when it is a link or inside the store
    if p.is_symlink():
        raise Refused(f"{p}: a seed is a regular file, not a link")
    if store is not None and p.resolve().is_relative_to(Path(store).resolve()):
        raise Refused(f"{p}: a seed lives outside the store it writes to")
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # NOSONAR S8707: a name-confined path (seed_named) or the caller's own
        with os.fdopen(fd, "w") as f:
            f.write(K.Key.generate().seed_hex() + "\n")
    return K.Key.from_seed_hex(p.read_text().strip())  # NOSONAR S8707: see above


def seed_named(name, store=None):
    """The agent's key by name: its seed is SEEDS/<name>.seed, nowhere else (the command line names a key, never a
    path, so no argument can point a seed at another file)."""
    if not (isinstance(name, str) and NAME.match(name)):
        raise Refused("a key's name is 1..40 of a-z, 0-9 and '-', starting with a letter or digit")
    return seed(SEEDS / f"{name}.seed", store)


def say(store, target, statement, key, at=None):
    """File the agent's challenge against record `target` in the commons store; its id."""
    if not (isinstance(target, str) and S.hex64(target)):
        raise Refused("the target is one record id: 64 hex characters")
    statement = (statement or "").strip()
    if not 0 < len(statement) <= STATEMENT_MAX:
        raise Refused(f"the statement is 1..{STATEMENT_MAX} characters")
    dot = init(store)
    actor = "key:" + key.public
    record = R.record("challenge", actor, int(time.time()) if at is None else at,
                      {"target": target, "statement": statement}, refs=[target])
    return Store(dot).extend([record], key, DOC["trust"])[0]


def voices(store):
    """[(id, actor, target, statement)] of every challenge in the commons store, in its order."""
    dot = Path(store) / ".warrant"
    if not (dot / "records.jsonl").exists():
        return []
    out = []
    for envs in Store(dot).snapshot().lines.values():
        r = envs[0]["record"]
        if r["kind"] == "challenge":
            out.append((R.rid(r), r["actor"], r["body"].get("target"), r["body"].get("statement", "")))
    return out


