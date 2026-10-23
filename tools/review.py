#!/usr/bin/env python3
"""The pull request review loop as Warrant 2 records: the command. The code is
tools/claimslib/reviews.py (its docstring maps the loop onto the records and lists the
commands) and the review replay checker tools/claimslib/review_replay.py.

    python3 tools/review.py --help
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from claimslib import reviews        # noqa: E402

if __name__ == "__main__":
    sys.exit(reviews.main())
