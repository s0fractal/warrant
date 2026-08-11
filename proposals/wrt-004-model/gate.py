#!/usr/bin/env python3
"""The WRT-004 §6 kill gate. Exit status is the verdict.

Two independent implementations must produce **byte-identical** manifest
bytes for the same store, and every mutation of the bytes or the paths must
move `input_root`. Failing this closes the upstream direction — the gate was
written before the code so that outcome stays available.

What it does NOT prove: that the design is complete. This covers
`input_manifest` and `input_root` only. The judgement half of `@v1` depends
on a closed issue-code registry, which WRT-004 §7 deliberately leaves
undecided, and an incomplete registry is exactly what sank WRT-003.

    gate.py            # run it
    gate.py --keep     # leave the materialized stores for inspection
"""

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "input_manifest.py")
GO_SRC = os.path.join(HERE, "input_manifest.go")

failures = []


def check(name, ok, detail=""):
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name,
                        "" if ok else "  (%s)" % detail))
    if not ok:
        failures.append(name)
    return ok


def materialize(root, files):
    for rel, b64 in files.items():
        full = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(base64.b64decode(b64))


def run(cmd, cwd=None):
    p = subprocess.run(cmd, capture_output=True, cwd=cwd)
    if p.returncode:
        return None, p.stderr.decode()[:200]
    return p.stdout, ""


def main(argv):
    with open(os.path.join(HERE, "corpus.json")) as fh:
        corpus = json.load(fh)
    if not corpus.get("stores"):
        print("FAIL  empty corpus — a gate over zero stores is vacuous")
        return 1

    tmp = tempfile.mkdtemp(prefix="wrt004-")
    go_bin = os.path.join(tmp, "input_manifest")
    out, err = run(["go", "build", "-o", go_bin, GO_SRC])
    if out is None:
        print("FAIL  the Go implementation does not build  (%s)" % err)
        return 1
    print("built the Go implementation\n")

    roots = {}
    try:
        for name, store in corpus["stores"].items():
            d = os.path.join(tmp, name)
            os.makedirs(d, exist_ok=True)
            materialize(d, store["files"])

            py_out, py_err = run([sys.executable, PY, d])
            go_out, go_err = run([go_bin, d])
            if py_out is None or go_out is None:
                check("%s: both implementations run" % name, False,
                      py_err or go_err)
                continue

            # THE claim: identical bytes, not equal-after-parsing. Comparing
            # parsed objects would pass while the two emit different JSON,
            # and the whole point of a digest over those bytes is that the
            # bytes are the artifact.
            if not check("%s: byte-identical manifest" % name,
                         py_out == go_out,
                         "python=%r go=%r" % (py_out[:70], go_out[:70])):
                continue

            py_root = run([sys.executable, PY, d, "--root"])[0].decode().strip()
            go_root = run([go_bin, d, "--root"])[0].decode().strip()
            check("%s: identical input_root" % name, py_root == go_root)
            roots[name] = py_root

            # ...and the root must actually be the domain-separated hash of
            # those bytes, not some other value both agree on
            want = hashlib.sha256(
                b"warrant.verify-report.input@v1:" + py_out).hexdigest()
            # decoded, not raw stdout: comparing bytes to a hexdigest str is
            # vacuously false, which is how this check first "failed" against
            # two implementations that were in fact correct
            check("%s: input_root is the domain-separated hash" % name,
                  py_root == want, "got %s want %s" % (py_root[:12], want[:12]))

        # Every mutation moves the root. A manifest that survives an edit is
        # not naming the bytes it claims to name.
        base = os.path.join(tmp, "plain")
        before = run([sys.executable, PY, base, "--root"])[0].decode().strip()
        mutations = {
            "one byte changed": lambda: open(
                os.path.join(base, "blobs", "p"), "wb").write(b"policX"),
            "a file added": lambda: open(
                os.path.join(base, "blobs", "q"), "wb").write(b"q"),
            "a path renamed": lambda: os.rename(
                os.path.join(base, "blobs", "q"),
                os.path.join(base, "blobs", "r")),
            "a file removed": lambda: os.remove(
                os.path.join(base, "blobs", "r")),
        }
        # compared against the state IMMEDIATELY before each mutation, not
        # against every state ever seen: this sequence deliberately ends by
        # removing the file it added, so it legitimately returns to an
        # earlier manifest. "Undo restores the root" is the property working,
        # not a collision.
        prev = before
        for label, mutate in mutations.items():
            mutate()
            after = run([sys.executable, PY, base, "--root"])[0].decode().strip()
            go_after = run([go_bin, base, "--root"])[0].decode().strip()
            check("mutation moves input_root: %s" % label, after != prev,
                  "unchanged at %s" % after[:12])
            check("...and both implementations move together: %s" % label,
                  after == go_after)
            prev = after

        # The duplicate-path rule (§3.1) cannot be reached from store bytes —
        # a filesystem holds one file per path — so it is reachable only via
        # the trust config, whose basename can collide with a store-relative
        # path. Without this case the rule was unenforced in one
        # implementation and the gate did not notice.
        dup = os.path.join(tmp, "dup")
        os.makedirs(os.path.join(dup, "records"), exist_ok=True)
        with open(os.path.join(dup, "genesis.json"), "wb") as fh:
            fh.write(b"{}")
        trust = os.path.join(tmp, "genesis.json")   # basename collides
        with open(trust, "wb") as fh:
            fh.write(b"{}")
        py_dup = subprocess.run([sys.executable, PY, dup, "--trust-config", trust],
                                capture_output=True)
        go_dup = subprocess.run([go_bin, dup, "--trust-config", trust],
                                capture_output=True)
        check("a duplicate path is refused (python)", py_dup.returncode != 0,
              "accepted: %r" % py_dup.stdout[:60])
        check("a duplicate path is refused (go)", go_dup.returncode != 0,
              "accepted: %r" % go_dup.stdout[:60])

        # distinct stores must not collide
        check("distinct stores have distinct roots",
              len(set(roots.values())) == len(roots),
              "roots=%s" % sorted(roots.values()))
    finally:
        if "--keep" in argv:
            print("\nstores kept in %s" % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print()
    if failures:
        print("KILL GATE FAILED: %d check(s): %s"
              % (len(failures), ", ".join(failures[:4])))
        print("Per WRT-004 §6 this closes the upstream direction unless the "
              "next round reaches byte identity.")
        return 1
    print("KILL GATE PASSED — input_manifest and input_root only.")
    print("The judgement half of @v1 is NOT covered: it needs the closed "
          "issue-code registry that §7 leaves open.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
