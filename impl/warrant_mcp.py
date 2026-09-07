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
            "observation_complete": not self.seal_failures,
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
        dst.write(raw)
        dst.flush()


def run_proxy(server_cmd, sealer):
    """Spawn the downstream server and relay JSON-RPC both ways, sealing A2+
    tools/call results as they pass server->host."""
    proc = subprocess.Popen(server_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=None, bufsize=1, text=True)
    pending = {}                                 # request id -> (tool, input, ts)
    plock = threading.Lock()

    def on_host_line(raw):                        # host -> server: note tools/call
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        if msg.get("method") == "tools/call" and "id" in msg:
            params = msg.get("params") or {}
            with plock:
                pending[msg["id"]] = (params.get("name", ""),
                                      params.get("arguments", {}), int(time.time()))

    def on_server_line(raw):                       # server -> host: seal the result
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        mid = msg.get("id")
        with plock:
            call = pending.pop(mid, None) if mid is not None else None
        if not call:
            return
        tool, tinput, ts = call
        result = msg.get("result", msg.get("error"))
        is_error = "error" in msg or bool((msg.get("result") or {}).get("isError"))
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
    proc.wait()
    sealer.write_manifest()
    lost = len(sealer.seal_failures)
    print(f"warrant-mcp: session sealed {sealer.sealed} calls into "
          f"{sealer.store.root}" + (f"; {lost} call(s) NOT sealed (see manifest "
          "seal_failure_log) -- the pack is incomplete" if lost else ""), file=sys.stderr)
    return lost


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
    store_dir = Path(args.store) / ".warrants"
    sealer = Sealer(store_dir, args.actor, args.key, effects_map, args.ceiling)
    lost = run_proxy(server_cmd, sealer)
    # 0: every observed consequential call is in the pack. 3: the stream was
    # kept but the pack is incomplete -- a consumer must not read it as whole.
    return 3 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
