"""Operator configuration (CONTRACT A). Chosen by the operator, never by a request:
stores, signer, receiver trust/profile, expectations, use policies and limits.
Requests name a workspace and an expectation only by their local handles."""
import json
import re
from pathlib import Path

from warrant import jcs as C
from warrant.store import Trust

from . import AGENT_API
from .errors import AgentError, need

HANDLE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
OPERATIONS = ("context", "read", "handoff", "prepare", "commit", "compute")
RELATIONS = ("MATCH_EXPECTED_SET", "UNPINNED", "MISSING_DECLARED_BYTES", "CONTENT_MISMATCH", "WRONG_SET",
             "WRONG_SOURCE", "UNVERIFIED_EXPORTER", "LOCAL_CAPTURE")
DEFAULT_LIMITS = {"context_bytes": 16 * 1024, "transfer_bytes": 16 * 1024 * 1024, "assess_seconds": 120,
                  "provider_seconds": 600, "read_bytes": 64 * 1024, "view_ttl": 24 * 3600}


class Workspace:
    def __init__(self, name, doc, state_root):
        self.name = name
        self.store = Path(doc["store"])
        self.trust_path = Path(doc["trust"])
        self.profile_path = Path(doc["profile"])
        self.current = list(doc.get("current", []))
        repo = doc.get("repo")
        self.repo = (Path(repo["path"]), repo["rev"]) if repo else None
        signer = doc.get("signer")
        self.signer = (signer["actor"], Path(signer["key"])) if signer else None
        self.source_name = doc.get("source_name", name)
        self.expectations = dict(doc.get("expectations", {}))
        self.uses = dict(doc.get("uses", {}))
        self.limits = dict(DEFAULT_LIMITS, **doc.get("limits", {}))
        self.operations = tuple(doc.get("operations", OPERATIONS))
        self.state = Path(state_root) / name
        for sub in ("views", "staging", "imports", "drafts", "requests", "exports"):
            (self.state / sub).mkdir(parents=True, exist_ok=True)

    def permit(self, op):
        need(op in self.operations, "NOT_PERMITTED", f"operation {op!r} is not permitted for workspace {self.name!r}")

    def trust_bytes(self):
        return self.trust_path.read_bytes()

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


class Config:
    def __init__(self, doc):
        need(isinstance(doc, dict) and doc.get("agent_api") == AGENT_API, "UNSUPPORTED_VERSION",
             f"configuration must declare agent_api {AGENT_API!r}")
        self.state = Path(doc["state"])
        self.workspaces = {}
        for name, w in doc["workspaces"].items():
            need(HANDLE.match(name) is not None, "BAD_REQUEST", "workspace names are local handles")
            for h, e in w.get("expectations", {}).items():
                need(HANDLE.match(h) is not None and HEX64.match(e.get("manifest", "")) is not None,
                     "BAD_REQUEST", "an expectation is {manifest: hex64, source?, exporter?}")
            for u, p in w.get("uses", {}).items():
                need(set(p) <= {"delivery", "reliance", "fresh"} and all(r in RELATIONS for r in p.get("delivery", [])),
                     "BAD_REQUEST", f"use policy {u!r}: delivery, reliance, fresh")
            self.workspaces[name] = Workspace(name, w, self.state)
        # Configuration is not a Warrant record: it may carry floats (deadlines).
        self.digest = C.digest(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def workspace(self, name):
        if not (isinstance(name, str) and name in self.workspaces):
            raise AgentError("UNKNOWN_WORKSPACE", "workspace is not configured")
        return self.workspaces[name]
