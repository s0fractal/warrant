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

        # THE round-1 refutation, now a permanent vector. A live verifier
        # follows a symlinked record; the round-1 walk skipped it silently,
        # so input_root committed to [] while the report judged one record.
        sym = os.path.join(tmp, "symlink")
        os.makedirs(os.path.join(sym, "records"), exist_ok=True)
        target = os.path.join(tmp, "real.json")
        with open(target, "wb") as fh:
            fh.write(b'{"a":1}')
        os.symlink(target, os.path.join(sym, "records", "linked.json"))
        py_sym = run([sys.executable, PY, sym])[0]
        go_sym = run([go_bin, sym])[0]
        check("a symlink is visible in the observation",
              py_sym is not None and b'"refused"' in py_sym
              and b'"symlink"' in py_sym,
              "manifest=%r" % (py_sym or b"")[:80])
        check("...identically in both implementations", py_sym == go_sym)

        # attempted-but-unreadable: round 1's schema could not represent it
        # (sha256 was mandatory and there are no bytes), and the Python
        # crashed with a traceback rather than refusing
        unre = os.path.join(tmp, "unreadable")
        os.makedirs(os.path.join(unre, "records"), exist_ok=True)
        bad = os.path.join(unre, "records", "aaaa.json")
        with open(bad, "wb") as fh:
            fh.write(b"{}")
        os.chmod(bad, 0)
        try:
            py_un = run([sys.executable, PY, unre])[0]
            go_un = run([go_bin, unre])[0]
            check("an unreadable file is stated, not crashed on",
                  py_un is not None and b'"unreadable"' in py_un,
                  "manifest=%r" % (py_un or b"")[:80])
            check("...and carries no digest for bytes it never had",
                  py_un is not None and b'"sha256"' not in py_un)
            check("...identically in both implementations", py_un == go_un)
        finally:
            os.chmod(bad, 0o644)

        # U+2028: encoding/json escapes it even with SetEscapeHTML(false),
        # and SPEC §4 forbids that escaping outright
        sep = os.path.join(tmp, "u2028")
        os.makedirs(os.path.join(sep, "blobs"), exist_ok=True)
        with open(os.path.join(sep, "blobs", "line\u2028sep"), "wb") as fh:
            fh.write(b"x")
        py_sep, go_sep = run([sys.executable, PY, sep])[0], run([go_bin, sep])[0]
        check("U+2028 in a path is emitted raw, per SPEC §4",
              py_sep is not None and b"\xe2\x80\xa8" in py_sep
              and b"u2028" not in py_sep.lower())
        check("...identically in both implementations", py_sep == go_sep,
              "py=%r go=%r" % ((py_sep or b"")[:60], (go_sep or b"")[:60]))

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

    # The normative escaping battery SPEC §4 points at (§8.4). Round 1 hand-
    # rolled an argument about escaping while the repository already shipped
    # 47 machine-readable vectors that decide it; the Go failed one of them
    # and nothing noticed, because nothing ran them.
    vec_path = os.path.join(HERE, "..", "..", "examples", "canon-vectors.json")
    with open(vec_path) as fh:
        vectors = json.load(fh)
    sys.path.insert(0, HERE)
    import input_manifest as im
    bad = []
    for case in vectors["cases"]:
        got = im.jcs(case["body"]).encode("utf-8")
        if got.hex() != case["canon_hex"]:
            bad.append(case["name"])
    check("the §4 escaping battery passes (%d vectors)" % len(vectors["cases"]),
          not bad, "failing: %s" % bad[:4])

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
