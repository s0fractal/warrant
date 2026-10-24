#!/usr/bin/env python3
"""Install the warrant-review Codex plugin and its waker on this machine (macOS), or remove them.

    python3 integrations/codex-plugin/install.py [--dry-run]
    python3 integrations/codex-plugin/install.py --uninstall

Install, from the checkout's HEAD commit (never its working tree: a dirty plugin path is refused):

  1. the marketplace (.agents/plugins/marketplace.json and integrations/codex-plugin) written by
     `git archive HEAD` to ~/.warrant/codex-marketplace, with INSTALLED.json naming the commit;
  2. ~/.codex/config.toml copied to ~/.codex/config.toml.warrant-backup-<UTC time>;
  3. `codex plugin marketplace add` of that directory and `codex plugin add warrant-review@warrant`;
  4. the [mcp_servers.warrant] table removed from ~/.codex/config.toml: the plugin registers the server
     `warrant` now (the same warrant-agent-mcp with the same ~/.warrant/codex-warrant.json; a server
     of that name in config.toml would shadow the plugin's);
  5. the waker's Python (~/.warrant/codex-waker/venv, cryptography only) and the launchd agent
     ~/Library/LaunchAgents/dev.s0fractal.warrant-codex-waker.plist, loaded: the waker runs at load
     and every five minutes.

Hold without uninstalling: `touch ~/.warrant/codex-waker/HOLD` (nothing is woken while it exists).
Stop the waker: `launchctl bootout gui/$(id -u)/dev.s0fractal.warrant-codex-waker`.
--uninstall unloads and removes the agent and the plugin; restoring config.toml is the backup's.
"""
import argparse
import datetime
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATHS = (".agents/plugins/marketplace.json", "integrations/codex-plugin")
MARKET = Path.home() / ".warrant" / "codex-marketplace"
HOME = Path.home() / ".warrant" / "codex-waker"
CONFIG = Path.home() / ".codex" / "config.toml"
LABEL = "dev.s0fractal.warrant-codex-waker"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
PLUGIN = "warrant-review@warrant"
CRYPTOGRAPHY = "cryptography==50.0.2"
TABLE = re.compile(r"^\[mcp_servers\.warrant\]\n(?:(?!\[)[^\n]*\n)*", re.M)


def run(*cmd, dry=False, **kw):
    print("+ " + " ".join(str(c) for c in cmd))
    if not dry:
        return subprocess.run([str(c) for c in cmd], check=True, **kw)
    return None


def head():
    commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, check=True,
                            text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--", *PATHS], capture_output=True,
                           check=True, text=True).stdout
    if dirty:
        sys.exit(f"refused: the plugin's paths differ from HEAD {commit[:12]}:\n{dirty}")
    return commit


def marketplace(commit, dry):
    data = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", commit, *PATHS], capture_output=True,
                          check=True).stdout
    print(f"+ git archive {commit[:12]} {' '.join(PATHS)} -> {MARKET}")
    if dry:
        return
    shutil.rmtree(MARKET, ignore_errors=True)
    MARKET.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(MARKET, filter="data")
    trees = {p: subprocess.run(["git", "-C", str(ROOT), "rev-parse", f"{commit}:{p}"], capture_output=True, check=True,
                               text=True).stdout.strip() for p in PATHS}
    (MARKET / "INSTALLED.json").write_text(json.dumps({"source": "https://github.com/s0fractal/warrant", "commit": commit,
                                                       "objects": trees}, indent=1) + "\n")


def config_without_server(dry):
    text = CONFIG.read_text()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = CONFIG.with_name(f"config.toml.warrant-backup-{stamp}")
    print(f"+ cp {CONFIG} {backup}")
    if not dry:
        shutil.copy2(CONFIG, backup)
    new = TABLE.sub("", text, count=1)
    if new != text:
        print(f"+ remove [mcp_servers.warrant] from {CONFIG} (the plugin registers `warrant`)")
        if not dry:
            CONFIG.write_text(new)


def plist(python):
    env = {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin", "HOME": str(Path.home())}
    args = [python, str(MARKET / "integrations" / "codex-plugin" / "waker" / "waker.py")]
    items = "".join(f"<string>{a}</string>" for a in args)
    envs = "".join(f"<key>{k}</key><string>{v}</string>" for k, v in env.items())
    log = HOME / "logs" / "launchd.log"
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
            f"<key>Label</key><string>{LABEL}</string><key>ProgramArguments</key><array>{items}</array>"
            f"<key>EnvironmentVariables</key><dict>{envs}</dict><key>StartInterval</key><integer>300</integer>"
            f"<key>RunAtLoad</key><true/><key>StandardOutPath</key><string>{log}</string>"
            f"<key>StandardErrorPath</key><string>{log}</string></dict></plist>\n")


def domain():
    return f"gui/{os.getuid()}"


def install(dry):
    commit = head()
    marketplace(commit, dry)
    config_without_server(dry)
    listed = subprocess.run(["codex", "plugin", "marketplace", "list"], capture_output=True, text=True).stdout
    if str(MARKET) not in listed:
        run("codex", "plugin", "marketplace", "add", MARKET, dry=dry)
    run("codex", "plugin", "add", PLUGIN, dry=dry)
    venv = HOME / "venv"
    if not (venv / "bin" / "python").is_file():
        run(sys.executable, "-m", "venv", venv, dry=dry)
    run(venv / "bin" / "python", "-m", "pip", "install", "--quiet", "--only-binary", ":all:", CRYPTOGRAPHY, dry=dry)
    (HOME / "logs").mkdir(parents=True, exist_ok=True)
    print(f"+ write {PLIST}")
    if not dry:
        PLIST.parent.mkdir(parents=True, exist_ok=True)
        PLIST.write_text(plist(str(venv / "bin" / "python")))
    subprocess.run(["launchctl", "bootout", f"{domain()}/{LABEL}"], capture_output=True)
    run("launchctl", "bootstrap", domain(), PLIST, dry=dry)
    print(f"installed {PLUGIN} from {commit[:12]}; waker {LABEL} every 300 s; logs {HOME / 'logs'}")


def uninstall(dry):
    run("launchctl", "bootout", f"{domain()}/{LABEL}", dry=dry)
    if PLIST.exists():
        print(f"+ rm {PLIST}")
        if not dry:
            PLIST.unlink()
    run("codex", "plugin", "remove", PLUGIN, dry=dry)
    print(f"removed; ~/.codex/config.toml backups are {CONFIG.parent}/config.toml.warrant-backup-*")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    (uninstall if a.uninstall else install)(a.dry_run)
