#!/usr/bin/env python3
"""Claude opens the WRT-022 S2 duty, once, on 2026-10-18, when S2 was written.
Kept for audit: running it again files a NEW record.

    WRT022_KEY=<claude's key> python3 dogfood/wrt-022/record_claude_s2_open.py
"""
import sys

import events as E

sys.path.insert(0, str(E.ROOT / "impl"))
import loops as L  # noqa: E402

BASE = "de0fc912fdfb0bf519a1b0fefca137c13120e354"   # master with S1 merged (#135)


def main():
    s = E.store()
    d = L.duty(E.CLAUDE, [E.CODEX], "implement WRT-022 S2: crossings and replay receipts the recipient re-verifies",
               BASE, [["DISCHARGED", "ATTESTED"]], acceptance=[E.CODEX])
    print(E.file(s, "propose", s.put_blob(L.canon(d)), E.CLAUDE, note="duty"))


if __name__ == "__main__":
    main()
