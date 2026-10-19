#!/usr/bin/env python3
"""Local control only: exercise both roles, return replay and two refusals."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from warrant import jcs as C

HERE = Path(__file__).resolve().parent


def run(*args, passes=True):
    p = subprocess.run([sys.executable, str(HERE / "run.py"), *map(str, args)],
                       text=True, capture_output=True, timeout=240)
    assert (p.returncode == 0) == passes, (p.returncode, p.stdout, p.stderr)
    return json.loads(p.stdout) if passes else p.stderr


with tempfile.TemporaryDirectory(prefix="cross-host-control-") as tmp:
    root = Path(tmp)
    packet, reply = root / "packet.json", root / "reply.json"
    sent = run("produce", "--work", root / "producer", "--packet", packet)
    args = ["receive", "--packet", packet, "--accept-provider",
            "0caff793d00dd798fa0af89517674c2ca562e1d517e7c969cc40617778c776c5"]
    err = run(*args, "--packet-sha256", "00" * 32, "--work", root / "rejected",
              "--reply", reply, passes=False)
    assert "packet digest mismatch" in err and not (root / "rejected").exists()
    received = run(*args, "--packet-sha256", sent["packet_sha256"],
                   "--work", root / "receiver", "--reply", reply)
    verified = run("verify", "--packet", packet, "--reply", reply,
                   "--reply-sha256", received["reply_sha256"], "--work", root / "verifier")
    assert verified["local_return_replay"] == "PASS"
    wrong = C.loads(reply.read_bytes())
    wrong["result"]["segment"]["checkpoint"] = "ab" * 32
    altered = root / "altered.json"
    altered.write_bytes(C.canon(wrong))
    err = run("verify", "--packet", packet, "--reply", altered,
              "--reply-sha256", C.digest(altered.read_bytes()), "--work", root / "other", passes=False)
    assert "reply metadata does not name its receipt" in err
    print("CROSS-HOST LOCAL CONTROL: PASS (two roles, six receiver controls, return replay, packet and reply substitutions)")
