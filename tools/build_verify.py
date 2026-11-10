#!/usr/bin/env python3
"""Build warrant_verify.py: `warrant verify` as one standard-library file (docs/VERIFY.md).

    python3 tools/build_verify.py            # write warrant_verify.py at the repository's root
    python3 tools/build_verify.py --check    # exit 1 unless the file there is what this build gives

The file is tools/verify_single.py (an Ed25519 verification for an interpreter without `cryptography`, and a loader)
with one block replaced: the text of every module of warrant/ that warrant/verify.py imports, directly or through
another, each byte for byte, with its SHA-256. Which modules those are is read from their import statements, not
listed here, and they are ordered so that each comes after the ones it imports at its top. The build is a function of
those files alone: no time, no path, no version of anything. tests/verify_test.py rebuilds it and compares bytes, so
the committed file cannot differ from the package's modules, and holds its answers to `warrant verify`'s."""
import ast
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE, START, OUT, TEMPLATE = "warrant", "verify", "warrant_verify.py", "tools/verify_single.py"
BEGIN, END = "# @@BUILD@@", "# @@END@@\n"


def imports(src, top_only=False):
    """The modules of the package a module's source imports: at its top only, or anywhere in it."""
    tree = ast.parse(src)
    out = set()
    for node in (tree.body if top_only else ast.walk(tree)):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1 and node.module is None or node.level == 0 and node.module == PACKAGE:
                out |= {a.name for a in node.names}                          # from . import x / from warrant import x
            elif node.level == 1 or node.level == 0 and (node.module or "").startswith(PACKAGE + "."):
                out.add(node.module.split(".")[-1] if node.level == 0 else node.module.split(".")[0])     # from .x import y
        elif isinstance(node, ast.Import):
            out |= {a.name.split(".")[1] for a in node.names if a.name.startswith(PACKAGE + ".")}
    return out


def closure(root=ROOT):
    """({module: source}, order): the modules warrant/verify.py reaches, and an order in which each follows what it
    imports at its top (names first to last where nothing orders two)."""
    src, todo = {}, [START]
    while todo:
        name = todo.pop()
        if name not in src:
            src[name] = (root / PACKAGE / f"{name}.py").read_text(encoding="utf-8")
            todo += sorted(imports(src[name]))
    order = []
    while len(order) < len(src):
        ready = sorted(n for n in src if n not in order and imports(src[n], top_only=True) <= set(order))
        if not ready:
            raise SystemExit(f"build: the modules import each other in a circle: {sorted(set(src) - set(order))}")
        order.append(ready[0])
    return src, order


def literal(text):
    """`text` as a raw string literal that a reader of the file reads as the module's own lines."""
    lit = "r'''" + text + "'''"
    if "'''" in text or "\r" in text or ast.literal_eval(lit) != text:
        raise SystemExit("build: a module's text cannot be written as a raw ''' string")
    return lit


def build(root=ROOT):
    src, order = closure(root)
    digests = {f"{PACKAGE}/{n}.py": hashlib.sha256(src[n].encode()).hexdigest() for n in order}
    block = ["# Built by tools/build_verify.py from the files below, each byte for byte; edit those and build again.",
             "DIGESTS = {"] + [f'    "{p}": "{h}",' for p, h in digests.items()] + ["}", f"ORDER = {tuple(order)!r}", "SOURCES = {}"]
    for n in order:
        block += ["", f'SOURCES["{n}"] = {literal(src[n])}']
    template = (root / TEMPLATE).read_text(encoding="utf-8")
    head, _, rest = template.partition(BEGIN)
    _, found, tail = rest.partition(END)
    if not found or BEGIN in tail:
        raise SystemExit(f"build: {TEMPLATE} holds one block from {BEGIN} to {END.strip()}")
    return head + "\n".join(block) + "\n" + tail


def main(argv):
    text = build()
    out = ROOT / OUT
    if argv == ["--check"]:
        same = out.is_file() and out.read_text(encoding="utf-8") == text
        print(f"{OUT}: {'is' if same else 'IS NOT'} what tools/build_verify.py builds")
        return 0 if same else 1
    if argv:
        raise SystemExit(__doc__)
    out.write_text(text, encoding="utf-8")
    print(f"{OUT}: {len(text.encode())} bytes, {len(text.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
