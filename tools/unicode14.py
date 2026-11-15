"""The code points assigned in Unicode 14.0.0, as the format fixes them for actor ids (docs/V3.md §2, `actor`).

    python3.11 tools/unicode14.py          # prints the table, from an interpreter whose tables are Unicode 14.0.0
    python3.11 tools/unicode14.py --write  # writes it into warrant/shapes.py and impl-js/warrant.mjs

The table is the ranges of code points whose General_Category is not Cn in UnicodeData 14.0.0, written as
`start-end` in lowercase hex, comma-separated. Python 3.11 carries exactly these tables; tests/shapes_test.py holds the
table against the interpreter's (equal under 14.0.0, a subset under any later version: an assignment is never taken
back), and tests/impl_js_test.py holds the JavaScript copy equal to the Python one."""
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "warrant" / "shapes.py"
JS = ROOT / "impl-js" / "warrant.mjs"


def table():
    if unicodedata.unidata_version != "14.0.0":
        sys.exit(f"needs an interpreter with Unicode 14.0.0 tables (Python 3.11), not {unicodedata.unidata_version}")
    out, start = [], None
    for cp in range(0x110001):
        assigned = cp <= 0x10FFFF and unicodedata.category(chr(cp)) != "Cn"
        if assigned and start is None:
            start = cp
        elif not assigned and start is not None:
            out.append(f"{start:x}-{cp - 1:x}")
            start = None
    return ",".join(out)


def main():
    t = table()
    if "--write" not in sys.argv[1:]:
        print(t)
        return 0
    PY.write_text(re.sub(r'^UNICODE14_ASSIGNED = "[^"]*"$', f'UNICODE14_ASSIGNED = "{t}"', PY.read_text(), count=1, flags=re.M))
    js = JS.read_text()
    JS.write_text(re.sub(r'export const UNICODE14_ASSIGNED = "[^"]*";', f'export const UNICODE14_ASSIGNED = "{t}";', js))
    return 0


if __name__ == "__main__":
    sys.exit(main())
