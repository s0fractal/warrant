#!/usr/bin/env python3
"""Tests for tools/pack_pdf.py — the polyglot evidence envelope.

WHAT THIS HARNESS IS BUILT TO AVOID
-----------------------------------
  * *a PDF that is only a PDF to a lenient reader.* Poppler silently repairs a
    `startxref` that points into a content stream, so "it opened" proves
    nothing. Section A walks the xref table itself and requires every offset to
    address the object it claims — the exact corruption an audit of a sibling
    project found shipped in four files.

  * *an archive that escapes its destination.* Section C builds hostile members
    by hand (`../`, absolute, symlink, device) and requires a refusal BEFORE any
    byte is written.

  * *a document that verifies itself.* Section D asserts the envelope does NOT
    adjudicate: running it must not print a verdict about its own contents.
    This is a property test on a deliberate absence, because the absence is the
    design.
"""
import base64
import gzip
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "impl"))


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


W = _load("warrant", "impl/warrant.py")
pp = _load("pack_pdf", "tools/pack_pdf.py")

ok = []
_TMP = []
DEMO = ROOT / "demos" / "refund-chain"


def chk(cond, label, detail=""):
    ok.append(bool(cond))
    print(("OK  " if cond else "FAIL"), label, "" if cond else f"-> {detail}")


def tmp(prefix="pack-test-"):
    d = tempfile.mkdtemp(prefix=prefix)
    _TMP.append(d)
    return pathlib.Path(d)


def ensure_demo():
    if not (DEMO / "pack" / ".warrants" / "records").is_dir():
        subprocess.run([sys.executable, str(DEMO / "build.py")],
                       capture_output=True, cwd=str(ROOT), check=True)
    return DEMO / "pack"


def build(out, pack=None):
    pack = pack or ensure_demo()
    data = pp.compose(pack / ".warrants", "Test pack", "subtitle",
                      pp.summarize_pack(pack))
    out.write_bytes(data)
    return data


# ------------------------------------------------- A. it is really a PDF
def test_pdf_structure():
    data = build(tmp() / "a.pdf")
    chk(data.startswith(b"# coding: utf-8\n"), "starts as a Python source file")
    chk(b"%PDF-1.7" in data[:64], "the PDF header is inside the first 1024 bytes")
    chk(data.rstrip().endswith(b"sys.exit(main())"),
        "and ends as a Python script")

    # Walk the xref exactly as a strict validator would.
    tail = data[data.rfind(b"startxref"):]
    m = re.search(rb"startxref\s+(\d+)", tail)
    chk(m is not None, "there is a startxref")
    xstart = int(m.group(1))
    chk(data[xstart:xstart + 4] == b"xref",
        "startxref addresses the xref table, not a content stream",
        f"found {data[xstart:xstart + 20]!r}")

    entries = re.findall(rb"^(\d{10}) 00000 n $",
                         data[xstart:data.find(b"trailer", xstart)],
                         re.MULTILINE)
    chk(len(entries) == 7, f"seven in-use xref entries (got {len(entries)})")
    bad = []
    for i, e in enumerate(entries, 1):
        off = int(e)
        if not data[off:].startswith(f"{i} 0 obj".encode()):
            bad.append((i, off, data[off:off + 16]))
    chk(not bad, "every xref offset addresses the object it claims", bad)

    # And a real parser agrees, if one is installed.
    p = tmp() / "b.pdf"
    p.write_bytes(data)
    try:
        r = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True)
        chk(r.returncode == 0 and "Pages:" in r.stdout,
            "pdfinfo parses it", r.stderr[:120])
    except FileNotFoundError:
        chk(True, "pdfinfo not installed — structural check above stands alone")


# ------------------------------------------- B. round trip and determinism
def test_round_trip_and_determinism():
    pack = ensure_demo()
    src_store = pack / ".warrants"
    out = tmp() / "c.pdf"
    data = build(out, pack)

    again = pp.compose(src_store, "Test pack", "subtitle", pp.summarize_pack(pack))
    chk(data == again, "the same store produces byte-identical output",
        f"{hashlib.sha256(data).hexdigest()[:12]} != "
        f"{hashlib.sha256(again).hexdigest()[:12]}")

    dest = tmp()
    r = subprocess.run([sys.executable, str(out), "--extract", str(dest)],
                       capture_output=True, text=True)
    chk(r.returncode == 0, "the file runs as a script and extracts", r.stderr[-300:])

    got = dest / ".warrants"
    chk(got.is_dir(), "extraction produces a store at DIR/.warrants")
    diff = subprocess.run(["diff", "-r", str(got), str(src_store)],
                          capture_output=True, text=True)
    chk(diff.returncode == 0, "extracted store is byte-identical to the original",
        diff.stdout[:300])

    # The extracted store must verify with the repository's own verifier —
    # which is the point: the bytes travelled, the trust did not.
    v = subprocess.run([sys.executable, str(ROOT / "impl" / "warrant.py"),
                        "--store", str(got), "verify"],
                       capture_output=True, text=True)
    chk(v.returncode == 0 and "0 errors" in v.stdout,
        "the extracted store verifies with an independent verifier",
        (v.stdout + v.stderr)[-300:])
    fpres = subprocess.run([sys.executable, str(ROOT / "impl" / "fact_provenance.py"),
                            "--store", str(got)], capture_output=True, text=True)
    chk("stale" in fpres.stdout,
        "and the provenance profile still finds the stale derivation")


# ------------------------------------------------------- C. hostile archives
def _archive(*members):
    """members: (name, kind, linkname, payload) -> deterministic tar.gz bytes."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as t:
        for name, kind, linkname, payload in members:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = linkname
            info.size = len(payload) if kind == tarfile.REGTYPE else 0
            t.addfile(info,
                      io.BytesIO(payload) if kind == tarfile.REGTYPE else None)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def test_extraction_refusals():
    def archive(name, *, kind=tarfile.REGTYPE, linkname=""):
        return _archive((name, kind, linkname, b"pwned\n"))

    cases = [
        ("../escaped.txt", tarfile.REGTYPE, "", "parent-directory traversal"),
        ("a/../../escaped.txt", tarfile.REGTYPE, "", "traversal through a subdir"),
        ("/tmp/absolute.txt", tarfile.REGTYPE, "", "absolute path"),
        ("link", tarfile.SYMTYPE, "/etc/passwd", "symlink"),
        ("hard", tarfile.LNKTYPE, "/etc/passwd", "hard link"),
        ("dev", tarfile.CHRTYPE, "", "character device"),
    ]
    for name, kind, link, label in cases:
        dest = tmp()
        before = sorted(p.name for p in dest.rglob("*"))
        try:
            pp.unpack_store(archive(name, kind=kind, linkname=link), dest)
            chk(False, f"refuses: {label}", "extracted instead")
        except ValueError as e:
            after = sorted(p.name for p in dest.rglob("*"))
            chk(before == after, f"refuses: {label} (and writes nothing)",
                f"wrote {set(after) - set(before)}")
        except Exception as e:
            chk(False, f"refuses: {label}", f"wrong exception {e!r}")

    # F5: a hostile member AFTER a valid one. The refusal must leave the
    # destination exactly as it was. Validating and writing member by member
    # refused the traversal and still replaced `existing` first.
    def hostile():
        return _archive(("existing", tarfile.REGTYPE, "", b"REPLACED"),
                        ("../escape", tarfile.REGTYPE, "", b"pwned\n"))

    dest = tmp()
    (dest / "existing").write_text("ORIGINAL")
    try:
        pp.unpack_store(hostile(), dest)
        chk(False, "library: hostile member after a valid one is refused",
            "extracted")
    except ValueError as e:
        chk("outside destination" in str(e),
            "library: hostile member after a valid one is refused", str(e)[:70])
    chk((dest / "existing").read_text() == "ORIGINAL",
        "library: the refusal leaves the pre-existing file untouched",
        f"became {(dest / 'existing').read_text()!r}")
    chk(not (dest.parent / "escape").exists(),
        "library: nothing is written outside the destination")

    # The same property for the runner that actually travels in the file: its
    # source is executed verbatim, with the hostile archive as the operand.
    dest = tmp()
    (dest / "existing").write_text("ORIGINAL")
    ns = {"PACK": base64.b64encode(hostile()).decode(), "MANIFEST_TEXT": ""}
    exec(compile(pp.RUNNER, "<embedded-runner>", "exec"), ns)
    try:
        ns["_extract"](str(dest))
        chk(False, "embedded runner: hostile member is refused", "extracted")
    except SystemExit as e:
        chk("outside destination" in str(e),
            "embedded runner: hostile member is refused", str(e)[:70])
    chk((dest / "existing").read_text() == "ORIGINAL",
        "embedded runner: the refusal leaves the pre-existing file untouched",
        f"became {(dest / 'existing').read_text()!r}")

    # H2: `node` and `node/child` in one archive. The conflict is structural
    # and order-independent; catching it only when mkdir raises meant the
    # failure landed after earlier members had been written.
    for order in (("existing", "node", "node/child"),
                  ("existing", "node/child", "node")):
        members = {"existing": b"REPLACED", "node": b"FILE",
                   "node/child": b"CHILD"}
        blob = _archive(*[(n, tarfile.REGTYPE, "", members[n]) for n in order])
        dest = tmp()
        (dest / "existing").write_text("ORIGINAL")
        try:
            pp.unpack_store(blob, dest)
            chk(False, f"library: file/parent conflict {order} is refused",
                "extracted")
        except ValueError as e:
            chk("as a directory" in str(e),
                f"library: file/parent conflict {order} is refused", str(e)[:70])
        chk((dest / "existing").read_text() == "ORIGINAL",
            f"library: {order} leaves the pre-existing file untouched",
            f"became {(dest / 'existing').read_text()!r}")

        dest = tmp()
        (dest / "existing").write_text("ORIGINAL")
        ns = {"PACK": base64.b64encode(blob).decode(), "MANIFEST_TEXT": ""}
        exec(compile(pp.RUNNER, "<embedded-runner>", "exec"), ns)
        try:
            ns["_extract"](str(dest))
            chk(False, f"embedded runner: conflict {order} is refused",
                "extracted")
        except SystemExit as e:
            chk("as a directory" in str(e),
                f"embedded runner: conflict {order} is refused", str(e)[:70])
        chk((dest / "existing").read_text() == "ORIGINAL",
            f"embedded runner: {order} leaves the pre-existing file untouched",
            f"became {(dest / 'existing').read_text()!r}")

    # A member whose parent already exists as a FILE in the destination.
    dest = tmp()
    (dest / "node").write_text("PREEXISTING FILE")
    try:
        pp.unpack_store(_archive(("node/child", tarfile.REGTYPE, "", b"x")), dest)
        chk(False, "refuses a member whose parent exists as a file", "extracted")
    except ValueError as e:
        chk("already exists there" in str(e),
            "refuses a member whose parent exists as a file", str(e)[:70])
    chk((dest / "node").read_text() == "PREEXISTING FILE",
        "and leaves that file untouched")

    # A member that would replace an existing directory.
    dest = tmp()
    (dest / "node").mkdir()
    try:
        pp.unpack_store(_archive(("node", tarfile.REGTYPE, "", b"x")), dest)
        chk(False, "refuses a member that would replace a directory", "extracted")
    except ValueError as e:
        chk("existing directory" in str(e),
            "refuses a member that would replace a directory", str(e)[:70])

    # Two members resolving to one target are refused up front too.
    dest = tmp()
    try:
        pp.unpack_store(_archive(("a/../x", tarfile.REGTYPE, "", b"1"),
                                 ("x", tarfile.REGTYPE, "", b"2")), dest)
        chk(False, "refuses: two members resolving to one path", "extracted")
    except ValueError as e:
        chk("same path" in str(e), "refuses: two members resolving to one path",
            str(e)[:70])

    # And the guard is load-bearing: without it, the traversal case escapes.
    dest = tmp()
    blob = archive("../escaped.txt")
    raw = gzip.decompress(blob)
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as t:
        names = [m.name for m in t.getmembers()]
    chk(names == ["../escaped.txt"],
        "control: the hostile fixture really does contain a traversal", names)


# ------------------------------------------ D. it does NOT verify itself
def test_does_not_adjudicate():
    """The envelope's most important property is an absence."""
    out = tmp() / "d.pdf"
    build(out)
    r = subprocess.run([sys.executable, str(out)], capture_output=True, text=True)
    chk(r.returncode == 0, "running it with no arguments succeeds", r.stderr[-200:])
    text = r.stdout.lower()
    for word in ("verified", "sound", "q.e.d", "all checks pass", "valid signature"):
        chk(word not in text,
            f"the envelope never prints {word!r} about its own contents",
            f"found in: {r.stdout[:200]}")
    chk("does not verify itself" in text,
        "it says plainly that it does not verify itself")
    chk("independently" in text,
        "and points at a verifier obtained independently")

    # It must also not import or execute anything from the store it carries.
    src = (ROOT / "tools" / "pack_pdf.py").read_text()
    runner = src[src.index("RUNNER = "):src.index("def make_manifest_text")]
    for danger in ("exec(", "eval(", "os.system", "subprocess", "runpy",
                   "importlib", "__import__"):
        chk(danger not in runner,
            f"the embedded runner contains no {danger!r}")


def main():
    print("=" * 66)
    print("  pack_pdf — the polyglot evidence envelope")
    print("=" * 66)
    try:
        test_pdf_structure()
        test_round_trip_and_determinism()
        test_extraction_refusals()
        test_does_not_adjudicate()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    good = all(ok)
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("PACK-PDF: ALL PASS" if good else "PACK-PDF: FAILURES PRESENT")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
