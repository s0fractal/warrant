#!/usr/bin/env python3
"""Local control only: exercise both roles, return replay and two refusals."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zlib

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
    frozen_reply = HERE / "round-1/reply.json"
    frozen_report = HERE / "round-1/receiver-report.json"
    reply_hash = "974fef6d681e415b477327cfb811b18f1b9cd72cbeb18737615adaf662447c13"
    assert hashlib.sha256(frozen_reply.read_bytes()).hexdigest() == reply_hash
    assert hashlib.sha256(frozen_report.read_bytes()).hexdigest() == "65dd3b72e61991911cd05a5c825a48589de0e96785e40de109eba869630f1f88"
    reported = json.loads(frozen_report.read_bytes())
    assert reported["reply_sha256"] == reply_hash
    assert zlib.decompress(base64.b64decode(reported["reply_zlib_base64"], validate=True)) == frozen_reply.read_bytes()
    verified = run("verify", "--packet", HERE / "packet.json", "--reply", frozen_reply,
                   "--reply-sha256", reply_hash, "--work", root / "frozen-verifier")
    assert verified["local_return_replay"] == "PASS"
    print("CROSS-HOST LOCAL CONTROL: PASS (two roles, six receiver controls, return replay, packet and reply substitutions)")
    print("FROZEN ROUND-1 ARTIFACTS: PASS (exact file hashes, compressed-payload parity, signed acceptance and local computation replay)")
