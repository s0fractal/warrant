#!/usr/bin/env python3
"""warrant-mcp — seal an MCP server's tool-calls as warrants, into an evidence pack.

Drop this proxy between an MCP host (Claude Desktop, an agent runtime) and any
downstream MCP server. It forwards the JSON-RPC stream untouched, and for every
consequential (class >= ceiling) `tools/call` it files a signed warrant recording
what the agent did, under which effect policy, with the result as evidence and
the previous action as `prior`. The resulting `.warrants/` store IS an evidence
pack: a stranger verifies the whole agent session offline with `warrant verify`.

This is provenance, NOT gating — it observes and seals, it does not block. (Fail-
closed *authorization* is trinity/autonomy-kernel's job.) Sealing is scoped to
A2+ so read-only chatter (A0/A1) doesn't bloat the pack — but only a tool the
effects config *declares* can be read-only. A tool the config does not name is
sealed as undeclared (A4) whatever its name suggests, an empty effect list is
refused at startup, and a seal that fails is counted in the manifest and in
the exit status rather than lost to stderr (review 2026-09, chatgpt-web:
`get_and_execute` and `query` were A0 by name and never sealed, and a write
failure left the pack looking complete).

    warrant-mcp --store ./session --actor agent@me --key agent.key \
                --effects effects.json -- <downstream server command…>

MIT. Pure standard library (+ `cryptography` via the warrant module). The effect
taxonomy here is a light MIT subset for the sealing use-case; the canonical
A0–A4 authority taxonomy lives in trinity/autonomy-kernel.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---- locate the warrant reference implementation (installed or in-repo) ----
try:
    import warrant as W                                    # installed package
except ModuleNotFoundError:
    _p = Path(__file__).resolve().parent / "warrant.py"    # sibling in impl/
    _spec = importlib.util.spec_from_file_location("warrant", _p)
    W = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(W)


# ---------- effect taxonomy (light MIT subset; canonical one is in trinity) ----------
# Most-privileged effect wins. An effect absent from this table is treated as A4
# (fail-closed): an unrecognized action is consequential until proven otherwise.
EFFECT_CLASS = {
    # A0 — observe
    "read": "A0", "observe": "A0", "list": "A0", "get": "A0", "search": "A0",
    # A1 — derive/format
    "format": "A1", "cache": "A1", "render": "A1", "summarize": "A1",
    # A2 — local change
    "source_change": "A2", "write": "A2", "create": "A2", "update": "A2",
    "comment": "A2", "test": "A2",
    # A3 — reach outward (non-destructive)
    "fetch_public": "A3", "push": "A3", "dispatch": "A3", "publish": "A3",
    # A4 — irreversible / value-bearing / governance
    "delete": "A4", "destroy": "A4", "spend": "A4", "pay": "A4", "transfer": "A4",
    "key": "A4", "rotate_key": "A4", "deploy": "A4", "chain_tx": "A4", "admin": "A4",
}
ORDER = {"A0": 0, "A1": 1, "A2": 2, "A3": 3, "A4": 4}

# Name hints: verb -> effect, consulted only for a tool absent from the effects
# config, and only as an ANNOTATION on the undeclared sentinel. They can name
# what a tool probably does; they can never lower its class below A4.
_NAME_HINTS = [
    ("delete", "delete"), ("remove", "delete"), ("drop", "delete"), ("destroy", "destroy"),
    ("deploy", "deploy"), ("pay", "pay"), ("transfer", "transfer"), ("charge", "spend"),
    ("push", "push"), ("publish", "publish"), ("send", "dispatch"), ("dispatch", "dispatch"),
    ("fetch", "fetch_public"), ("http", "fetch_public"), ("web", "fetch_public"),
    ("create", "create"), ("write", "write"), ("update", "update"), ("edit", "write"),
    ("insert", "write"), ("comment", "comment"), ("append", "write"),
    ("read", "read"), ("get", "get"), ("list", "list"), ("search", "search"),
    ("query", "read"), ("fetch_row", "read"),
]


def effects_for(tool, effects_map):
    """Return (effects list, source) for a tool name.

    Config wins. A tool absent from the config carries the fail-closed sentinel
    `mcp_tool_undeclared` (-> A4) whatever its name says; when a name hint
    matches it is appended so the record states what the name suggested, but
    a hint never lowers the class. `query` used to be A0 by name, which is a
    statement about a substring, not about what the tool does."""
    if tool in effects_map:
        return list(effects_map[tool]), "config"
    low = tool.lower()
    for needle, eff in _NAME_HINTS:
        if needle in low:
            return ["mcp_tool_undeclared", eff], "undeclared+hint"
    return ["mcp_tool_undeclared"], "undeclared"


def validate_effects_map(effects_map):
    """Refuse an effects config that would silence a tool. Returns the map.

    An empty list classified a tool A0 from a declaration that declared nothing;
    under the default ceiling it was then never sealed. Declare what the tool
    does, or leave it out and it is sealed as undeclared."""
    if not isinstance(effects_map, dict):
        raise ValueError("EFFECTS_CONFIG: must be a JSON object {tool: [effect, ...]}")
    for tool, effs in effects_map.items():
        if not isinstance(tool, str) or not tool:
            raise ValueError("EFFECTS_CONFIG: tool names must be non-empty strings")
        if (not isinstance(effs, list) or not effs
                or not all(isinstance(e, str) and e for e in effs)):
            raise ValueError(
                f"EFFECTS_CONFIG: {tool!r} declares no effects -- an empty list would "
                "classify it A0 and never seal it; declare what it does, or leave it "
                "out and it is sealed as undeclared (A4)")
    return effects_map


def classify(tool, effects_map):
    """(cls, effects, source): the most-privileged class over the tool's effects."""
    effects, source = effects_for(tool, effects_map)
    cls = "A0"
    for e in effects:
        c = EFFECT_CLASS.get(e, "A4")            # unknown effect -> A4 (fail-closed)
        if ORDER[c] > ORDER[cls]:
            cls = c
    return cls, effects, source


# ---------- sealing ----------
class Sealer:
    """Files one warrant per consequential tool-call, chained by `prior`."""

    def __init__(self, store_dir, actor, key_path, effects_map, ceiling="A2"):
        self.store = W.Store(str(store_dir))
        self.store.init()
        self.actor = actor
        self.key_path = str(key_path)
        self.effects_map = validate_effects_map(effects_map)
        self.ceiling = ceiling
        self.prior = []                          # WarrantID chain of the session
        self.sealed = 0
        self.records = []
        self.seal_failures = []                  # calls observed but NOT sealed
        self.unreturned = []                     # calls sent, never answered
        self.unpaired = []                       # responses on an ambiguous id, never sealed
        self.downstream_returncode = None
        # Pin the effect policy itself (bytes) so a verifier sees exactly which
        # table classified these actions.
        policy_bytes = json.dumps(
            {"warrant_mcp_effects": "0", "ceiling": ceiling, "effects": effects_map},
            sort_keys=True, separators=(",", ":")).encode()
        self.policy_hash = self.store.put_blob(policy_bytes)
        self._lock = threading.Lock()

    def _args(self, **kw):
        class A:
            pass
        a = A()
        a.under = [self.policy_hash]
        a.evidence = kw.pop("evidence", [])
        a.prior = list(self.prior)
        a.reason = kw.pop("reason", None)
        a.check = a.transcript = None
        a.runtime, a.verdict = "cmd@v1", "pass"
        a.relitigates = None
        a.actor, a.key = self.actor, self.key_path
        a.ts = kw.pop("ts", int(time.time()))
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def seal(self, tool, tool_input, result, is_error, ts=None):
        """Seal one completed tool-call. Returns the WarrantID, or None if the
        call's class is below the ceiling (not sealed)."""
        cls, effects, source = classify(tool, self.effects_map)
        if ORDER[cls] < ORDER[self.ceiling]:
            return None
        with self._lock:
            call = json.dumps({"tool": tool, "input": tool_input},
                              sort_keys=True, separators=(",", ":")).encode()
            subject = self.store.put_blob(call)
            result_bytes = json.dumps(result, sort_keys=True,
                                      separators=(",", ":")).encode()
            ev = self.store.put_blob(result_bytes)
            decision = "reject" if is_error else "accept"
            reason = (f"MCP tools/call {tool!r} classified {cls} "
                      f"(effects={effects}, via {source}); "
                      f"{'error' if is_error else 'ok'}")
            args = self._args(evidence=[ev], reason=[reason],
                              ts=ts if ts is not None else int(time.time()))
            # file_warrant prints the WarrantID to stdout (CLI behaviour). In the
            # proxy, stdout IS the host's JSON-RPC channel, so capture it away.
            with contextlib.redirect_stdout(io.StringIO()):
                wid = W.file_warrant(self.store, decision, subject, args,
                                     note=f"{tool} [{cls}]")
            self.prior = [wid]
            self.sealed += 1
            self.records.append(wid)
            return wid

    def record_failure(self, tool, error):
        """A tool-call passed through but its seal failed. The stream is kept
        (the host must not lose the response) and the loss is kept too: in the
        manifest, and in the proxy's exit status. A pack that silently omits
        the call it failed to seal is the pack that looks complete."""
        with self._lock:
            self.seal_failures.append({
                "tool": tool, "ts": int(time.time()),
                "error": f"{type(error).__name__}: {error}"[:300]})

    def record_unreturned(self, tool, tool_input, ts, ambiguous=False):
        """A tools/call went downstream and the session ended before a response
        came back. The effect may have happened; nobody observed the outcome.
        It is listed, classified, and counts against completeness if it is a
        consequential call -- an unanswered request is not a non-event."""
        cls, effects, source = classify(tool, self.effects_map)
        with self._lock:
            self.unreturned.append({"tool": tool, "arguments": tool_input, "class": cls, "effects": effects,
                                    "source": source, "ts": ts, "ambiguous": bool(ambiguous),
                                    "consequential": ORDER[cls] >= ORDER[self.ceiling]})

    def record_unpaired(self, request_id, result, is_error):
        """A response arrived for a request id whose calls can no longer be told apart
        (the host reused the id while a call was outstanding). It is kept as a blob and
        listed, and it is never sealed as the evidence of any one call."""
        blob = self.store.put_blob(json.dumps(result, sort_keys=True, separators=(",", ":")).encode())
        with self._lock:
            self.unpaired.append({"id": request_id, "result": blob, "is_error": bool(is_error),
                                  "ts": int(time.time())})

    def incomplete(self):
        """Why the pack must not be read as a complete observation, or []."""
        why = []
        if self.seal_failures:
            why.append(f"{len(self.seal_failures)} seal failure(s)")
        n = sum(1 for u in self.unreturned if u["consequential"])
        if n:
            why.append(f"{n} consequential call(s) sent downstream and never answered")
        return why

    def write_manifest(self, title=None):
        manifest = {
            "evidence_pack": "0",
            "title": title or f"warrant-mcp session ({self.actor})",
            "produced_by": "warrant-mcp",
            "ceiling": self.ceiling,
            "records": list(self.records),
            "decision": self.records[-1] if self.records else None,
            "root": self.records[0] if self.records else None,
            "sealed_calls": self.sealed,
            "seal_failures": len(self.seal_failures),
            "seal_failure_log": list(self.seal_failures),
            "unreturned_calls": list(self.unreturned),
            "unpaired_responses": list(self.unpaired),
            "downstream_returncode": self.downstream_returncode,
            "observation_complete": not self.incomplete(),
            "incomplete_because": self.incomplete(),
            "expected_verification": {"errors": 0},
            "how_to_verify": "warrant --store .warrants verify",
        }
        (Path(self.store.root).parent / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return manifest


# ---------- stdio JSON-RPC proxy ----------
def _pump_and_forward(src, dst, on_line, on_error=None):
    """Forward every line; call on_line first. A failure in on_line never breaks
    the stream, and never disappears either: on_error(raw, ex) records it."""
    for raw in src:
        try:
            on_line(raw)
        except Exception as ex:                  # sealing must never break the stream
            print(f"warrant-mcp: seal error: {ex}", file=sys.stderr)
            if on_error is not None:
                on_error(raw, ex)
        try:
            dst.write(raw)
            dst.flush()
        except (OSError, ValueError) as ex:      # the other side is gone
            print(f"warrant-mcp: forward failed, peer closed: {ex}", file=sys.stderr)
            return


# ---------- the per-id bookkeeping table ----------
# What run_proxy does with a request id is decided by a certified transition table,
# not by the branches below. The table is stargate's projection of the model in
# stargate examples/mcp-proxy (variant `fixed`): certified there with `idle` live, a
# repair of the model of this file's earlier code, which a two-step trace refuted
# (call, call on one id). `warrant_mcp_table.py` is stargate's fixed table runtime,
# byte for byte. Both are pinned here, in this file, not read from anything shipped
# next to them; the proxy refuses to start on any difference, and runs the runtime
# from the bytes it hashed.
TABLE_RUNTIME_SHA256 = "4ab9224fac3605bd150cb12764424e9b5c7147c72a0e5259c2d0861f94746b1a"
TABLE_PROJECTION_SHA256 = "6235a212057f2ef360d30cb767f170a363311f20bfa18f00dbf4143c8d7ac321"
TABLE_PROJECTION = (
    b'{"events":["host","reply"],"model":"14cfbf8c906b36518bf1d7be689aeeaa7032e6fb03beb333d269'
    b'7568f55b8234","projection":1,"rows":[{"event":{"host":false,"reply":false},"next":{"ambi'
    b'guous":false,"calls.one":false,"calls.two":false,"pending":false},"state":{"ambiguous":f'
    b'alse,"calls.one":false,"calls.two":false,"pending":false}},{"event":{"host":false,"reply'
    b'":true},"next":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":false},"'
    b'state":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":false}},{"event"'
    b':{"host":true,"reply":false},"next":{"ambiguous":false,"calls.one":true,"calls.two":fals'
    b'e,"pending":true},"state":{"ambiguous":false,"calls.one":false,"calls.two":false,"pendin'
    b'g":false}},{"event":{"host":true,"reply":true},"next":{"ambiguous":false,"calls.one":fal'
    b'se,"calls.two":false,"pending":false},"state":{"ambiguous":false,"calls.one":false,"call'
    b's.two":false,"pending":false}},{"event":{"host":false,"reply":false},"next":{"ambiguous"'
    b':false,"calls.one":false,"calls.two":false,"pending":true},"state":{"ambiguous":false,"c'
    b'alls.one":false,"calls.two":false,"pending":true}},{"event":{"host":false,"reply":true},'
    b'"next":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":false},"state":{'
    b'"ambiguous":false,"calls.one":false,"calls.two":false,"pending":true}},{"event":{"host":'
    b'true,"reply":false},"next":{"ambiguous":true,"calls.one":true,"calls.two":false,"pending'
    b'":false},"state":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":true}}'
    b',{"event":{"host":true,"reply":true},"next":{"ambiguous":false,"calls.one":false,"calls.'
    b'two":false,"pending":false},"state":{"ambiguous":false,"calls.one":false,"calls.two":fal'
    b'se,"pending":true}},{"event":{"host":false,"reply":false},"next":{"ambiguous":false,"cal'
    b'ls.one":false,"calls.two":true,"pending":false},"state":{"ambiguous":false,"calls.one":f'
    b'alse,"calls.two":true,"pending":false}},{"event":{"host":false,"reply":true},"next":{"am'
    b'biguous":false,"calls.one":true,"calls.two":false,"pending":false},"state":{"ambiguous":'
    b'false,"calls.one":false,"calls.two":true,"pending":false}},{"event":{"host":true,"reply"'
    b':false},"next":{"ambiguous":false,"calls.one":true,"calls.two":false,"pending":true},"st'
    b'ate":{"ambiguous":false,"calls.one":false,"calls.two":true,"pending":false}},{"event":{"'
    b'host":true,"reply":true},"next":{"ambiguous":false,"calls.one":false,"calls.two":false,"'
    b'pending":false},"state":{"ambiguous":false,"calls.one":false,"calls.two":true,"pending":'
    b'false}},{"event":{"host":false,"reply":false},"next":{"ambiguous":false,"calls.one":fals'
    b'e,"calls.two":true,"pending":true},"state":{"ambiguous":false,"calls.one":false,"calls.t'
    b'wo":true,"pending":true}},{"event":{"host":false,"reply":true},"next":{"ambiguous":false'
    b',"calls.one":true,"calls.two":false,"pending":false},"state":{"ambiguous":false,"calls.o'
    b'ne":false,"calls.two":true,"pending":true}},{"event":{"host":true,"reply":false},"next":'
    b'{"ambiguous":true,"calls.one":true,"calls.two":false,"pending":false},"state":{"ambiguou'
    b's":false,"calls.one":false,"calls.two":true,"pending":true}},{"event":{"host":true,"repl'
    b'y":true},"next":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":false},'
    b'"state":{"ambiguous":false,"calls.one":false,"calls.two":true,"pending":true}},{"event":'
    b'{"host":false,"reply":false},"next":{"ambiguous":false,"calls.one":true,"calls.two":fals'
    b'e,"pending":false},"state":{"ambiguous":false,"calls.one":true,"calls.two":false,"pendin'
    b'g":false}},{"event":{"host":false,"reply":true},"next":{"ambiguous":false,"calls.one":fa'
    b'lse,"calls.two":false,"pending":false},"state":{"ambiguous":false,"calls.one":true,"call'
    b's.two":false,"pending":false}},{"event":{"host":true,"reply":false},"next":{"ambiguous":'
    b'false,"calls.one":true,"calls.two":true,"pending":true},"state":{"ambiguous":false,"call'
    b's.one":true,"calls.two":false,"pending":false}},{"event":{"host":true,"reply":true},"nex'
    b't":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":false},"state":{"amb'
    b'iguous":false,"calls.one":true,"calls.two":false,"pending":false}},{"event":{"host":fals'
    b'e,"reply":false},"next":{"ambiguous":false,"calls.one":true,"calls.two":false,"pending":'
    b'true},"state":{"ambiguous":false,"calls.one":true,"calls.two":false,"pending":true}},{"e'
    b'vent":{"host":false,"reply":true},"next":{"ambiguous":false,"calls.one":false,"calls.two'
    b'":false,"pending":false},"state":{"ambiguous":false,"calls.one":true,"calls.two":false,"'
    b'pending":true}},{"event":{"host":true,"reply":false},"next":{"ambiguous":true,"calls.one'
    b'":true,"calls.two":true,"pending":false},"state":{"ambiguous":false,"calls.one":true,"ca'
    b'lls.two":false,"pending":true}},{"event":{"host":true,"reply":true},"next":{"ambiguous":'
    b'false,"calls.one":false,"calls.two":false,"pending":false},"state":{"ambiguous":false,"c'
    b'alls.one":true,"calls.two":false,"pending":true}},{"event":{"host":false,"reply":false},'
    b'"next":{"ambiguous":false,"calls.one":true,"calls.two":true,"pending":false},"state":{"a'
    b'mbiguous":false,"calls.one":true,"calls.two":true,"pending":false}},{"event":{"host":fal'
    b'se,"reply":true},"next":{"ambiguous":false,"calls.one":true,"calls.two":false,"pending":'
    b'false},"state":{"ambiguous":false,"calls.one":true,"calls.two":true,"pending":false}},{"'
    b'event":{"host":true,"reply":false},"next":{"ambiguous":false,"calls.one":true,"calls.two'
    b'":true,"pending":true},"state":{"ambiguous":false,"calls.one":true,"calls.two":true,"pen'
    b'ding":false}},{"event":{"host":true,"reply":true},"next":{"ambiguous":false,"calls.one":'
    b'false,"calls.two":false,"pending":false},"state":{"ambiguous":false,"calls.one":true,"ca'
    b'lls.two":true,"pending":false}},{"event":{"host":false,"reply":false},"next":{"ambiguous'
    b'":false,"calls.one":true,"calls.two":true,"pending":true},"state":{"ambiguous":false,"ca'
    b'lls.one":true,"calls.two":true,"pending":true}},{"event":{"host":false,"reply":true},"ne'
    b'xt":{"ambiguous":false,"calls.one":true,"calls.two":false,"pending":false},"state":{"amb'
    b'iguous":false,"calls.one":true,"calls.two":true,"pending":true}},{"event":{"host":true,"'
    b'reply":false},"next":{"ambiguous":true,"calls.one":true,"calls.two":true,"pending":false'
    b'},"state":{"ambiguous":false,"calls.one":true,"calls.two":true,"pending":true}},{"event"'
    b':{"host":true,"reply":true},"next":{"ambiguous":false,"calls.one":false,"calls.two":fals'
    b'e,"pending":false},"state":{"ambiguous":false,"calls.one":true,"calls.two":true,"pending'
    b'":true}},{"event":{"host":false,"reply":false},"next":{"ambiguous":true,"calls.one":fals'
    b'e,"calls.two":false,"pending":false},"state":{"ambiguous":true,"calls.one":false,"calls.'
    b'two":false,"pending":false}},{"event":{"host":false,"reply":true},"next":{"ambiguous":tr'
    b'ue,"calls.one":false,"calls.two":false,"pending":false},"state":{"ambiguous":true,"calls'
    b'.one":false,"calls.two":false,"pending":false}},{"event":{"host":true,"reply":false},"ne'
    b'xt":{"ambiguous":true,"calls.one":true,"calls.two":false,"pending":false},"state":{"ambi'
    b'guous":true,"calls.one":false,"calls.two":false,"pending":false}},{"event":{"host":true,'
    b'"reply":true},"next":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":fa'
    b'lse},"state":{"ambiguous":true,"calls.one":false,"calls.two":false,"pending":false}},{"e'
    b'vent":{"host":false,"reply":false},"next":{"ambiguous":true,"calls.one":false,"calls.two'
    b'":false,"pending":true},"state":{"ambiguous":true,"calls.one":false,"calls.two":false,"p'
    b'ending":true}},{"event":{"host":false,"reply":true},"next":{"ambiguous":true,"calls.one"'
    b':false,"calls.two":false,"pending":false},"state":{"ambiguous":true,"calls.one":false,"c'
    b'alls.two":false,"pending":true}},{"event":{"host":true,"reply":false},"next":{"ambiguous'
    b'":true,"calls.one":true,"calls.two":false,"pending":false},"state":{"ambiguous":true,"ca'
    b'lls.one":false,"calls.two":false,"pending":true}},{"event":{"host":true,"reply":true},"n'
    b'ext":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":false},"state":{"a'
    b'mbiguous":true,"calls.one":false,"calls.two":false,"pending":true}},{"event":{"host":fal'
    b'se,"reply":false},"next":{"ambiguous":true,"calls.one":false,"calls.two":true,"pending":'
    b'false},"state":{"ambiguous":true,"calls.one":false,"calls.two":true,"pending":false}},{"'
    b'event":{"host":false,"reply":true},"next":{"ambiguous":true,"calls.one":true,"calls.two"'
    b':false,"pending":false},"state":{"ambiguous":true,"calls.one":false,"calls.two":true,"pe'
    b'nding":false}},{"event":{"host":true,"reply":false},"next":{"ambiguous":true,"calls.one"'
    b':true,"calls.two":false,"pending":false},"state":{"ambiguous":true,"calls.one":false,"ca'
    b'lls.two":true,"pending":false}},{"event":{"host":true,"reply":true},"next":{"ambiguous":'
    b'false,"calls.one":false,"calls.two":false,"pending":false},"state":{"ambiguous":true,"ca'
    b'lls.one":false,"calls.two":true,"pending":false}},{"event":{"host":false,"reply":false},'
    b'"next":{"ambiguous":true,"calls.one":false,"calls.two":true,"pending":true},"state":{"am'
    b'biguous":true,"calls.one":false,"calls.two":true,"pending":true}},{"event":{"host":false'
    b',"reply":true},"next":{"ambiguous":true,"calls.one":true,"calls.two":false,"pending":fal'
    b'se},"state":{"ambiguous":true,"calls.one":false,"calls.two":true,"pending":true}},{"even'
    b't":{"host":true,"reply":false},"next":{"ambiguous":true,"calls.one":true,"calls.two":fal'
    b'se,"pending":false},"state":{"ambiguous":true,"calls.one":false,"calls.two":true,"pendin'
    b'g":true}},{"event":{"host":true,"reply":true},"next":{"ambiguous":false,"calls.one":fals'
    b'e,"calls.two":false,"pending":false},"state":{"ambiguous":true,"calls.one":false,"calls.'
    b'two":true,"pending":true}},{"event":{"host":false,"reply":false},"next":{"ambiguous":tru'
    b'e,"calls.one":true,"calls.two":false,"pending":false},"state":{"ambiguous":true,"calls.o'
    b'ne":true,"calls.two":false,"pending":false}},{"event":{"host":false,"reply":true},"next"'
    b':{"ambiguous":true,"calls.one":false,"calls.two":false,"pending":false},"state":{"ambigu'
    b'ous":true,"calls.one":true,"calls.two":false,"pending":false}},{"event":{"host":true,"re'
    b'ply":false},"next":{"ambiguous":true,"calls.one":true,"calls.two":true,"pending":false},'
    b'"state":{"ambiguous":true,"calls.one":true,"calls.two":false,"pending":false}},{"event":'
    b'{"host":true,"reply":true},"next":{"ambiguous":false,"calls.one":false,"calls.two":false'
    b',"pending":false},"state":{"ambiguous":true,"calls.one":true,"calls.two":false,"pending"'
    b':false}},{"event":{"host":false,"reply":false},"next":{"ambiguous":true,"calls.one":true'
    b',"calls.two":false,"pending":true},"state":{"ambiguous":true,"calls.one":true,"calls.two'
    b'":false,"pending":true}},{"event":{"host":false,"reply":true},"next":{"ambiguous":true,"'
    b'calls.one":false,"calls.two":false,"pending":false},"state":{"ambiguous":true,"calls.one'
    b'":true,"calls.two":false,"pending":true}},{"event":{"host":true,"reply":false},"next":{"'
    b'ambiguous":true,"calls.one":true,"calls.two":true,"pending":false},"state":{"ambiguous":'
    b'true,"calls.one":true,"calls.two":false,"pending":true}},{"event":{"host":true,"reply":t'
    b'rue},"next":{"ambiguous":false,"calls.one":false,"calls.two":false,"pending":false},"sta'
    b'te":{"ambiguous":true,"calls.one":true,"calls.two":false,"pending":true}},{"event":{"hos'
    b't":false,"reply":false},"next":{"ambiguous":true,"calls.one":true,"calls.two":true,"pend'
    b'ing":false},"state":{"ambiguous":true,"calls.one":true,"calls.two":true,"pending":false}'
    b'},{"event":{"host":false,"reply":true},"next":{"ambiguous":true,"calls.one":true,"calls.'
    b'two":false,"pending":false},"state":{"ambiguous":true,"calls.one":true,"calls.two":true,'
    b'"pending":false}},{"event":{"host":true,"reply":false},"next":{"ambiguous":true,"calls.o'
    b'ne":true,"calls.two":true,"pending":false},"state":{"ambiguous":true,"calls.one":true,"c'
    b'alls.two":true,"pending":false}},{"event":{"host":true,"reply":true},"next":{"ambiguous"'
    b':false,"calls.one":false,"calls.two":false,"pending":false},"state":{"ambiguous":true,"c'
    b'alls.one":true,"calls.two":true,"pending":false}},{"event":{"host":false,"reply":false},'
    b'"next":{"ambiguous":true,"calls.one":true,"calls.two":true,"pending":true},"state":{"amb'
    b'iguous":true,"calls.one":true,"calls.two":true,"pending":true}},{"event":{"host":false,"'
    b'reply":true},"next":{"ambiguous":true,"calls.one":true,"calls.two":false,"pending":false'
    b'},"state":{"ambiguous":true,"calls.one":true,"calls.two":true,"pending":true}},{"event":'
    b'{"host":true,"reply":false},"next":{"ambiguous":true,"calls.one":true,"calls.two":true,"'
    b'pending":false},"state":{"ambiguous":true,"calls.one":true,"calls.two":true,"pending":tr'
    b'ue}},{"event":{"host":true,"reply":true},"next":{"ambiguous":false,"calls.one":false,"ca'
    b'lls.two":false,"pending":false},"state":{"ambiguous":true,"calls.one":true,"calls.two":t'
    b'rue,"pending":true}}],"state":["ambiguous","calls.one","calls.two","pending"]}'
)
IDLE = {"ambiguous": False, "calls.one": False, "calls.two": False, "pending": False}
CALL, RESPONSE = {"host": True, "reply": False}, {"host": False, "reply": True}
REQUEST, END = {"host": False, "reply": False}, {"host": True, "reply": True}


def load_table(runtime_path=None, projection=None):
    """The pinned table, or ValueError. Nothing is executed before both digests match."""
    runtime_path = Path(runtime_path or Path(__file__).with_name("warrant_mcp_table.py"))
    projection = TABLE_PROJECTION if projection is None else projection
    source = runtime_path.read_bytes()
    if hashlib.sha256(source).hexdigest() != TABLE_RUNTIME_SHA256:
        raise ValueError(f"table runtime {runtime_path} does not match the pinned digest")
    if hashlib.sha256(projection).hexdigest() != TABLE_PROJECTION_SHA256:
        raise ValueError("table projection does not match the pinned digest")
    namespace = {"__name__": "warrant_mcp_table"}
    exec(compile(source, str(runtime_path), "exec"), namespace)
    return namespace["ProjectionMachine"].from_bytes(projection)


def run_proxy(server_cmd, sealer, table=None):
    """Spawn the downstream server and relay JSON-RPC both ways, sealing A2+
    tools/call results as they pass server->host."""
    table = table or load_table()                # before any server exists
    proc = subprocess.Popen(server_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=None, bufsize=1, text=True)
    ids = {}                                     # request id -> [table state, held call or None]
    plock = threading.Lock()

    def step(mid, event):
        """One table step for this id; returns (previous state, next state, held call)."""
        state, held = ids.get(mid, (IDLE, None))
        after = table.step(state, event)
        if after == IDLE:
            ids.pop(mid, None)
        else:
            ids[mid] = (after, held)
        return state, after, held

    def on_host_line(raw):                        # host -> server: note tools/call
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("method") == "tools/call" and "id" in msg:
            params = msg.get("params") or {}
            call = (params.get("name", ""), params.get("arguments", {}), int(time.time()))
            unreturned = []
            with plock:
                before, after, held = step(msg["id"], CALL)
                if before["pending"] and held and after["ambiguous"]:
                    unreturned.append(held)      # displaced: its response can no longer be told apart
                # (a held call the table neither keeps nor marks ambiguous is overwritten:
                # that is what the table says, and what this file did before the table)
                if after["pending"]:
                    ids[msg["id"]] = (after, call)
                else:
                    unreturned.append(call)
                    if msg["id"] in ids:
                        ids[msg["id"]] = (after, None)
            for tool, tinput, ts in unreturned:
                sealer.record_unreturned(tool, tinput, ts, ambiguous=after["ambiguous"])

    def on_server_line(raw):                       # server -> host: seal the result
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        # Only a RESPONSE resolves a pending call. A server may send its own
        # requests (MCP 2025-03-26: either side may `ping`) and notifications
        # on this channel, and request ids belong to the requesting direction --
        # a server ping with id 1 is not the answer to the host's tools/call 1.
        # Both are forwarded untouched; neither touches `pending`.
        if not isinstance(msg, dict):
            return
        mid = msg.get("id")
        is_response = "method" not in msg and ("result" in msg or "error" in msg)
        if mid is None:
            return
        if "method" not in msg and not is_response:
            return
        with plock:
            if mid not in ids:
                return                           # not a call this proxy saw: nothing to pair
            before, after, held = step(mid, RESPONSE if is_response else REQUEST)
            if is_response and before["ambiguous"]:
                call, unpaired = None, True
            elif before["pending"] and not after["pending"]:
                call, unpaired = held, False     # the table resolves the held call with this message
            else:
                call, unpaired = None, False
            if mid in ids and not after["pending"]:
                ids[mid] = (after, None)
        result = msg.get("result", msg.get("error"))
        is_error = "error" in msg or bool((msg.get("result") or {}).get("isError"))
        if unpaired:
            sealer.record_unpaired(mid, result, is_error)
            return
        if not call:
            return
        tool, tinput, ts = call
        try:
            wid = sealer.seal(tool, tinput, result, is_error, ts=ts)
        except Exception as ex:                  # attributed here; the pump still forwards
            sealer.record_failure(tool, ex)
            print(f"warrant-mcp: seal error on {tool!r}: {ex}", file=sys.stderr)
            return
        if wid:
            print(f"warrant-mcp: sealed {tool} -> {wid[:12]}", file=sys.stderr)

    def on_error(raw, ex):                         # anything on_*_line did not attribute
        sealer.record_failure("<unattributed line>", ex)

    def upstream():
        _pump_and_forward(sys.stdin, proc.stdin, on_host_line, on_error)
        try:
            proc.stdin.close()            # host EOF -> let the downstream server exit
        except Exception:
            pass

    t_up = threading.Thread(target=upstream, daemon=True)
    t_up.start()
    _pump_and_forward(proc.stdout, sys.stdout, on_server_line, on_error)   # blocks until server EOF
    sealer.downstream_returncode = proc.wait()
    # Server EOF: whatever the host sent and never got answered is not a
    # non-event. The effect may have run (review probe: marker written, server
    # exited without a response) -- list it, classify it, refuse to call the
    # pack complete. Nothing is invented about its outcome.
    with plock:
        leftover = []
        for mid in list(ids):
            before, after, held = step(mid, END)
            if held:
                leftover.append(held)
        ids.clear()
    for tool, tinput, ts in leftover:
        sealer.record_unreturned(tool, tinput, ts)
    sealer.write_manifest()
    why = sealer.incomplete()
    print(f"warrant-mcp: session sealed {sealer.sealed} calls into {sealer.store.root}"
          f" (downstream exit {sealer.downstream_returncode})"
          + (f"; INCOMPLETE: {'; '.join(why)} -- see manifest" if why else ""),
          file=sys.stderr)
    return len(why)


def build_parser():
    """The CLI's argument parser, built WITHOUT dispatching anything.

    Exposed so a checker can validate a documented argv without running the
    command. Asking "does this parse?" by executing it is how a documentation
    check ends up creating files.
    """
    ap = argparse.ArgumentParser(prog="warrant-mcp", description=__doc__.splitlines()[0], allow_abbrev=False)
    ap.add_argument("--store", required=True, help="evidence-pack dir (.warrants inside)")
    ap.add_argument("--actor", required=True)
    ap.add_argument("--key", required=True, help="Ed25519 seed file (warrant keygen)")
    ap.add_argument("--effects", help="JSON map: tool name -> [effect,...]")
    ap.add_argument("--ceiling", default="A2", choices=list(ORDER),
                    help="seal calls of this class and above (default A2)")
    ap.add_argument("server", nargs=argparse.REMAINDER,
                    help="-- <downstream MCP server command>")
    return ap


def parse_cli(argv=None):
    """Parse an argv AND apply the pure post-parse invariants. No side effects.

    `build_parser().parse_args()` is not the whole CLI contract: a command can
    parse and still be rejected a line later by a check main() performs. A
    checker that stops at parse_args therefore reports a surface the CLI does
    not actually accept -- warrant-mcp with no downstream command parsed cleanly
    here while the real CLI exited 2 (Codex release-surface re-gate 2).

    So both the checker and main() go through this one function, and everything
    it does is pure: no filesystem, no subprocess, no network.
    """
    ap = build_parser()
    args = ap.parse_args(argv)
    server_cmd = args.server[1:] if args.server and args.server[0] == "--" else args.server
    if not server_cmd:
        ap.error("provide the downstream server command after --")
    return args, server_cmd


def main(argv=None):
    args, server_cmd = parse_cli(argv)
    effects_map = json.loads(Path(args.effects).read_text()) if args.effects else {}
    try:
        validate_effects_map(effects_map)
    except ValueError as ex:
        print(f"warrant-mcp: {ex}", file=sys.stderr)
        return 2
    try:
        table = load_table()                     # before any server is spawned or any byte is sealed
    except (OSError, ValueError) as ex:
        print(f"warrant-mcp: refusing to start: {ex}", file=sys.stderr)
        return 2
    store_dir = Path(args.store) / ".warrants"
    sealer = Sealer(store_dir, args.actor, args.key, effects_map, args.ceiling)
    incomplete = run_proxy(server_cmd, sealer, table)
    # 0: every consequential call the host sent was answered and sealed. 3: the
    # stream was kept but the pack is incomplete (a seal failed, or a call went
    # downstream and was never answered) -- a consumer must not read it as whole.
    return 3 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
