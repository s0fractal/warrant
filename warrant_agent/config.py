"""Operator configuration. Chosen by the operator, never by a request: the workspaces (a repository
checkout, or a store with its trust and profile), the signer and the limits. Requests name a workspace
only by its handle.

    {"agent_api": "warrant-agent/3",
     "workspaces": {NAME: {"repo": DIR}                                   # DIR/.warrant and DIR/.warrant/v3.json
                         | {"store": DIR, "trust": FILE, "profile": FILE},
                    ... "signer": {"actor": A, "key": SEED}?, "operations": [...]?, "limits": {...}?}}}

A configuration `warrant-agent-mcp init` wrote for Warrant 2 (agent_api warrant-agent/1, its store a
repository's `.warrant/store`) is read as the same repository with the same signer: an operator's
existing configuration, and the seed it names, keep working across the switch."""
import json
import re
from pathlib import Path

from warrant import engine as E
from warrant import shapes as S
from warrant.store import Store

from . import AGENT_API
from .errors import AgentError, need

V2_API = "warrant-agent/1"
HANDLE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")
OPERATIONS = ("context", "read", "graph", "handoff", "prepare", "commit")
ALWAYS = ("workspace", "explain")            # read the configuration and a static table only
REPOSITORY = "repository/3"
STORE_DIR = ".warrant"                       # a repository's store, with its v3.json
DEFAULT_LIMITS = {"store_bytes": 64 << 20, "context_bytes": 64 << 10, "read_bytes": 256 << 10}


def repository_config(repo):
    """(trust, profile, name) of a repository: its `.warrant/v3.json`, checked."""
    try:
        doc = json.loads((Path(repo) / STORE_DIR / "v3.json").read_bytes())
    except (OSError, ValueError) as e:
        raise AgentError("BAD_REQUEST", f"repository configuration: {type(e).__name__}: {e}") from None
    need(isinstance(doc, dict) and doc.get("warrant") == REPOSITORY and set(doc) == {"warrant", "repository", "trust", "profile"},
         "BAD_REQUEST", f".warrant/v3.json is a {REPOSITORY} document {{warrant, repository, trust, profile}}")
    for why in (E.trust_problem(doc["trust"]), E.profile_problem(doc["profile"])):
        need(why is None, "BAD_REQUEST", f".warrant/v3.json: {why}")
    return doc["trust"], doc["profile"], doc["repository"]


class Workspace:
    def __init__(self, name, doc, legacy=False):
        need(isinstance(doc, dict), "BAD_REQUEST", f"workspace {name!r} is an object")
        self.name = name
        if legacy:                   # Warrant 2's init output: {store: <repo>/.warrant/store, trust, profile, signer, ...}
            store = Path(str(doc.get("store", "")))
            need(store.name == "store" and store.parent.name == STORE_DIR, "UNSUPPORTED_VERSION",
                 f"workspace {name!r}: a {V2_API} configuration is read only for a repository's .warrant/store")
            doc = {"repo": str(store.parent.parent), "signer": doc.get("signer"),
                   "operations": [o for o in doc.get("operations", OPERATIONS) if o in OPERATIONS] + ["graph"]}
        if "repo" in doc:
            self.repo = Path(doc["repo"])
            self.store, self.trust_path, self.profile_path = self.repo / STORE_DIR, None, None
        else:
            need({"store", "trust", "profile"} <= set(doc), "BAD_REQUEST",
                 f"workspace {name!r}: give repo, or store, trust and profile")
            self.repo, self.store = None, Path(doc["store"])
            self.trust_path, self.profile_path = Path(doc["trust"]), Path(doc["profile"])
        signer = doc.get("signer")
        if signer:
            need(isinstance(signer, dict) and S.is_actor(signer.get("actor")) and isinstance(signer.get("key"), str),
                 "BAD_REQUEST", f"workspace {name!r}: signer is {{actor, key}} with an actor id")
        self.signer = (signer["actor"], Path(signer["key"])) if signer else None
        ops = list(dict.fromkeys(doc.get("operations", OPERATIONS)))
        need(set(ops) <= set(OPERATIONS), "BAD_REQUEST", f"workspace {name!r}: operations are of {list(OPERATIONS)}")
        self.operations = tuple(ops)
        self.limits = dict(DEFAULT_LIMITS, **doc.get("limits", {}))
        need(all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in self.limits.values())
             and set(self.limits) == set(DEFAULT_LIMITS), "BAD_REQUEST", f"workspace {name!r}: limits {sorted(DEFAULT_LIMITS)}")

    def permit(self, op):
        need(op in ALWAYS or op in self.operations, "NOT_PERMITTED", f"operation {op!r} is not permitted for workspace {self.name!r}")

    def receiver(self):
        """(trust, profile), read again for every call."""
        if self.repo is not None:
            return repository_config(self.repo)[:2]
        try:
            trust, profile = (json.loads(p.read_bytes()) for p in (self.trust_path, self.profile_path))
        except (OSError, ValueError) as e:
            raise AgentError("BAD_REQUEST", f"workspace {self.name!r}: {type(e).__name__}: {e}") from None
        for why in (E.trust_problem(trust), E.profile_problem(profile)):
            need(why is None, "BAD_REQUEST", f"workspace {self.name!r}: {why}")
        return trust, profile

    def open(self):
        """The store, admitted by size before a byte is parsed (the workspace's bound; the engine's LIMITS
        bound the rest of the assessment)."""
        st = Store(self.store)
        size = (st.file.stat().st_size if st.file.is_file() else 0) + \
            (sum(p.stat().st_size for p in st.blobs.iterdir()) if st.blobs.is_dir() else 0)
        need(size <= self.limits["store_bytes"], "RESOURCE_LIMIT",
             f"the store holds {size} bytes; this workspace admits {self.limits['store_bytes']}")
        return st


class Config:
    def __init__(self, doc):
        api = doc.get("agent_api") if isinstance(doc, dict) else None
        need(api in (AGENT_API, V2_API), "UNSUPPORTED_VERSION", f"configuration must declare agent_api {AGENT_API!r}")
        need(isinstance(doc.get("workspaces"), dict) and doc["workspaces"], "BAD_REQUEST", "workspaces is a non-empty object")
        self.workspaces = {}
        for name, w in doc["workspaces"].items():
            need(HANDLE.match(name) is not None, "BAD_REQUEST", "workspace names are local handles")
            self.workspaces[name] = Workspace(name, w, legacy=api == V2_API)

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))  # NOSONAR S8707: the operator's --config, read before any request

    def workspace(self, name):
        if not (isinstance(name, str) and name in self.workspaces):
            raise AgentError("UNKNOWN_WORKSPACE", "workspace is not configured")
        return self.workspaces[name]
