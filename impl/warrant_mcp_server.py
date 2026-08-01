#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 s0fractal. See LICENSE at the repository root.
#
# This header is on this file and not on its siblings for one reason: this file
# travels. It ships as a flat top-level module in the `warrant-verify` wheel and
# lands in a site-packages directory shared with other projects' files, and the
# README still invites a reader to run it straight out of a checkout. It does not
# establish a repo-wide convention.
"""warrant-mcp-server — file and verify signed decision records from any MCP client.

Point an MCP host (Claude Code, Claude Desktop, any agent runtime) at this
command and the agent gets three tools:

  warrant_file_decision   file a signed warrant (propose/accept/reject/supersede)
  warrant_verify_store    verify a store; returns the warrant.verify-report@v0 JSON
  warrant_show_reason     show a warrant's reasons; re-executes ski@v1 checks

NOT to be confused with `warrant-mcp` (module `warrant_mcp`), which is a different
program in the same distribution: that one is a *sealing proxy* — it wraps some
OTHER MCP server and seals the tool-calls passing through it from the outside.
This one is a *server*: the agent connects to it and files its own decisions
deliberately. `warrant-mcp` takes a downstream server command after `--` and
refuses to start without one; `warrant-mcp-server` takes no downstream command at
all. If you are choosing between them: seal someone else's server -> `warrant-mcp`;
give the agent decision records of its own -> `warrant-mcp-server`.

Transport is MCP's stdio framing: newline-delimited JSON-RPC 2.0, requests on
stdin, responses on stdout, logs on stderr. Standard library only.

Everything goes through the warrant CLI as a subprocess — never through imported
internals — so this server tracks the released command surface and nothing else.

    pip install warrant-verify
    warrant-mcp-server --store /abs/path/.warrants \
        [--key agent.key] [--actor me@host] [--warrant-cli /path/to/warrant]

    # or, from a checkout, without installing:
    python3 impl/warrant_mcp_server.py --store .warrants

Trust model, honestly: this process signs with a locally held Ed25519 key. If no
--key/WARRANT_KEY is configured, the first filing generates one next to the
store (never inside it — evidence packs must not ship keys) and says so in the
result. Any process on this host that can read that file can sign as this actor.
See integrations/mcp-server/README.md and SECURITY.md.
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

# Kept equal to the distribution version and to both version fields of
# `integrations/mcp-server/server.json` — `tools/doc_counts.py` fails if any of
# the four drift. A registry manifest naming a package version that is not the
# one this module ships is a listing that points at the wrong artifact.
__version__ = "0.9.0"
PROTOCOL_VERSION = "2025-06-18"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
SUBPROCESS_TIMEOUT = 120


# ---------- configuration ----------
class Config:
    def __init__(self, store, key, actor, cli_cmd):
        self.store = store          # str: store path handed to `warrant --store`
        self.key = key              # str|None: Ed25519 seed file (may be created)
        self.actor = actor          # str: default actor id
        self.cli_cmd = cli_cmd      # list[str]: argv prefix for the warrant CLI
        self.key_note = None        # set once if the key was auto-generated


def resolve_cli(explicit):
    """Locate the warrant CLI. First hit wins:
      1. --warrant-cli / WARRANT_CLI (a warrant.py path, or an executable)
      2. `warrant.py` SITTING BESIDE this module
      3. an installed `warrant` on PATH
    A *.py path runs under the current interpreter; anything else runs as-is.

    Rule 2 is one rule covering both worlds on purpose. `warrant.py` is a flat
    module of the same distribution, so it is beside this file in `impl/` of a
    checkout and beside it again in site-packages once installed — the same
    bytes the `warrant` console script dispatches to, reached without depending
    on PATH (an MCP host may launch this server with an empty environment).
    The previous form walked `parents[2]/impl/warrant.py` from
    `integrations/mcp-server/`, which resolves to nothing once installed.
    """
    cand = explicit or os.environ.get("WARRANT_CLI")
    if cand:
        if cand.endswith(".py"):
            p = Path(cand)
            if not p.is_file():
                sys.exit(f"warrant CLI not found: {cand}")
            return [sys.executable, str(p)]
        return [cand]
    sibling = Path(__file__).resolve().parent / "warrant.py"
    if sibling.is_file():
        return [sys.executable, str(sibling)]
    on_path = shutil.which("warrant")
    if on_path:
        return [on_path]
    sys.exit("no warrant CLI found: pass --warrant-cli, set WARRANT_CLI, "
             "or `pip install warrant-verify`")


def run_cli(cfg, args, store=None, timeout=SUBPROCESS_TIMEOUT):
    """Run one warrant CLI command. Returns CompletedProcess (never raises on
    a nonzero exit — the caller decides what a failure means)."""
    argv = cfg.cli_cmd + ["--store", store or cfg.store] + args
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def ensure_store(cfg):
    """`warrant init` is mkdir -p semantics; only run it when the store is absent
    so an existing store's contents are never touched."""
    if not (Path(cfg.store) / "records").is_dir():
        r = run_cli(cfg, ["init"])
        if r.returncode != 0:
            raise ToolError(f"warrant init failed: {(r.stderr or r.stdout).strip()}")


def ensure_key(cfg):
    """Return the signing-key path, generating one (via the CLI) if none was
    configured. The generated key lands NEXT TO the store, never inside it: the
    store is an evidence pack and packs must not ship anything key-shaped."""
    if cfg.key:
        return cfg.key
    store = Path(cfg.store).resolve()
    keypath = store.parent / "warrant-mcp-server.key"
    if not keypath.is_file():
        r = run_cli(cfg, ["keygen", "--out", str(keypath)])
        if r.returncode != 0:
            raise ToolError(f"keygen failed: {(r.stderr or r.stdout).strip()}")
        pub = r.stdout.strip()
        cfg.key_note = (f"no signing key was configured, so one was generated at "
                        f"{keypath} ({pub}). Anyone who can read that file can "
                        f"sign as this actor; pass --key to use your own.")
        log(cfg.key_note)
    cfg.key = str(keypath)
    return cfg.key


# ---------- tools ----------
class ToolError(Exception):
    """A tool-level failure: reported as an isError result, not a protocol error."""


TOOLS = [
    {
        "name": "warrant_file_decision",
        "description": (
            "File a signed, content-addressed decision record (a warrant) into the "
            "store. Use `propose` for a new subject; `accept`/`reject`/`supersede` "
            "usually answer a prior warrant (pass `prior`), inheriting its subject "
            "and policy unless overridden. Reasons are prose strings; a re-runnable "
            "reason is a check blob (`check` + `runtime` + `verdict`). Returns the "
            "warrant id (the record's hash) plus a summary."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "decision": {"type": "string",
                             "enum": ["propose", "accept", "reject", "supersede"],
                             "description": "The decision being recorded."},
                "subject": {"type": "string",
                            "description": "What is decided about: a file path (its "
                                           "bytes get stored) or a hex64 hash. "
                                           "Required for propose; accept/reject with "
                                           "`prior` inherit the prior's subject."},
                "subject_text": {"type": "string",
                                 "description": "Inline subject content, stored as a "
                                                "blob (alternative to `subject`)."},
                "note": {"type": "string", "maxLength": 200,
                         "description": "Short human label for the subject."},
                "policy": {"type": "string",
                           "description": "The policy in force: a file path or hex64 "
                                          "hash (becomes `under`). Required for "
                                          "propose; with `prior` it defaults to the "
                                          "prior's policy."},
                "reasons": {"type": "array", "items": {"type": "string"},
                            "description": "Prose reasons. A reject/supersede needs "
                                           "at least one reason (prose or check)."},
                "check": {"type": "string",
                          "description": "Optional re-runnable reason: hex64 hash or "
                                         "file path of a check blob."},
                "runtime": {"type": "string", "enum": ["cmd@v1", "ski@v1"],
                            "description": "Check runtime (default cmd@v1). ski@v1 "
                                           "is re-executed at filing time and the "
                                           "filing is refused if the verdict "
                                           "claimed here does not reproduce."},
                "verdict": {"type": "string", "enum": ["pass", "fail"],
                            "description": "The check's verdict (default pass)."},
                "evidence": {"type": "array", "items": {"type": "string"},
                             "description": "Evidence: file paths or hex64 hashes."},
                "prior": {"type": "string",
                          "description": "WarrantID (hex64) this decision answers."},
                "actor": {"type": "string",
                          "description": "Actor id (defaults to server config)."},
            },
            "required": ["decision"],
        },
    },
    {
        "name": "warrant_verify_store",
        "description": (
            "Verify every hash, signature and link in a warrant store. Returns the "
            "machine-readable warrant.verify-report@v0 object (closed schema: "
            "report, grade, ok, records, errors, warnings, findings). ok == "
            "(errors == 0); a missing or uninitialized store fails closed "
            "(ok:false)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "store_path": {"type": "string",
                               "description": "Store to verify (default: the "
                                              "server's configured store)."},
            },
        },
    },
    {
        "name": "warrant_show_reason",
        "description": (
            "Show why a warrant was filed: its decision, actor, and reasons, plus "
            "the verified `why` chain (decision -> reasons -> policy -> priors). "
            "Each ski@v1 check reason is RE-EXECUTED locally and the fresh verdict "
            "is returned next to the filed one. cmd@v1 checks are not re-run (they "
            "name a command, not a portable term); prose is returned as-is."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "warrant_id": {"type": "string", "pattern": "^[0-9a-f]{64}$",
                               "description": "The warrant's hex64 id."},
                "rerun": {"type": "boolean",
                          "description": "Re-execute ski@v1 checks (default true)."},
            },
            "required": ["warrant_id"],
        },
    },
]


def tool_file_decision(cfg, a):
    decision = a.get("decision")
    if decision not in ("propose", "accept", "reject", "supersede"):
        raise ToolError("decision must be propose|accept|reject|supersede")
    ensure_store(cfg)
    key = ensure_key(cfg)

    tmp = None
    args = [decision]
    try:
        prior = a.get("prior")
        if prior is not None:
            if not HEX64.match(str(prior)):
                raise ToolError("prior must be a hex64 WarrantID")
            if decision == "propose":
                raise ToolError("propose does not take a prior; "
                                "use accept/reject/supersede to answer one")
            args.append(prior)

        subject = a.get("subject")
        if a.get("subject_text") is not None:
            if subject is not None:
                raise ToolError("pass subject or subject_text, not both")
            fd, tmp = tempfile.mkstemp(prefix="warrant-subject-")
            with os.fdopen(fd, "w") as f:
                f.write(a["subject_text"])
            subject = tmp
        if subject is not None:
            args += ["--subject", str(subject)]
        if a.get("note") is not None:
            args += ["--note", str(a["note"])]
        if a.get("policy") is not None:
            args += ["--under", str(a["policy"])]
        for r in a.get("reasons") or []:
            args += ["--reason", str(r)]
        if a.get("check") is not None:
            args += ["--check", str(a["check"]),
                     "--runtime", a.get("runtime") or "cmd@v1",
                     "--verdict", a.get("verdict") or "pass"]
        for ev in a.get("evidence") or []:
            args += ["--evidence", str(ev)]
        args += ["--actor", str(a.get("actor") or cfg.actor), "--key", key]

        r = run_cli(cfg, args)
    finally:
        if tmp:
            os.unlink(tmp)

    if r.returncode != 0:
        raise ToolError(f"warrant {decision} failed: "
                        f"{(r.stderr.strip() or r.stdout.strip() or 'no output')}")
    wid = r.stdout.strip().splitlines()[-1]
    if not HEX64.match(wid):
        raise ToolError(f"unexpected CLI output (no warrant id): {r.stdout!r}")
    out = {"warrant_id": wid, "decision": decision,
           "actor": a.get("actor") or cfg.actor,
           "store": str(Path(cfg.store).resolve())}
    warning = r.stderr.strip()
    if warning:
        out["warning"] = warning        # e.g. UNVERIFIABLE prose-only reject
    if cfg.key_note:
        out["key_note"], cfg.key_note = cfg.key_note, None
    return out


def tool_verify_store(cfg, a):
    store = a.get("store_path") or cfg.store
    # --store-mode --json: exactly one verify-report@v0 object on stdout, fail-
    # closed on a missing/uninitialized store. Exit 1 with a valid report is a
    # verification outcome (ok:false), not a tool failure.
    r = run_cli(cfg, ["verify", "--store-mode", "--json"], store=store)
    line = r.stdout.strip()
    try:
        report = json.loads(line)
    except ValueError:
        raise ToolError("verify produced no verify-report@v0 object: "
                        f"{(r.stderr.strip() or line or 'no output')}")
    return report


def tool_show_reason(cfg, a):
    wid = a.get("warrant_id", "")
    if not HEX64.match(str(wid)):
        raise ToolError("warrant_id must be hex64")
    record_path = Path(cfg.store) / "records" / f"{wid}.json"
    if not record_path.is_file():
        raise ToolError(f"warrant {wid} not in store {cfg.store}")
    # The record is read from the store's documented plain-file format (SPEC §6);
    # everything *interpretive* — chain verification, check re-execution — goes
    # through the CLI.
    try:
        body = json.loads(record_path.read_text(encoding="utf-8"))["body"]
    except (ValueError, KeyError, TypeError, UnicodeError, OSError) as ex:
        raise ToolError(f"unreadable record {wid}: {ex}")

    out = {"warrant_id": wid,
           "decision": body.get("decision"),
           "actor": (body.get("actor") or {}).get("id"),
           "subject": body.get("subject"),
           "under": body.get("under"),
           "reasons": body.get("because"),
           "prior": body.get("prior")}

    why = run_cli(cfg, ["why", wid])
    out["why"] = why.stdout.rstrip()
    # why exits nonzero when a link is missing or a signature fails — the walk
    # could not verify the chain it printed. Surface that, don't swallow it.
    out["chain_verified"] = (why.returncode == 0)

    if a.get("rerun", True):
        reruns = []
        for reason in body.get("because") or []:
            if not (isinstance(reason, dict) and reason.get("kind") == "check"):
                continue
            entry = {"check": reason.get("check"),
                     "runtime": reason.get("runtime"),
                     "filed_verdict": reason.get("verdict")}
            if reason.get("runtime") == "ski@v1":
                r = run_cli(cfg, ["check", str(reason.get("check"))])
                # prints: "<pass|fail>  result=<hex64>  atp_spent=<n>"; exit
                # status encodes the verdict (fail -> 1), so "reproduced" is a
                # comparison of verdicts, not of exit codes.
                entry["rerun"] = (r.stdout.strip() or r.stderr.strip())
                got = (r.stdout.split() or [""])[0]
                entry["reproduced"] = (got in ("pass", "fail")
                                       and got == reason.get("verdict"))
            else:
                entry["rerun"] = ("not re-executed: cmd@v1 names a command in an "
                                  "environment, not a portable term")
            reruns.append(entry)
        out["reruns"] = reruns
    return out


TOOL_IMPL = {
    "warrant_file_decision": tool_file_decision,
    "warrant_verify_store": tool_verify_store,
    "warrant_show_reason": tool_show_reason,
}


# ---------- JSON-RPC 2.0 over stdio (MCP framing: one message per line) ----------
def log(msg):
    print(f"warrant-mcp-server: {msg}", file=sys.stderr, flush=True)


def reply(mid, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": mid}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg, ensure_ascii=True,
                                separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle(cfg, msg):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}

    if method == "initialize":
        pv = params.get("protocolVersion")
        reply(mid, {"protocolVersion": pv if isinstance(pv, str) else PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "warrant", "version": __version__}})
    elif method == "ping":
        reply(mid, {})
    elif method == "tools/list":
        reply(mid, {"tools": TOOLS})
    elif method == "tools/call":
        name = params.get("name")
        impl = TOOL_IMPL.get(name)
        if impl is None:
            reply(mid, error={"code": -32602, "message": f"unknown tool: {name}"})
            return
        try:
            result = impl(cfg, params.get("arguments") or {})
            text = json.dumps(result, indent=2, ensure_ascii=True)
            reply(mid, {"content": [{"type": "text", "text": text}],
                        "isError": False})
        except ToolError as ex:
            reply(mid, {"content": [{"type": "text", "text": str(ex)}],
                        "isError": True})
        except subprocess.TimeoutExpired:
            reply(mid, {"content": [{"type": "text",
                                     "text": "warrant CLI timed out"}],
                        "isError": True})
    elif mid is not None:                      # unknown *request* -> error
        reply(mid, error={"code": -32601, "message": f"method not found: {method}"})
    # unknown notifications (incl. notifications/initialized): ignore, per spec


def serve(cfg):
    log(f"serving store={cfg.store} actor={cfg.actor} "
        f"cli={' '.join(cfg.cli_cmd)}")
    for raw in sys.stdin:
        if not raw.strip():
            continue
        try:
            msg = json.loads(raw)
        except ValueError:
            reply(None, error={"code": -32700, "message": "parse error"})
            continue
        if not isinstance(msg, dict):
            reply(None, error={"code": -32600, "message": "invalid request"})
            continue
        try:
            handle(cfg, msg)
        except Exception as ex:                # a bug must not kill the transport
            log(f"internal error on {msg.get('method')}: {ex}")
            if msg.get("id") is not None:
                reply(msg["id"], error={"code": -32603,
                                        "message": f"internal error: {ex}"})


def build_parser():
    ap = argparse.ArgumentParser(
        prog="warrant-mcp-server", allow_abbrev=False,
        description=__doc__.splitlines()[0]
        + "  NOT `warrant-mcp`, which is the sealing proxy for someone else's "
          "MCP server; this one serves the agent's own decisions and takes no "
          "downstream command.")
    ap.add_argument("--store", default=os.environ.get("WARRANT_STORE", ".warrants"),
                    help="warrant store to file into / verify (env WARRANT_STORE; "
                         "default .warrants, relative to the server's cwd)")
    ap.add_argument("--key", default=os.environ.get("WARRANT_KEY"),
                    help="Ed25519 seed file for signing (env WARRANT_KEY). If "
                         "absent, one is generated next to the store on first "
                         "filing and the result says so.")
    ap.add_argument("--actor", default=os.environ.get(
                        "WARRANT_ACTOR", f"mcp-client@{socket.gethostname()}"),
                    help="default actor id for filed warrants (env WARRANT_ACTOR)")
    ap.add_argument("--warrant-cli", default=None,
                    help="warrant CLI: a warrant.py path or an executable (env "
                         "WARRANT_CLI). Default: the warrant.py beside this "
                         "module (impl/ in a checkout, site-packages once "
                         "installed), else `warrant` on PATH.")
    return ap


def parse_cli(argv=None):
    """Parse an argv AND apply the pure post-parse invariants. No side effects.

    Same contract as `warrant` and `warrant-mcp`: `tools/check_release_surface.py`
    calls this to decide whether a documented invocation is one the command
    actually accepts, and main() goes through the same function, so the surface
    that is checked is the surface that runs. Nothing here touches the
    filesystem, spawns a process, or opens a socket.
    """
    ap = build_parser()
    args = ap.parse_args(argv)

    # An empty --store is not a store. Without this, `--store ""` parses, and
    # `Path("")` is the current directory, so the server would silently file
    # into ./records instead of refusing.
    if not str(args.store).strip():
        ap.error("--store must name a path (got an empty string)")
    return args


def main(argv=None):
    args = parse_cli(argv)
    cfg = Config(args.store, args.key, args.actor, resolve_cli(args.warrant_cli))
    serve(cfg)


if __name__ == "__main__":
    main()
