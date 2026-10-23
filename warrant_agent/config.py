"""Operator configuration (CONTRACT A). Chosen by the operator, never by a request:
stores, signer, receiver trust/profile, expectations, use policies and limits.
Requests name a workspace and an expectation only by their local handles."""
import json
import os
import re
from pathlib import Path

from warrant import bindings as B
from warrant import jcs as C
from warrant import limits as L
from warrant import records as R
from warrant import shapes as S
from warrant.store import Trust

from . import AGENT_API
from .errors import AgentError, need

HANDLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}\Z")      # \Z: `$` admits a trailing newline (AMEND 2 of #164)
OPERATIONS = ("context", "read", "handoff", "prepare", "commit", "compute")
# What a workspace keeps under <state>/<name>: created when the configuration loads (the first six) or by the
# views and the store (verdicts, replay-cache). None of them may be a symlink (AMEND 1 of #179).
STATE_DIRS = ("views", "staging", "imports", "drafts", "requests", "exports")
STATE_LAZY = ("verdicts", "replay-cache")
RELATIONS = ("MATCH_EXPECTED_SET", "UNPINNED", "MISSING_DECLARED_BYTES", "CONTENT_MISMATCH", "WRONG_SET",
             "WRONG_SOURCE", "UNVERIFIED_EXPORTER", "LOCAL_CAPTURE")
# The engine's admission limits (warrant.limits, SPEC §9) are workspace limits too.
DEFAULT_LIMITS = {"context_bytes": 16 * 1024, "transfer_bytes": 16 * 1024 * 1024, "assess_seconds": 120,
                  "provider_seconds": 600, "read_bytes": 64 * 1024, "view_ttl": 24 * 3600, **L.DEFAULTS}


def state_links(ws_state):
    """The paths of a workspace's state tree that are symlinks (dangling ones included): its directory, the
    directories under it and the profile beside them are written by the interface, and a link there would
    take those writes elsewhere."""
    return [str(q) for q in (ws_state, *(ws_state / d for d in STATE_DIRS + STATE_LAZY)) if os.path.islink(q)]


class Workspace:
    def __init__(self, name, doc, state_root, create=True):
        self.name = name
        self.store = Path(doc["store"])
        trust = doc["trust"]
        if isinstance(trust, dict):         # a repository's bindings under its roles, admitted on every read
            need(set(trust) == {"bindings", "roles"}, "BAD_REQUEST",
                 f"workspace {name!r}: trust is a trust/2 file or {{bindings, roles}} of a repository")
            self.trust_path, self.roles_path = Path(trust["bindings"]), Path(trust["roles"])
        else:
            self.trust_path, self.roles_path = Path(trust), None
        self.profile_path = Path(doc["profile"])
        self.current = list(doc.get("current", []))
        repo = doc.get("repo")
        self.repo = (Path(repo["path"]), repo["rev"]) if repo else None
        signer = doc.get("signer")
        if signer:
            try:
                R.check_actor(signer["actor"], "signer actor")       # SPEC §3: the one shape of an actor id
            except R.Invalid as e:
                raise AgentError("BAD_REQUEST", f"workspace {name!r}: {e}") from None
        self.signer = (signer["actor"], Path(signer["key"])) if signer else None
        self.source_name = doc.get("source_name", name)
        self.expectations = dict(doc.get("expectations", {}))
        self.uses = dict(doc.get("uses", {}))
        self.limits = dict(DEFAULT_LIMITS, **doc.get("limits", {}))
        try:
            L.resolve(self.assessment_limits())
        except ValueError as e:
            raise AgentError("BAD_REQUEST", f"workspace {name!r}: {e}") from None
        self.operations = tuple(doc.get("operations", OPERATIONS))
        self.state = Path(state_root) / name
        links = state_links(self.state)
        need(not links, "BAD_REQUEST", f"workspace {name!r}: the state tree holds symlinks: {links}", links=links)
        for sub in STATE_DIRS if create else ():
            (self.state / sub).mkdir(parents=True, exist_ok=True)

    def assessment_limits(self):
        """The engine's admission limits of this workspace (warrant.limits)."""
        return {k: self.limits[k] for k in L.DEFAULTS}

    def permit(self, op):
        need(op in self.operations, "NOT_PERMITTED", f"operation {op!r} is not permitted for workspace {self.name!r}")

    def trust_bytes(self):
        if self.roles_path is None:
            return self.trust_path.read_bytes()
        return C.canon(repository_trust(self.trust_path, self.roles_path))

    def trust(self):
        return Trust(C.loads(self.trust_bytes()))

    def profile(self):
        return json.loads(self.profile_path.read_bytes())

    def expectation(self, handle):
        if handle is None:
            return None
        need(isinstance(handle, str) and handle in self.expectations, "UNKNOWN_EXPECTATION",
             "expectation is not a configured handle of this workspace")
        return dict(self.expectations[handle], handle=handle)

    def expectation_digest(self, handle):
        """The identity of the CURRENT definition behind a handle, or None if the handle is gone."""
        e = self.expectations.get(handle)
        # JSON, not JCS: the operator's configuration may carry floats (as the config digest does)
        return None if e is None else C.digest(json.dumps(e, sort_keys=True, separators=(",", ":")).encode())

    def use_policy(self, use):
        need(isinstance(use, str) and use in self.uses, "BAD_REQUEST", f"use {use!r} is not configured")
        return self.uses[use]


def repository_trust(bindings_path, roles_path):
    """The trust/2 document of the bindings a repository's .warrant/trust.json admits under its
    .warrant/roles.json, by warrant.bindings: the rule tools/claims.py admits by. A binding that
    rule does not admit is not in the trust; a roles file with any problem, or a bindings file
    that is not a bindings document, is refused: a dropped pin would make its name first-come."""
    try:
        roles_doc, doc = json.loads(Path(roles_path).read_bytes()), C.loads(Path(bindings_path).read_bytes())
    except (OSError, ValueError, TypeError) as e:      # C.NotCanonical is a ValueError
        raise AgentError("BAD_REQUEST", f"repository trust: {type(e).__name__}: {e}") from None
    roles, problems = B.read_roles(roles_doc)
    admitted, refused = B.admit_bindings(doc, roles=roles)
    problems += [p for p in refused if p[0] == "BINDINGS_SHAPE"]
    need(not problems, "BAD_REQUEST", "repository trust: " + "; ".join(f"{c} {d}" for c, d in problems),
         problems=[c for c, _ in problems])
    return Trust.document(admitted)


class Config:
    def __init__(self, doc, create=True):
        need(isinstance(doc, dict) and doc.get("agent_api") == AGENT_API, "UNSUPPORTED_VERSION",
             f"configuration must declare agent_api {AGENT_API!r}")
        self.state = Path(doc["state"])
        self.workspaces = {}
        for name, w in doc["workspaces"].items():
            need(HANDLE.match(name) is not None, "BAD_REQUEST", "workspace names are local handles")
            for h, e in w.get("expectations", {}).items():
                need(HANDLE.match(h) is not None and S.hex64(e.get("manifest")),
                     "BAD_REQUEST", "an expectation is {manifest: hex64, source?, exporter?}")
            for u, p in w.get("uses", {}).items():
                need(set(p) <= {"delivery", "reliance", "fresh"} and all(r in RELATIONS for r in p.get("delivery", [])),
                     "BAD_REQUEST", f"use policy {u!r}: delivery, reliance, fresh")
            self.workspaces[name] = Workspace(name, w, self.state, create)
        # Configuration is not a Warrant record: it may carry floats (deadlines).
        self.digest = C.digest(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def workspace(self, name):
        if not (isinstance(name, str) and name in self.workspaces):
            raise AgentError("UNKNOWN_WORKSPACE", "workspace is not configured")
        return self.workspaces[name]
