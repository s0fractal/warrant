#!/usr/bin/env python3
"""Seal or reveal the Planter's commitment for EXP-001.

    python3 commit_plants.py seal PLANTS.json      # writes PLANTS.sha256 (commit this; NOT the json)
    python3 commit_plants.py reveal PLANTS.json    # checks the revealed file against PLANTS.sha256

The commitment is sha256 over the exact bytes of PLANTS.json, with the UTC
time it was sealed. A reveal that does not match is a failure of the
experiment's independence, not a scoring detail, and is reported as such.
"""
import hashlib
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEAL = HERE / "PLANTS.sha256"


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main(argv):
    if len(argv) != 3 or argv[1] not in ("seal", "reveal"):
        print(__doc__, file=sys.stderr)
        return 2
    d = digest(argv[2])
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
