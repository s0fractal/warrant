#!/usr/bin/env python3
"""CLOSED as an external artifact — its oracle produced a false PASS.

**Do not quote a green run of this script.** It exits non-zero for that
reason, while still printing what it does.

The finding: the oracle required that an ERR *message contain the tampered
digest*, which is not the same as the report asserting a content-address
mismatch. Rewriting both ERRs to `blob c8d453b05c7d could not be read:
permission denied` — right digest, right subjects, wrong claim — printed all
five PASS and exited 0, asserting that a one-byte change had been detected
when the report never said so.

That is the fourth wrapper in a row whose *interpretation* was the defect
while the mechanism underneath was fine. The conclusion is in the README:
the external proof does not need a demo. Two raw `warrant verify` runs and a
visible one-byte diff say it, and every interpretive layer added more
false-PASS surface than value.

Original description follows.

One property: change one digit in the pinned policy, and verification goes red.

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


def policy_of(store):
    """The policy digest, taken from `body.under` — not from the text.

    The first version of this demo grepped the blobs for "bereavement" and
    hit the passenger's REQUEST, then called it the policy. The property
    still demonstrated, but the sentence describing it was false, and a demo
    whose one claim is mislabelled is worse than no demo. `under` is where a
    Warrant record names the rules it was filed under, so that is where the
    digest comes from.

    Returns (policy digest, {record WarrantID that names it}).
    """
    digests, records = {}, {}
    rec_dir = os.path.join(store, "records")
    for name in sorted(os.listdir(rec_dir)):
        with open(os.path.join(rec_dir, name)) as fh:
            body = json.load(fh)["body"]
        for u in body.get("under") or []:
            digests[u] = digests.get(u, 0) + 1
            records.setdefault(u, set()).add(name[:-5])
    if not digests:
        sys.exit("no record in the pack names anything under `under`")
    # the one the most records agree on; ties are a pack problem, not ours
    best = max(sorted(digests), key=lambda d: digests[d])
    return best, records[best]


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

        policy, naming = policy_of(store)
        blob = os.path.join(store, "blobs", policy)
        if not os.path.isfile(blob):
            sys.exit("the pack names policy %s but does not carry it" % policy[:12])
        with open(blob, "rb") as fh:
            text = fh.read()
        print("policy blob:  %s" % policy)
        print("named in `under` by %d record(s); addressed by the hash of its bytes"
              % len(naming))

        rc_before, before = verify(store)
        show("BEFORE — the bytes are what the decision named", rc_before, before)

        # exactly one byte, digit to digit
        pos = next((i for i, b in enumerate(text) if chr(b).isdigit()), None)
        if pos is None:
            sys.exit("no digit in the policy text to change")
        old_ch = chr(text[pos])
        new_ch = "7" if old_ch != "7" else "3"
        tampered = text[:pos] + new_ch.encode() + text[pos + 1:]
        differing = sum(1 for a, b in zip(text, tampered) if a != b)
        with open(blob, "wb") as fh:
            fh.write(tampered)
        print("\nchanged one byte at offset %d: %r -> %r  (bytes differing: %d)"
              % (pos, old_ch, new_ch, differing))
        print("the decision record is untouched")

        rc_after, after = verify(store)
        show("AFTER — the same command, the same decision", rc_after, after)

        # The oracle names what it requires. The first version accepted any
        # non-zero exit with any error: injecting an unrelated verifier
        # failure made it print success. Detection has to be attributable to
        # THIS blob and to the records that name it, or it is not evidence
        # about the tamper.
        errs = [f for f in after["findings"] if f["level"] == "ERR"]
        about_policy = [f for f in errs if policy[:12] in f["message"]]
        subjects = {f["subject"] for f in about_policy}
        checks = [
            ("exactly one byte changed, digit to digit",
             differing == 1 and old_ch.isdigit() and new_ch.isdigit()),
            ("before: exit 0, ok=true, no errors",
             rc_before == 0 and before["ok"] is True and before["errors"] == 0),
            ("after: exit 1, ok=false",
             rc_after == 1 and after["ok"] is False),
            ("every ERR names the tampered digest",
             bool(about_policy) and len(about_policy) == len(errs)),
            ("the ERR subjects are exactly the records naming it",
             subjects == naming),
        ]
        print("\n" + "-" * 62)
        for name, ok in checks:
            print("%s  %s" % ("PASS" if ok else "FAIL", name))
        if not all(ok for _n, ok in checks):
            print("\nFAILED: the outcome is not attributable to this tamper.")
            return 1
        print("\nThe verifier is the same. The decision is the same.")
        print("One digit moved in the file the decision named, and the")
        print("exit status went from 0 to %d." % rc_after)
        print("\n" + "!" * 62)
        print("CLOSED: these PASS lines are not trustworthy. The oracle")
        print("accepts any ERR whose message merely contains the digest —")
        print("including 'could not be read: permission denied', which")
        print("asserts no mismatch at all. See README. Run the two raw")
        print("commands instead; they need no oracle.")
        print("!" * 62)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
