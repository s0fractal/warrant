#!/usr/bin/env python3
"""keygen creates a new key file and nothing else (Python = Rust).

`--out` comes from whoever runs the CLI, increasingly an agent. A key writer that
overwrites the path it is handed, or follows a symlink, is a write primitive.
Before this, both implementations wrote the file and only then set 0600.

WHAT IS ASSERTED, FOR EACH OF PYTHON AND RUST
  1. a new path: created, mode 0600, exit 0
  2. an existing file: refused, nonzero, the file unchanged
  3. a symlink (dangling): refused, and its target is NOT created
  4. a key file must be a regular file: /dev/zero as --key is refused, not read forever
"""
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from three_clis import PY, RS, Tally

T = Tally()


def main():
    if not RS.is_file():
        print(f"UNRUN  {RS} not built")
        return 3
    for name, cli in (("py", PY), ("rs", [str(RS)])):
        tmp = Path(tempfile.mkdtemp(prefix="keygen-"))
        new = tmp / "new.key"
        r = subprocess.run(cli + ["keygen", "--out", str(new)], capture_output=True, text=True, check=False)
        T.check(f"{name} 1. new path created with mode 0600",
                r.returncode == 0 and stat.S_IMODE(new.stat().st_mode) == 0o600, r.stderr)
        before = new.read_bytes()
        r = subprocess.run(cli + ["keygen", "--out", str(new)], capture_output=True, text=True, check=False)
        T.check(f"{name} 2. existing file refused and unchanged",
                r.returncode != 0 and new.read_bytes() == before and "never overwrites" in r.stderr + r.stdout,
                (r.returncode, r.stderr))
        link = tmp / "link.key"
        os.symlink(tmp / "target.key", link)
        r = subprocess.run(cli + ["keygen", "--out", str(link)], capture_output=True, text=True, check=False)
        T.check(f"{name} 3. symlink refused, target not created",
                r.returncode != 0 and not (tmp / "target.key").exists(), (r.returncode, r.stderr))
    store = Path(tempfile.mkdtemp(prefix="keygen-store-")) / "s"
    subprocess.run(PY + ["--store", str(store), "init"], capture_output=True, check=False)
    blob = store.parent / "b"
    blob.write_bytes(b"x")
    subprocess.run(PY + ["--store", str(store), "blob", "add", str(blob)], capture_output=True, check=False)
    r = subprocess.run(PY + ["--store", str(store), "propose", "--subject", str(blob), "--under", str(blob),
                             "--actor", "a", "--key", "/dev/zero", "--ts", "1"],
                       capture_output=True, text=True, check=False, timeout=20)
    T.check("py 4. /dev/zero as a key file refused", r.returncode != 0 and "regular file" in r.stderr, r.stderr)
    print(f"\nKEYGEN-NEVER-OVERWRITES: {'ALL PASS' if T.ok else 'FAILURES PRESENT'}")
    return 0 if T.ok else 1


if __name__ == "__main__":
    sys.exit(main())
