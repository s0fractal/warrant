"""`warrant-agent-mcp init` — an operator command, never a tool: a configuration for one
repository checkout that keeps its records in `.warrant/` (the layout of tools/claims.py and
tools/roadmap.py).

    warrant-agent-mcp init --actor ACTOR --seed SEED --config OUT.json [--repo DIR] [--state DIR]
                           [--workspace NAME] [--operations context,read,prepare,commit] [--force]

The workspace's store is the repository's `.warrant/store`; its trust is `.warrant/trust.json`
admitted under `.warrant/roles.json` by warrant.bindings, the rule tools/claims.py admits by,
read again for every view; its profile counts results acceptances by the
`results_accept_by` of `.warrant/roadmap.json`. The signer is the operator's existing seed,
and it is refused unless its key is exactly the key `.warrant/roles.json` pins for ACTOR and
`.warrant/trust.json` admits that binding: no key is created, copied or bound here (SPEC
§10.8; `tools/claims.py keygen`, `pin` and `bind` are the operator's commands). The state
directory, the configuration and the seed lie outside the repository and, with the repository, in the
operator's directory ($WARRANT_AGENT_HOME, else the home directory). Nothing is written
before every check has passed; nothing of the repository is run, only its JSON files read.
A refusal prints `REFUSED <CODE> <detail>` on stderr and exits 2."""
import argparse
import json
import os
import sys
from pathlib import Path

from warrant import bindings as B
from warrant import engine as E
from warrant import records as R
from warrant import shapes as S
from warrant.keys import Key

from . import AGENT_API
from .config import HANDLE, OPERATIONS, Config, repository_trust
from .errors import AgentError

CODES = ("INIT_ACTOR_SHAPE", "INIT_NOT_A_REPOSITORY", "INIT_INSIDE_REPOSITORY", "INIT_OUTSIDE_HOME", "INIT_OPERATIONS",
         "INIT_WORKSPACE_NAME", "INIT_CONFIG_EXISTS", "INIT_NO_SEED", "INIT_SEED_SHAPE", "INIT_TRUST_SHAPE",
         "INIT_ACTOR_NOT_PINNED", "INIT_KEY_NOT_PINNED", "INIT_NOT_ADMITTED", "INIT_ROADMAP_SHAPE")
DEFAULT_OPERATIONS = ("context", "read", "prepare", "commit")
USE = "continue"
USES = {USE: {"delivery": ["LOCAL_CAPTURE", "MATCH_EXPECTED_SET"], "reliance": ["ELIGIBLE"], "fresh": True}}
ROADMAP = "warrant-roadmap/config@1"
DOT = ".warrant"
TRUST, ROLES_FILE, ROADMAP_FILE = "trust.json", "roles.json", "roadmap.json"
FILES = tuple(f"{DOT}/{f}" for f in (TRUST, ROLES_FILE, ROADMAP_FILE))
HOME = "WARRANT_AGENT_HOME"     # the operator's directory (default: the home directory)


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


def _confined(arg, home, what):
    """The real path of a command-line path `arg` if it lies in the operator's directory `home`, else refused:
    init writes and reads only there."""
    real, base = os.path.realpath(arg), os.path.realpath(home)
    _refuse(os.path.commonpath([real, base]) == base, "INIT_OUTSIDE_HOME",
            f"{what} {real} is outside the operator's directory {base} (${HOME}, else the home directory)")
    return Path(real)


def _json(path, code):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError) as e:
        raise Refused(code, f"{path.name}: {type(e).__name__}: {e}") from None


def plan(repo, actor, seed, config, state=None, workspace=None, operations=DEFAULT_OPERATIONS, force=False, home=None):
    """(configuration document, profile document, summary): every check, nothing written."""
    home = home or os.environ.get(HOME) or Path.home()
    try:
        R.check_actor(actor, "actor")
    except R.Invalid as e:
        raise Refused("INIT_ACTOR_SHAPE", f"{str(actor)[:60]!r} is not an actor id (SPEC §3): {e}") from None
    repo = _confined(repo, home, "the repository")
    dot = repo / DOT
    _refuse((dot / "store").is_dir() and all((repo / f).is_file() for f in FILES),
            "INIT_NOT_A_REPOSITORY", f"{repo} has no {DOT}/store with {', '.join(FILES)}")
    config = _confined(config, home, "the configuration")
    state = _confined(state, home, "the state directory") if state else config.parent / f"{config.stem}-state"
    seed = _confined(seed, home, "the seed")
    for what, p in (("the configuration", config), ("the state directory", state), ("the seed", seed)):
        _refuse(not _inside(p, repo), "INIT_INSIDE_REPOSITORY",
                f"{what} {p} is inside the repository {repo}: the operator's files stay outside it")
    operations = list(operations)
    _refuse(bool(operations) and len(set(operations)) == len(operations) and set(operations) <= set(OPERATIONS),
            "INIT_OPERATIONS", f"operations are distinct names of {list(OPERATIONS)}, not {operations}")
    workspace = workspace or repo.name.lower()
    _refuse(HANDLE.match(workspace) is not None, "INIT_WORKSPACE_NAME",
            f"{workspace!r} is not a workspace handle ([a-z0-9][a-z0-9_.-]{{0,63}}); give --workspace")
    _refuse(force or not config.exists(), "INIT_CONFIG_EXISTS", f"{config} exists; --force replaces it")
    _refuse(seed.is_file(), "INIT_NO_SEED",
            f"no seed at {seed}: init creates no key (the operator makes one: tools/claims.py keygen)")
    try:
        key = Key.from_seed_hex(seed.read_text())
    except (OSError, ValueError, TypeError) as e:
        raise Refused("INIT_SEED_SHAPE", f"{seed.name} is not a hex Ed25519 seed: {type(e).__name__}") from None
    roles, problems = B.read_roles(_json(dot / ROLES_FILE, "INIT_TRUST_SHAPE"))
    _refuse(not problems, "INIT_TRUST_SHAPE", "; ".join(f"{c} {d}" for c, d in problems))
    pin = roles.get(actor)
    _refuse(S.hex64(pin), "INIT_ACTOR_NOT_PINNED",
            f".warrant/roles.json pins no key for {actor!r} ({B._role_name(pin) if actor in roles else 'no role'}): "
            "a signer is an actor whose key the repository pins")
    _refuse(key.public == pin, "INIT_KEY_NOT_PINNED",
            f"the seed's key {key.id[:12]} is not the key .warrant/roles.json pins for {actor!r} "
            f"({B._role_name(pin)}); no other key signs as it")
    try:
        trust = repository_trust(dot / TRUST, dot / ROLES_FILE)
    except AgentError as e:
        raise Refused("INIT_TRUST_SHAPE", e.message) from None
    admitted = [(k["actor"], k["public"]) for k in trust["keys"]]
    _refuse((actor, key.public) in admitted, "INIT_NOT_ADMITTED",
            f".warrant/trust.json admits no binding of {actor!r} to key {key.id[:12]} (tools/claims.py bind)")
    rm = _json(dot / ROADMAP_FILE, "INIT_ROADMAP_SHAPE")
    _refuse(isinstance(rm, dict) and rm.get("roadmap") == ROADMAP and isinstance(rm.get("results_accept_by"), list)
            and all(S.is_actor(a) for a in rm["results_accept_by"]), "INIT_ROADMAP_SHAPE",
            f".warrant/roadmap.json is not a {ROADMAP} with results_accept_by a list of actor ids")
    profile = E.profile(uses={USE: {"requires_triggers": False}}, results_by=rm["results_accept_by"])
    ws_state = state / workspace
    doc = {"agent_api": AGENT_API, "state": str(state),
           "workspaces": {workspace: {
               "store": str(dot / "store"),
               "trust": {"bindings": str(dot / TRUST), "roles": str(dot / ROLES_FILE)},
               "profile": str(ws_state / "profile.json"),
               "signer": {"actor": actor, "key": str(seed)},
               "source_name": workspace, "uses": USES, "operations": operations}}}
    summary = {"config": str(config), "workspace": workspace, "repository": str(repo), "state": str(state),
               "signer": {"actor": actor, "key": key.id}, "operations": operations,
               "trust": sorted({a for a, _ in admitted}), "results_accept_by": rm["results_accept_by"],
               "serve": f"warrant-agent-mcp --config {config}"}
    return doc, profile, summary


def init(repo, actor, seed, config, state=None, workspace=None, operations=DEFAULT_OPERATIONS, force=False, home=None):
    """Check everything (plan), then write the profile and the configuration; returns the summary."""
    doc, profile, summary = plan(repo, actor, seed, config, state, workspace, operations, force, home)
    ws_state = Path(doc["state"]) / summary["workspace"]
    ws_state.mkdir(parents=True, exist_ok=True)
    (ws_state / "profile.json").write_text(json.dumps(profile, sort_keys=True) + "\n")
    Config(doc)                                 # the configuration loads, or nothing is written for it
    out = Path(summary["config"])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, out)
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser(prog="warrant-agent-mcp init", description=__doc__, allow_abbrev=False,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="the repository checkout (default: the current directory)")
    ap.add_argument("--actor", required=True, help="the signer's actor id, as .warrant/roles.json pins it")
    ap.add_argument("--seed", required=True, help="the operator's existing seed of that actor's pinned key")
    ap.add_argument("--config", required=True, help="the configuration to write (outside the repository)")
    ap.add_argument("--state", help="the state directory (default: <config>-state beside the configuration)")
    ap.add_argument("--workspace", help="the workspace handle (default: the repository directory's name)")
    ap.add_argument("--operations", default=",".join(DEFAULT_OPERATIONS),
                    help=f"comma-separated, of {','.join(OPERATIONS)} (default: %(default)s)")
    ap.add_argument("--force", action="store_true", help="replace an existing configuration")
    a = ap.parse_args(argv)
    try:
        summary = init(a.repo, a.actor, a.seed, a.config, a.state, a.workspace,
                       [x for x in a.operations.split(",") if x] if a.operations else [], a.force)
    except Refused as e:
        print(f"REFUSED {e.code} {e.message}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=1, sort_keys=True))
    return 0
