#!/usr/bin/env python3
"""One property: change one digit in the pinned policy, and verification goes red.

    python3 demos/air-canada/tamper.py

Nothing else. It does not evaluate the policy, does not decide whether the
decision was correct, and does not claim the agent was under control. It shows
one thing, twice:

    a signed decision names some policy bytes by hash
    those bytes are still there            -> verify exits 0
    one digit changes                      -> verify exits 1

The committed pack is never modified; the tamper happens in a temporary copy.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CLI = os.path.join(REPO, "impl", "warrant.py")
PACK = os.path.join(HERE, "pack")


def verify(store):
    """One verifier run. Returns (exit status, parsed report)."""
    p = subprocess.run([sys.executable, CLI, "--store", store,
                        "verify", "--json"], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout)


def show(label, rc, report):
    print("\n%s" % label)
    print("  $ warrant --store <pack> verify --json")
    print("  ok=%-5s records=%d errors=%d   exit status: %d"
          % (report["ok"], report["records"], report["errors"], rc))
    for f in report["findings"]:
        if f["level"] == "ERR":
            print("  ERR %s  %s" % (f["subject"][:12], f["message"][:64]))


def main():
    tmp = tempfile.mkdtemp(prefix="warrant-tamper-")
    try:
        store = os.path.join(tmp, ".warrants")
        shutil.copytree(os.path.join(PACK, ".warrants"), store)

        # the policy the decision names, by hash: the filename IS the digest
        blobs = os.path.join(store, "blobs")
        policy = None
        for name in sorted(os.listdir(blobs)):
            with open(os.path.join(blobs, name), "rb") as fh:
                body = fh.read()
            if b"bereavement" in body.lower():
                policy, text = name, body
                break
        if policy is None:
            sys.exit("no policy blob in the pack — nothing to tamper with")

        print("policy blob:  %s" % policy)
        print("named by the decision, and addressed by the hash of its bytes")

        rc_before, before = verify(store)
        show("BEFORE — the bytes are what the decision named", rc_before, before)

        # exactly one digit
        old, new = b"", b""
        for a, b in ((b"90 days", b"99 days"), (b"1", b"7")):
            if a in text:
                old, new = a, b
                break
        if not old:
            sys.exit("could not find a digit to change in the policy text")
        with open(os.path.join(blobs, policy), "wb") as fh:
            fh.write(text.replace(old, new, 1))
        print("\nchanged %r to %r — one digit, in the policy file, "
              "leaving the decision untouched" % (old.decode(), new.decode()))

        rc_after, after = verify(store)
        show("AFTER — the same command, the same decision", rc_after, after)

        # The demo asserts its own outcome. If the tamper ever stops being
        # detected, this must exit non-zero rather than print a reassuring
        # before/after that no longer means anything.
        detected = rc_before == 0 and rc_after != 0 and after["errors"] > 0
        print("\n" + "-" * 62)
        if detected:
            print("The verifier is the same. The decision is the same.")
            print("One digit moved in the file the decision named, and the")
            print("exit status went from 0 to %d." % rc_after)
            return 0
        print("FAILED: the tamper did not change the outcome.")
        print("before exit=%d after exit=%d errors=%d"
              % (rc_before, rc_after, after["errors"]))
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
