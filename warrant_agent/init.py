"""`warrant-agent-mcp init` — an operator command, never a tool: a configuration for one repository
checkout that keeps its records in `.warrant/` (records.jsonl, blobs/) under `.warrant/v3.json`.

    warrant-agent-mcp init --actor ACTOR --seed SEED --config OUT.json [--repo DIR]
                           [--workspace NAME] [--operations context,read,graph,prepare,commit] [--force]

The signer is the operator's existing seed, refused unless its key is a key `.warrant/v3.json`'s trust
binds to ACTOR: no key is created, copied or bound here. The repository, the seed and the configuration
lie in the operator's home directory; the seed and the configuration outside the repository. The
configuration is written atomically through no symlink, and an existing one is replaced only with
--force and only when it is what an init wrote for this repository and workspace (Warrant 2's init
output included). Nothing of the repository is run, only its JSON read. A refusal prints
`REFUSED <CODE> <detail>` on stderr and exits 2."""
import argparse
import json
import os
import sys
from pathlib import Path

from warrant import shapes as S
from warrant.keys import Key

from . import AGENT_API
from .config import HANDLE, OPERATIONS, V2_API, Config, repository_config
from .errors import AgentError

CODES = ("INIT_ACTOR_SHAPE", "INIT_NOT_A_REPOSITORY", "INIT_INSIDE_REPOSITORY", "INIT_OUTSIDE_HOME", "INIT_OPERATIONS",
         "INIT_WORKSPACE_NAME", "INIT_CONFIG_EXISTS", "INIT_NO_SEED", "INIT_SEED_SHAPE", "INIT_TRUST_SHAPE",
         "INIT_ACTOR_NOT_PINNED", "INIT_KEY_NOT_PINNED", "INIT_SYMLINK", "INIT_PATH_CHANGED", "INIT_PATH_COLLISION",
         "INIT_NOT_INIT_OUTPUT", "INIT_CONFIG_INVALID")
DEFAULT_OPERATIONS = ("context", "read", "graph", "prepare", "commit")
ROOTS = (Path.home(),)          # where init reads and writes: the operator's home directory


class Refused(Exception):
    def __init__(self, code, message):
        assert code in CODES, code
        super().__init__(message)
        self.code, self.message = code, message


def _refuse(ok, code, message):
    if not ok:
        raise Refused(code, message)


def _inside(path, root):
    return path == root or root in path.parents


def _home(real):
    return next((Path(os.path.realpath(r)) for r in ROOTS if _inside(real, Path(os.path.realpath(r)))), None)


def _confined(arg, what):
    real = Path(os.path.realpath(arg))
    _refuse(_home(real) is not None, "INIT_OUTSIDE_HOME", f"{what} {real} is outside the operator's home directory")
    return real


def _target(path, what, repo):
    """The real path init writes for `path`: in the home directory, outside the repository, and no component
    below the home directory a symlink (dangling or not), so the path written is the path checked."""
    real = _confined(path, what)
    _refuse(not _inside(real, repo), "INIT_INSIDE_REPOSITORY", f"{what} {real} is inside the repository {repo}")
    home, lexical = _home(real), Path(os.path.abspath(path))
    for q in (lexical, *lexical.parents):
        if os.path.islink(q) and _inside(Path(os.path.realpath(q.parent)), home):
            raise Refused("INIT_SYMLINK", f"{what}: {q} is a symlink; init writes no path through one")
    return real


def _write(real, data):
    """Write `data` at `real` through no symlink: each directory from the home root opened with O_NOFOLLOW
    (created where missing), then a new file renamed over the old one inside the last."""
    home = _home(real)
    fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in real.parent.relative_to(home).parts:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            try:
                nfd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as e:
                raise Refused("INIT_PATH_CHANGED", f"{real}: {part!r} is no longer a directory ({type(e).__name__})") from None
            os.close(fd)
            fd = nfd
        tmp = f".{real.name}.tmp{os.getpid()}"
        out = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(out, "wb") as f:
            f.write(data)
        os.replace(tmp, real.name, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        os.close(fd)


def _own_output(config, repo, workspace):
    """Whether the existing configuration is one an init wrote for this repository and workspace."""
    try:
        doc = json.loads(config.read_bytes())
        ws = doc["workspaces"]
        if list(ws) != [workspace]:
            return False
        if doc.get("agent_api") == AGENT_API:
            return Path(ws[workspace]["repo"]) == repo
        return doc.get("agent_api") == V2_API and Path(ws[workspace]["store"]) == repo / ".warrant" / "store"
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def plan(repo, actor, seed, config, workspace=None, operations=DEFAULT_OPERATIONS, force=False):
    """(configuration document, summary, config path): every check, nothing written."""
    _refuse(S.is_actor(actor), "INIT_ACTOR_SHAPE", f"{str(actor)[:60]!r} is not an actor id")
    repo = _confined(repo, "the repository")
    _refuse((repo / ".warrant" / "records.jsonl").is_file() and (repo / ".warrant" / "v3.json").is_file(),
            "INIT_NOT_A_REPOSITORY", f"{repo} has no .warrant/records.jsonl with .warrant/v3.json")
    seed = _confined(seed, "the seed")
    _refuse(not _inside(seed, repo), "INIT_INSIDE_REPOSITORY", f"the seed {seed} is inside the repository {repo}")
    config = _target(config, "the configuration", repo)
    _refuse(config != seed and not (config.exists() and os.path.samefile(config, seed)), "INIT_PATH_COLLISION",
            f"the configuration {config} would be written over the seed")
    operations = list(operations)
    _refuse(bool(operations) and len(set(operations)) == len(operations) and set(operations) <= set(OPERATIONS),
            "INIT_OPERATIONS", f"operations are distinct names of {list(OPERATIONS)}, not {operations}")
    workspace = workspace or repo.name.lower()
    _refuse(HANDLE.match(workspace) is not None, "INIT_WORKSPACE_NAME", f"{workspace!r} is not a workspace handle; give --workspace")
    _refuse(force or not config.exists(), "INIT_CONFIG_EXISTS", f"{config} exists; --force replaces it")
    _refuse(not config.exists() or _own_output(config, repo, workspace), "INIT_NOT_INIT_OUTPUT",
            f"{config} is not a configuration init wrote for workspace {workspace!r} of {repo}; --force replaces only that")
    _refuse(seed.is_file(), "INIT_NO_SEED", f"no seed at {seed}: init creates no key")
    try:
        key = Key.from_seed_hex(seed.read_text())
    except (OSError, ValueError, TypeError) as e:
        raise Refused("INIT_SEED_SHAPE", f"{seed.name} is not a hex Ed25519 seed: {type(e).__name__}") from None
    try:
        trust, _, name = repository_config(repo)
    except AgentError as e:
        raise Refused("INIT_TRUST_SHAPE", e.message) from None
    _refuse(actor in trust["keys"], "INIT_ACTOR_NOT_PINNED", f".warrant/v3.json binds no key to {actor!r}")
    _refuse(key.public in trust["keys"][actor], "INIT_KEY_NOT_PINNED",
            f"the seed's key {key.id[:12]} is not a key .warrant/v3.json binds to {actor!r}; no other key signs as it")
    doc = {"agent_api": AGENT_API, "workspaces": {workspace: {"repo": str(repo), "signer": {"actor": actor, "key": str(seed)},
                                                              "operations": operations}}}
    try:
        Config(doc)
    except AgentError as e:
        raise Refused("INIT_CONFIG_INVALID", e.message) from None
    summary = {"config": str(config), "workspace": workspace, "repository": str(repo), "name": name,
               "signer": {"actor": actor, "key": key.id}, "operations": operations,
               "serve": f"warrant-agent-mcp --config {config}"}
    return doc, summary, config


def init(repo, actor, seed, config, workspace=None, operations=DEFAULT_OPERATIONS, force=False):
    doc, summary, path = plan(repo, actor, seed, config, workspace, operations, force)
    _write(path, (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode())
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="warrant-agent-mcp init", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="the repository checkout (default: the current directory)")
    ap.add_argument("--actor", required=True, help="the signer's actor id, as .warrant/v3.json's trust binds it")
    ap.add_argument("--seed", required=True, help="the operator's existing seed of that actor's key")
    ap.add_argument("--config", required=True, help="the configuration to write (outside the repository)")
    ap.add_argument("--workspace", help="the workspace handle (default: the repository directory's name)")
    ap.add_argument("--operations", default=",".join(DEFAULT_OPERATIONS),
                    help=f"comma-separated, of {','.join(OPERATIONS)} (default: %(default)s)")
    ap.add_argument("--force", action="store_true", help="replace an existing configuration init wrote")
    ap.add_argument("--state", help=argparse.SUPPRESS)        # Warrant 2's flag: no state directory any more
    a = ap.parse_args(argv)
    try:
        summary = init(a.repo, a.actor, a.seed, a.config, a.workspace,
                       [x for x in a.operations.split(",") if x], a.force)
    except Refused as e:
        print(f"REFUSED {e.code} {e.message}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0
