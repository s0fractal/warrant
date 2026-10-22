#!/usr/bin/env python3
"""SPEC claims as Warrant 2 records: the command. The code is the package tools/claimslib/, one
module per responsibility; its docstring says what the records are and lists the commands.

    python3 tools/claims.py --help
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claimslib import *              # noqa: E402,F401,F403  every name, as `import claims` gave it before the split
from claimslib.cli import main       # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
