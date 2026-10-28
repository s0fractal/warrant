#!/usr/bin/env python3
"""`python3 -m warrant.review` with this checkout's package, kept at this path for CI and the docs
(docs/REPOSITORY.md). The code is warrant/review.py; this file decides nothing. A checker runs as
`python3 -m warrant.review`, not through here: this file is outside the checker's identity."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from warrant.review import entry  # noqa: E402

sys.exit(entry())
