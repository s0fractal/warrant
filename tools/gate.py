#!/usr/bin/env python3
"""`python3 -m warrant.gate` with this checkout's package, kept at this path for the merge-on-acceptance
workflow, which runs it from the base commit's checkout, and for the docs (docs/REPOSITORY.md). The code is
warrant/gate.py; this file decides nothing. An owner path, as warrant/gate.py is (.warrant/merge.json)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from warrant.gate import main  # noqa: E402

sys.exit(main())
