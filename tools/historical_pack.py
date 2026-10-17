#!/usr/bin/env python3
"""Historical verifier pack (redesign P6, D11): the verifier that wrote the old
records, frozen by exact commit, so the current path never has to run it.

    python3 tools/historical_pack.py build OUT [--commit SHA]   # extract + MANIFEST.json
    python3 tools/historical_pack.py verify PACK STORE [--expect-manifest SHA256] [args]

`build` takes the files from git at the commit (never from the working tree) and
records each SHA-256. `verify` runs the PACK's warrant.py in isolation (`python3
-I`, cwd = the pack) only after three checks, all against identities the
RECIPIENT chose, never ones the pack declares about itself (independent review
WA06: a pack with an empty file list and a substituted verifier used to run):
the SHA-256 of MANIFEST.json equals the expected digest (pinned below for the
baseline, or `--expect-manifest`); the manifest lists exactly FILES; every file
matches its digest.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "ca53e6489c5d888768193e2d172e72409a1eb560"     # the redesign's warrant baseline
FILES = ["impl/warrant.py", "impl/sigma_glyph_v05.py", "impl/sigma_glyph_v06.py"]
# The baseline pack's MANIFEST.json digest, as built from git at BASELINE. A pack
# is the baseline verifier iff its manifest has these exact bytes.
BASELINE_MANIFEST_SHA256 = "2ac8590b148272fc8b756c841005a6f8cb11eaea082f195319136ecbcc4af467"


def build(out, commit=BASELINE):
    out = Path(out)
    (out / "impl").mkdir(parents=True, exist_ok=True)
    files = {}
    for f in FILES:
        data = subprocess.run(["git", "show", f"{commit}:{f}"], cwd=ROOT, capture_output=True,
                              check=True).stdout
        (out / f).write_bytes(data)
        files[f] = hashlib.sha256(data).hexdigest()
    manifest = {"schema": "warrant.historical-pack@draft-1", "repository": "https://github.com/s0fractal/warrant",
                "commit": commit, "files": files,
                "use": "verify records of the profile this commit wrote; the current path refuses them by name"}
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify(pack, store, extra, expected_manifest=BASELINE_MANIFEST_SHA256):
    pack = Path(pack)
    raw = (pack / "MANIFEST.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_manifest:
        print("PACK IDENTITY: MANIFEST.json is not the expected manifest; nothing run")
        return 2
    manifest = json.loads(raw)
    if sorted(manifest.get("files", {})) != sorted(FILES):
        print(f"PACK IDENTITY: the pack must list exactly {FILES}; nothing run")
        return 2
    bad = [f for f, h in manifest["files"].items()
           if not (pack / f).is_file() or hashlib.sha256((pack / f).read_bytes()).hexdigest() != h]
    if bad:
        print(f"PACK INTEGRITY: {bad} do not match MANIFEST.json; nothing run")
        return 2
    r = subprocess.run([sys.executable, "-I", "impl/warrant.py", "--store", str(Path(store).resolve()),
                        "verify", *extra], cwd=pack, capture_output=True, text=True, check=False)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == "build":
        commit = a[a.index("--commit") + 1] if "--commit" in a else BASELINE
        print(json.dumps(build(a[1], commit), indent=2))
        return 0
    if len(a) >= 3 and a[0] == "verify":
        rest = a[3:]
        expected = BASELINE_MANIFEST_SHA256
        if "--expect-manifest" in rest:
            i = rest.index("--expect-manifest")
            expected, rest = rest[i + 1], rest[:i] + rest[i + 2:]
        return verify(a[1], a[2], rest, expected)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
