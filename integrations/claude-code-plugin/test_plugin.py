#!/usr/bin/env python3
"""The Claude Code witness plugin: what it files, what it refuses to claim.

WHAT IS ASSERTED
  1. The hook never speaks: for every event, valid or not, stdout is empty and
     the exit status is 0 -- it cannot allow, deny or delay a tool call.
  2. PermissionDenied files exactly one reject whose reason quotes the
     harness's reason, signed by one custody (sanction_independent false).
  3. PermissionRequest then PostToolUse with the same session, tool and input
     files one accept; a PostToolUse nobody asked about files nothing; a
     changed input does not match (negative control).
  4. An ask that never executes stays an open ask in decisions.py.
  5. The store verifies with 0 errors, and a tampered record turns it red.
  6. A fresh install with no store reports EMPTY, not errors; a store
     directory without records/ is still reported as a problem.
  6b. A missing warrant CLI files nothing and breaks nothing; decisions.py
     says NOT RUN instead of reporting a clean store.
  7. A huge tool input is bound by SHA-256, not stored inline.
  9. Unprompted executions: only checks and consequential commands are filed,
     with mode, success and a hash of the response; the output is never
     stored. SessionStart recalls recent denials as labelled data and prints
     nothing when there are none. The command classifier holds a table.
  8. The manifests parse.

The plugin records and verifies in the Warrant 0.x format. Its CLI is the
published `warrant-verify` 0.12.0, named by WARRANT_PLUGIN_CLI (CI installs it
in its own environment); this repository no longer carries that implementation.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WITNESS = HERE / "scripts" / "witness.py"
DECISIONS = HERE / "scripts" / "decisions.py"
CLI = os.environ.get("WARRANT_PLUGIN_CLI")
if not CLI:
    print("UNRUN: set WARRANT_PLUGIN_CLI to a warrant-verify 0.12.0 `warrant` executable")
    sys.exit(3)
ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def env_for(home, cli=CLI):
    e = {k: v for k, v in os.environ.items() if k not in ("WARRANT_CLI", "TRACEPARENT")}
    e["WARRANT_CC_HOME"] = str(home)
    e["PATH"] = "/usr/bin:/bin"          # no `warrant` on PATH unless given
    if cli:
        e["WARRANT_CLI"] = cli
    return e


def hook(home, event, cli=CLI, raw=None):
    r = subprocess.run([sys.executable, str(WITNESS)], input=raw if raw is not None else json.dumps(event),
                       capture_output=True, text=True, env=env_for(home, cli))
    return r


def decisions(home, cli=CLI):
    r = subprocess.run([sys.executable, str(DECISIONS), "--json", "--hours", "1"],
                       capture_output=True, text=True, env=env_for(home, cli))
    return json.loads(r.stdout)


def ev(name, cmd="git push", sid="sess-1", **kw):
    e = {"hook_event_name": name, "session_id": sid, "cwd": "/tmp", "tool_name": "Bash",
         "tool_input": {"command": cmd}, "permission_mode": "default"}
    e.update(kw)
    return e


def records(home):
    d = Path(home) / "store" / "records"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def main():
    tmp = Path(tempfile.mkdtemp(prefix="cc-witness-"))

    # 1. silence on every event shape
    h0 = tmp / "silent"
    outs = [hook(h0, None, raw=raw) for raw in ("", "not json", "[]", '{"hook_event_name":"Stop"}')]
    outs += [hook(h0, ev("PermissionRequest")), hook(h0, ev("PostToolUse", tool_use_id="toolu_x"))]
    check("hook prints nothing and exits 0 on every input",
          all(r.returncode == 0 and r.stdout == "" for r in outs),
          [(r.returncode, r.stdout[:40]) for r in outs])

    # 1b. fresh install: no store is not a broken store; a gutted one still is
    fresh = decisions(tmp / "fresh")
    check("a fresh install reports EMPTY, not errors",
          fresh["verify"]["status"] == "EMPTY" and fresh["decisions"] == [], fresh["verify"])
    gutted = tmp / "gutted" / "store"
    gutted.mkdir(parents=True)
    g = decisions(tmp / "gutted")
    check("a store directory without records/ is still reported, not called empty",
          g["verify"]["status"] in ("ERRORS", "UNRUN") and g["verify"]["status"] != "EMPTY", g["verify"])

    # 2. auto-mode denial
    h = tmp / "main"
    hook(h, ev("PermissionDenied", cmd="gh pr merge 95", tool_use_id="toolu_den",
               permission_mode="auto", reason="[Merge Without Review]"))
    rep = decisions(h)
    den = [r for r in rep["decisions"] if r["outcome"] == "denied"]
    check("PermissionDenied files one reject quoting the harness reason",
          len(den) == 1 and "[Merge Without Review]" in (den[0]["reason"] or "")
          and den[0]["tool_use_id"] == "toolu_den", den)
    keys = set()
    for p in records(h):
        for sig in json.loads(p.read_text()).get("sigs", []):
            keys.add(json.dumps({k: v for k, v in sig.items() if k != "sig"}, sort_keys=True))
    check("request and outcome are signed by one witness key (one custody, said so)",
          len(records(h)) == 2 and len(keys) == 1, keys)

    # 3. asked then executed; unasked; changed input
    hook(h, ev("PermissionRequest", cmd="rm -rf build"))
    hook(h, ev("PostToolUse", cmd="rm -rf build", tool_use_id="toolu_ok",
               tool_response={"stdout": ""}))
    hook(h, ev("PostToolUse", cmd="ls", tool_use_id="toolu_unasked"))
    hook(h, ev("PermissionRequest", cmd="npm view a"))
    hook(h, ev("PostToolUse", cmd="npm view b", tool_use_id="toolu_changed"))
    hook(h, ev("PermissionRequest", cmd="make deploy", sid="sess-2"))
    hook(h, ev("PostToolUse", cmd="make deploy", sid="sess-3", tool_use_id="toolu_other_sess"))
    rep = decisions(h)
    acc = [r for r in rep["decisions"] if r["outcome"] == "asked, then executed"]
    check("asked then executed files exactly one accept, bound to its tool_use_id",
          len(acc) == 1 and acc[0]["tool_use_id"] == "toolu_ok"
          and "cannot tell which" in acc[0]["reason"], acc)
    check("unasked, changed-input and other-session executions file nothing",
          not any(r["tool_use_id"] in ("toolu_unasked", "toolu_changed", "toolu_other_sess")
                  for r in rep["decisions"]), rep["decisions"])

    # 4. open asks
    opened = sorted(json.loads(r["input"])["command"] for r in rep["open_asks"])
    check("asks with no observed execution stay open, labelled as such",
          opened == ["make deploy", "npm view a"]
          and all("no execution observed" in r["outcome"] for r in rep["open_asks"]), opened)

    # failure path
    hook(h, ev("PermissionRequest", cmd="pytest"))
    hook(h, ev("PostToolUseFailure", cmd="pytest", tool_use_id="toolu_fail",
               error="Exit code 1", is_interrupt=True))
    rep = decisions(h)
    fail = [r for r in rep["decisions"] if r["tool_use_id"] == "toolu_fail"]
    check("an asked call that ran and failed is an accept that says it failed",
          len(fail) == 1 and "failure (interrupted)" in fail[0]["reason"], fail)

    # 4b. executions nobody asked about: only checks and consequential ones
    secret = "TOKEN=sk-live-do-not-store"
    hook(h, ev("PostToolUse", cmd="git push origin main", tool_use_id="toolu_push",
               permission_mode="auto", tool_response={"stdout": secret, "stderr": ""}))
    hook(h, ev("PostToolUseFailure", cmd="python3 tools/check.py", tool_use_id="toolu_chk",
               permission_mode="auto", error="Exit code 1", is_interrupt=False))
    hook(h, ev("PostToolUse", cmd="cat README.md | head", tool_use_id="toolu_cat",
               permission_mode="auto", tool_response={"stdout": "x"}))
    rep = decisions(h)
    ex = {r["tool_use_id"]: r for r in rep["decisions"] if r["outcome"] == "executed, no prompt"}
    import hashlib as _h
    want = _h.sha256(json.dumps({"stdout": secret, "stderr": ""}, sort_keys=True,
                                separators=(",", ":")).encode()).hexdigest()
    check("an unprompted push is witnessed: mode, success, response hash",
          "toolu_push" in ex and "(consequential) in auto mode" in ex["toolu_push"]["reason"]
          and "succeeded" in ex["toolu_push"]["reason"] and want in ex["toolu_push"]["reason"],
          ex.get("toolu_push"))
    check("an unprompted failing check is witnessed as failed",
          "toolu_chk" in ex and "(check)" in ex["toolu_chk"]["reason"]
          and "the tool failed" in ex["toolu_chk"]["reason"], ex.get("toolu_chk"))
    check("an unprompted ordinary command files nothing", "toolu_cat" not in ex, list(ex))
    stored = "".join(p.read_text(errors="replace") for p in (h / "store").rglob("*") if p.is_file())
    check("the witnessed output itself is never stored", secret not in stored)

    # 4c. session start recalls denials, as data; silent when there are none
    r = hook(h, {"hook_event_name": "SessionStart", "session_id": "new", "cwd": "/tmp",
                 "source": "startup"})
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"] if r.stdout else ""
    check("SessionStart recalls the recent denial as labelled data",
          r.returncode == 0 and "[Merge Without Review]" in ctx and "not instructions" in ctx
          and "gh pr merge 95" in ctx, r.stdout[:300])
    r0 = hook(tmp / "nodenials", {"hook_event_name": "SessionStart", "session_id": "n",
                                  "cwd": "/tmp", "source": "startup"})
    check("SessionStart with nothing to recall prints nothing", r0.returncode == 0 and r0.stdout == "",
          r0.stdout)

    # 5. verification, then tamper
    v = rep["verify"]
    check("the witness store verifies: 0 errors",
          v["status"] == "OK" and v["records"] == 10 and v["errors"] == 0, v)
    rec = records(h)[0]
    env = json.loads(rec.read_text())
    env["body"]["ts"] += 1
    rec.write_text(json.dumps(env))
    v2 = decisions(h)["verify"]
    check("a tampered record turns the store red", v2["status"] == "ERRORS", v2)

    # 6. no CLI
    hn = tmp / "nocli"
    r = hook(hn, ev("PermissionDenied", tool_use_id="toolu_n", reason="[x]"), cli=None)
    rep = decisions(hn, cli=None)
    check("without the warrant CLI: nothing filed, nothing broken, verify NOT RUN",
          r.returncode == 0 and r.stdout == "" and not records(hn)
          and rep["verify"]["status"] == "UNRUN" and "not filed" in (hn / "witness.log").read_text(),
          (r.returncode, rep["verify"]))

    # 7. size cap
    hb = tmp / "big"
    big = "x" * 70000
    hook(hb, ev("PermissionRequest", cmd=big))
    hook(hb, ev("PostToolUse", cmd=big, tool_use_id="toolu_big"))
    blobs = [p.read_text() for p in (hb / "store" / "blobs").iterdir()]
    subj = [json.loads(b) for b in blobs if '"warrant.tool-call@v0"' in b]
    check("a tool input over 64 KiB is bound by SHA-256, not inline",
          len(subj) == 1 and all(s["tool_input"].get("inline") is False for s in subj)
          and not any(big in b for b in blobs), [s.get("tool_input") for s in subj])

    # 7b. the classifier, case by case (both directions)
    sys.path.insert(0, str(HERE / "scripts"))
    from witness import classify_command
    table = {"git push origin x": "consequential", "cd a && git push": "consequential",
             "git -C ~/x push": "consequential", "gh pr merge 96 --squash": "consequential",
             "rm -rf build": "consequential", "deno publish --dry-run": "consequential",
             "pytest -q": "check", "npm --prefix js test": "check",
             "python3 tools/check.py": "check", "gh pr checks 97": "check",
             "FOO=1 cargo test": "check",
             "ls -la": None, "git status": None, "git log --grep push": None,
             "echo git push": None, "rm file": None, "gh pr view 1": None,
             "cat x | grep test": None, "python3 -c 'print(1)'": None, "x" * 70000: None}
    wrong = {k[:40]: (classify_command(k), v) for k, v in table.items() if classify_command(k) != v}
    check("command classifier: 20 cases, consequential / check / nothing", not wrong, wrong)

    # 8. manifests and vendored module
    for p in (HERE / ".claude-plugin" / "plugin.json", HERE / "hooks" / "hooks.json",
              ROOT / ".claude-plugin" / "marketplace.json"):
        try:
            json.loads(p.read_text())
            parsed = True
        except ValueError:
            parsed = False
        check(f"{p.relative_to(ROOT)} parses", parsed)

    print(f"\nCLAUDE-CODE-PLUGIN: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
