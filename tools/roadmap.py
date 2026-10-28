#!/usr/bin/env python3
"""`python3 -m warrant.roadmap` with this checkout's package, kept at this path for CI and the docs
(docs/REPOSITORY.md). The code is warrant/roadmap.py; this file decides nothing."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from warrant.roadmap import entry  # noqa: E402

sys.exit(entry())
