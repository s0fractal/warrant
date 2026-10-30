"""Warrant Home: the operator's one configuration for the repositories on this machine (docs/HOME.md).

    {"warrant": "warrant-home/1",
     "identities": {ACTOR: {"seed": FILE, "public": HEX64}},
     "repositories": {NAME: {"path": DIR, "signer": ACTOR?, "operations": [OP, ...]?}}}

The file is the operator's: $WARRANT_HOME, else $XDG_CONFIG_HOME/warrant/home.json, else
~/.config/warrant/home.json. It is never read from a repository, and no request names it. Each repository keeps its
own `.warrant/` (its records, its blobs and its receiver configuration v3.json): Home lists where they are and who
signs in each, and writes nothing into any of them. A seed is named, never copied, and never lies inside a
registered repository; Home reads one only to derive its public key when the operator registers the identity."""
import json
import os
import re
from pathlib import Path

from . import keys as K
from . import shapes as S
from .store import Refused, confined, dot_of, read_inside

FORMAT = "warrant-home/1"
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")        # a repository's handle, as the agent interface's workspaces
OPERATIONS = ("context", "read", "graph", "handoff", "prepare", "commit")   # warrant_agent's, which it checks again
RECEIVER = "repository/3"


def path():
    """Where this operator's Home is: $WARRANT_HOME, else $XDG_CONFIG_HOME/warrant/home.json, else
    ~/.config/warrant/home.json."""
    if os.environ.get("WARRANT_HOME"):
        return Path(os.environ["WARRANT_HOME"]).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "warrant" / "home.json"


def empty():
    return {"warrant": FORMAT, "identities": {}, "repositories": {}}


def problem(doc):
    """Why `doc` is not a Home, or None."""
    if not (isinstance(doc, dict) and set(doc) == {"warrant", "identities", "repositories"} and doc["warrant"] == FORMAT):
        return f"a Home is {{warrant: {FORMAT}, identities, repositories}}"
    ids, repos = doc["identities"], doc["repositories"]
    if not (isinstance(ids, dict) and isinstance(repos, dict)):
        return "identities and repositories are objects"
    for actor, i in ids.items():
        if not (S.is_actor(actor) and isinstance(i, dict) and set(i) == {"seed", "public"} and isinstance(i["seed"], str)
                and S.hex_of(i["public"], 64)):
            return f"identity {actor!r} is {{seed: FILE, public: HEX64}} under an actor id"
    for name, r in repos.items():
        if not (isinstance(name, str) and NAME.match(name) and isinstance(r, dict) and isinstance(r.get("path"), str)
                and set(r) <= {"path", "signer", "operations"}):
            return f"repository {name!r} is {{path, signer?, operations?}} under a plain name"
        if "signer" in r and r["signer"] not in ids:
            return f"repository {name!r}: its signer {r['signer']!r} is no identity of this Home"
        ops = r.get("operations", list(OPERATIONS))
        if not (isinstance(ops, list) and set(ops) <= set(OPERATIONS) and len(set(ops)) == len(ops)):
            return f"repository {name!r}: operations are of {list(OPERATIONS)}"
    paths = [os.path.realpath(os.path.expanduser(r["path"])) for r in repos.values()]
    if len(set(paths)) != len(paths):
        return "two repositories name one directory"
    for actor, i in ids.items():
        inside = _inside_any(i["seed"], paths)
        if inside:
            return f"identity {actor!r}: its seed lies inside the registered repository {inside}"
    return None


def _inside_any(seed, repo_paths):
    s = os.path.realpath(os.path.expanduser(seed))
    return next((p for p in repo_paths if s == p or s.startswith(p + os.sep)), None)


def load(p=None):
    """The Home at `p` (path()), checked; an empty Home when there is no file. A link, or a file other users may
    write, is refused: the configuration that says who signs where is the operator's alone."""
    p = Path(p) if p is not None else path()
    if not os.path.lexists(p):
        return empty()
    if p.is_symlink() or not p.is_file():
        raise Refused(f"{p}: a Home is a regular file, not a link")
    if p.stat().st_mode & 0o022:
        raise Refused(f"{p}: other users may write it (chmod 600)")
    doc = json.loads(p.read_text())
    why = problem(doc)
    if why:
        raise Refused(f"{p}: {why}")
    return doc


def save(doc, p=None):
    """Write the Home whole, 0600, its directory 0700; never through a link."""
    why = problem(doc)
    if why:
        raise Refused(why)
    p = Path(p) if p is not None else path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if p.is_symlink():
        raise Refused(f"{p}: a Home is a regular file, not a link")
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, p)
    return p


def update(change, p=None):
    """Apply `change` (a function from a Home to a Home) to the Home at `p` (path()) and save the result, under an
    exclusive lock on `<home>.lock` held from the read to the write: two changes made at once both take effect, in
    some order, and neither saves a document read before the other's write (Codex finding 773e7e02f857). The
    saved Home."""
    import fcntl
    p = Path(p) if p is not None else path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(p.with_name(p.name + ".lock"), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        doc = change(load(p))
        save(doc, p)
        return doc
    finally:
        os.close(fd)                                    # closing the descriptor releases the lock


def receiver(repo_path):
    """(trust, profile, repository name) of a repository directory: its .warrant/v3.json."""
    dot = dot_of(repo_path)
    doc = json.loads(read_inside(dot / "v3.json", dot))         # never through a link out of the store (d6127c0fd71d)
    if not (isinstance(doc, dict) and doc.get("warrant") == RECEIVER and isinstance(doc.get("trust"), dict)
            and isinstance(doc.get("profile"), dict)):
        raise Refused(f"{repo_path}/.warrant/v3.json is not a {RECEIVER} document")
    return doc["trust"], doc["profile"], doc.get("repository")


def add_repository(doc, repo_path, name=None, signer=None, operations=None):
    """`doc` with the repository at `repo_path` registered: a directory holding .warrant/v3.json, under `name` (its
    directory's name by default) and with `signer`, an identity of this Home."""
    real = os.path.realpath(os.path.expanduser(repo_path))
    receiver(real)
    name = name or re.sub(r"[^a-z0-9_.-]", "-", os.path.basename(real).lower()).lstrip("-_.")
    if name in doc["repositories"]:
        raise Refused(f"a repository is registered as {name!r}")
    entry = {"path": real}
    if signer is not None:
        entry["signer"] = signer
    if operations is not None:
        entry["operations"] = list(operations)
    out = dict(doc, repositories=dict(doc["repositories"], **{name: entry}))
    why = problem(out)
    if why:
        raise Refused(why)
    return out


def add_identity(doc, actor, seed):
    """`doc` with `actor`'s identity: the seed's path (absolute, read once here for its public key) and that key. The
    seed must be the operator's alone (no permission for others) and outside every registered repository."""
    real = os.path.realpath(os.path.expanduser(seed))
    if os.stat(real).st_mode & 0o077:
        raise Refused(f"{seed}: others may read or write it (chmod 600)")
    public = K.Key.from_seed_hex(Path(real).read_text().strip()).public
    out = dict(doc, identities=dict(doc["identities"], **{actor: {"seed": real, "public": public}}))
    why = problem(out)
    if why:
        raise Refused(why)
    return out


def remove(doc, name):
    if name not in doc["repositories"]:
        raise Refused(f"no repository is registered as {name!r}")
    return dict(doc, repositories={k: v for k, v in doc["repositories"].items() if k != name})


def store_of(doc, name):
    """The `.warrant/` directory of the registered repository `name`, confined by real path to that repository: a
    `.warrant` link out of it is refused (as warrant.cli confines a store it finds; Codex finding 24b91d75f065)."""
    if name not in doc["repositories"]:
        raise Refused(f"no repository is registered as {name!r} (warrant home add DIR)")
    root = os.path.expanduser(doc["repositories"][name]["path"])
    return confined(os.path.join(root, ".warrant"), root)


def listing(doc):
    """One row per registered repository: where it is, the repository its v3.json names, how many record lines its
    store holds, and its signer with whether that repository's trust binds the identity's key to it."""
    rows = []
    for name, r in sorted(doc["repositories"].items()):
        p = os.path.expanduser(r["path"])
        row = {"name": name, "path": p, "signer": r.get("signer"), "operations": r.get("operations", list(OPERATIONS))}
        try:
            trust, _, repository = receiver(p)
            f = dot_of(p) / "records.jsonl"
            row.update(repository=repository, records=sum(1 for _ in f.open("rb")) if f.is_file() else 0,
                       bound=None if not r.get("signer") else doc["identities"][r["signer"]]["public"] in trust["keys"].get(r["signer"], []))
        except (OSError, ValueError) as e:
            row["problem"] = f"{type(e).__name__}: {e}"
        rows.append(row)
    return rows
