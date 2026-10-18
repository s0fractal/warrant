#!/usr/bin/env python3
"""Claude opens the WRT-022 S3 duty, once, on 2026-10-18, when S3 was written.
Kept for audit: running it again files a NEW record.

    WRT022_KEY=<claude's key> python3 dogfood/wrt-022/record_claude_s3_open.py
"""
import sys

import events as E

sys.path.insert(0, str(E.ROOT / "impl"))
import loops as L  # noqa: E402

BASE = "8feb33558a5ec362e6d8c8ebd56c5c6903f7c210"   # master with S2 merged (#137)


def main():
    s = E.store()
    d = L.duty(E.CLAUDE, [E.CODEX], "implement WRT-022 S3: minimal grants -- explicit roots and attenuation; release by grant",
               BASE, [["DISCHARGED", "ATTESTED"]], acceptance=[E.CODEX])
    print(E.file(s, "propose", s.put_blob(L.canon(d)), E.CLAUDE, note="duty"))


if __name__ == "__main__":
    main()
