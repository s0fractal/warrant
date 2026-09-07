#!/usr/bin/env python3
"""Seal or reveal the Planter's commitment for EXP-001.

    python3 commit_plants.py seal      # digests ./PLANTS.json, writes ./PLANTS.sha256 (commit the .sha256, NOT the json)
    python3 commit_plants.py reveal    # checks ./PLANTS.json against ./PLANTS.sha256

Both files live beside this script and nowhere else; the script takes no
path. The commitment is sha256 over the exact bytes of PLANTS.json, with the
UTC time it was sealed. A reveal that does not match is a failure of the
experiment's independence, not a scoring detail, and is reported as such.
"""
import hashlib
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEAL = HERE / "PLANTS.sha256"
PLANTS = HERE / "PLANTS.json"


def main(argv):
    if len(argv) != 2 or argv[1] not in ("seal", "reveal"):
        print(__doc__, file=sys.stderr)
        return 2
    if not PLANTS.is_file():
        print(f"no {PLANTS.name} beside this script", file=sys.stderr)
        return 1
    d = hashlib.sha256(PLANTS.read_bytes()).hexdigest()
    if argv[1] == "seal":
        if SEAL.exists():
            print(f"refusing: {SEAL.name} already exists; a commitment is made once", file=sys.stderr)
            return 1
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        SEAL.write_text(f"{d}  PLANTS.json  sealed {stamp}\n")
        print(f"sealed {d[:16]}… at {stamp} -> {SEAL.name}; commit the .sha256, keep the .json out of the tree")
        return 0
    if not SEAL.exists():
        print("no PLANTS.sha256: nothing was committed before this run", file=sys.stderr)
        return 1
    committed = SEAL.read_text().split()[0]
    ok = committed == d
    print(("MATCH " if ok else "MISMATCH ") + f"committed {committed[:16]}… revealed {d[:16]}…")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
