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
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "third_party" / "primitives"
PIN = DEST / "PIN.json"


def check():
    pin = json.loads(PIN.read_text())
    manifest = DEST / "MANIFEST.sha256"
    problems = []
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != pin["manifest_sha256"]:
        problems.append("MANIFEST.sha256 does not match PIN.json")
    listed = []
    for line in manifest.read_text().splitlines():
        digest, name = line.split("  ", 1)
        listed.append(name)
        f = DEST / name
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest() != digest:
            problems.append(f"{name} does not match the manifest")
    present = sorted(str(p.relative_to(DEST)) for p in DEST.rglob("*") if p.is_file())
    extra = set(present) - set(listed) - {"MANIFEST.sha256", "PIN.json"}
    if extra:
        problems.append(f"files not in the manifest: {sorted(extra)}")
    for p in problems:
        print("FAIL", p)
    print(f"primitives {pin['commit'][:12]} (manifest {pin['manifest_sha256'][:16]}…):",
          "FAIL" if problems else "vendored copy matches its pin")
    return 1 if problems else 0


def vendor(repo, commit):
    show = lambda path: subprocess.run(["git", "-C", repo, "show", f"{commit}:{path}"],  # noqa: E731
                                       capture_output=True, check=True).stdout
    manifest = show("MANIFEST.sha256")
    if DEST.exists():
        for p in sorted(DEST.rglob("*"), reverse=True):
            p.unlink() if p.is_file() else p.rmdir()
    for line in manifest.decode().splitlines():
        name = line.split("  ", 1)[1]
        (DEST / name).parent.mkdir(parents=True, exist_ok=True)
        (DEST / name).write_bytes(show(name))
    (DEST / "MANIFEST.sha256").write_bytes(manifest)
    PIN.write_text(json.dumps({"repository": "https://github.com/s0fractal/primitives", "commit": commit,
                               "manifest_sha256": hashlib.sha256(manifest).hexdigest()}, indent=2) + "\n")
    return check()


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check())
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(vendor(sys.argv[1], sys.argv[2]))
