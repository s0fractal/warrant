#!/usr/bin/env python3
"""Vendor a pinned s0fractal/primitives pack, or check the vendored copy.

    python3 tools/vendor_primitives.py ~/Projects/primitives <commit>   # (re)vendor
    python3 tools/vendor_primitives.py --check                          # verify the copy

primitives holds the behaviour our implementations share (SHA-256, RFC 8785,
the signature message, Ed25519, P-256) as vectors, not as code. The copy lives in
third_party/primitives/ next to PIN.json, which records the source commit and the
SHA-256 of the pack's MANIFEST.sha256. --check recomputes both: every vendored
file matches the manifest, and the manifest matches the pin.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "third_party" / "primitives"
PIN = DEST / "PIN.json"
MANIFEST = "MANIFEST.sha256"
COMMIT = re.compile(r"[0-9a-f]{40}")
SAFE_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*(/[A-Za-z0-9_][A-Za-z0-9_.-]*)*")


def safe_name(name):
    """A manifest entry names a file inside the pack: no absolute path, no `..`,
    nothing that resolves outside third_party/primitives/. The manifest comes from
    another repository, so a hostile one must not be able to write elsewhere."""
    if not SAFE_NAME.fullmatch(name) or ".." in name.split("/"):
        sys.exit(f"refusing manifest entry {name!r}: not a plain relative path")
    target = (DEST / name).resolve()
    if not target.is_relative_to(DEST.resolve()):
        sys.exit(f"refusing manifest entry {name!r}: resolves outside {DEST}")
    return name


def check():
    pin = json.loads(PIN.read_text())
    manifest = DEST / MANIFEST
    problems = []
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != pin["manifest_sha256"]:
        problems.append("MANIFEST.sha256 does not match PIN.json")
    listed = []
    for line in manifest.read_text().splitlines():
        digest, name = line.split("  ", 1)
        listed.append(safe_name(name))
        f = DEST / name
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            problems.append(f"{name} does not match the manifest")
    present = {str(p.relative_to(DEST)) for p in DEST.rglob("*") if p.is_file()}
    extra = present - set(listed) - {MANIFEST, "PIN.json"}
    if extra:
        problems.append(f"files not in the manifest: {sorted(extra)}")
    for p in problems:
        print("FAIL", p)
    print(f"primitives {pin['commit'][:12]} (manifest {pin['manifest_sha256'][:16]}…):",
          "FAIL" if problems else "vendored copy matches its pin")
    return 1 if problems else 0


def vendor(repo, commit):
    if not COMMIT.fullmatch(commit):
        sys.exit("pin a full 40-hex commit, not a ref: a ref can move")
    # Sonar S8707 (CLI-supplied path): the maintainer names their own primitives
    # checkout; only `git show <commit>:<path>` reads from it, and every file is
    # then held to the pinned manifest digest by check().
    def show(path):
        return subprocess.run(["git", "-C", repo, "show", f"{commit}:{path}"],  # NOSONAR
                              capture_output=True, check=True).stdout
    manifest = show(MANIFEST)
    if DEST.exists():
        for p in sorted(DEST.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    names = [safe_name(line.split("  ", 1)[1]) for line in manifest.decode().splitlines()]
    DEST.mkdir(parents=True, exist_ok=True)
    for name in names:
        (DEST / name).parent.mkdir(parents=True, exist_ok=True)
        (DEST / name).write_bytes(show(name))
    (DEST / MANIFEST).write_bytes(manifest)
    PIN.write_text(json.dumps({"repository": "https://github.com/s0fractal/primitives", "commit": commit,
                               "manifest_sha256": hashlib.sha256(manifest).hexdigest()}, indent=2) + "\n")
    return check()


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check())
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(vendor(sys.argv[1], sys.argv[2]))
