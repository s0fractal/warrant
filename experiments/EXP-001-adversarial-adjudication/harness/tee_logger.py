#!/usr/bin/env python3
"""Non-sealing pass-through: the LOG condition's observer.

    python3 tee_logger.py --workdir <dir> -- <command...>    # appends <dir>/session.jsonl

Forwards stdin to the child and the child's stdout to stdout, byte for byte,
and appends every line to the log with its direction and a timestamp. No
signatures, no chain, no classification: exactly what an ordinary logging
proxy gives a dispute handler. It is placed OUTSIDE the sealing proxy in the
run, so both observers see the same byte stream.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
import time


def pump(src, dst, log, direction, close_dst=False):
    for raw in src:
        try:
            log.write(json.dumps({"ts": time.time(), "dir": direction, "line": raw.rstrip("\n")}) + "\n")
            log.flush()
        finally:
            try:
                dst.write(raw); dst.flush()
            except (OSError, ValueError):
                return
    if close_dst:                      # host EOF must reach the child, or it never exits
        try:
            dst.close()
        except (OSError, ValueError):
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    base = Path(a.workdir).resolve()
    if not base.is_dir():
        sys.exit(f"tee_logger: {a.workdir} is not a directory")
    log_path = (base / "session.jsonl").resolve()
    if log_path.parent != base:
        sys.exit("tee_logger: refusing a path outside the workdir")
    log = open(log_path, "a")
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=1, text=True)
    t = threading.Thread(target=pump, args=(sys.stdin, p.stdin, log, "host", True), daemon=True)
    t.start()
    pump(p.stdout, sys.stdout, log, "server")
    rc = p.wait()
    log.write(json.dumps({"ts": time.time(), "dir": "meta", "line": f"child exit {rc}"}) + "\n")
    log.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
