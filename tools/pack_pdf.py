#!/usr/bin/env python3
"""pack_pdf — put an evidence pack into ONE file that is both a readable
document and its own portable archive.

WHAT THIS SOLVES
----------------
A paper's claims and the artifact that backs them drift apart. The paper goes to
a repository or a DOI, the code goes somewhere else, and a reader has to trust
the author that the numbers in the prose came out of the code. Neither a PDF nor
a git repository fixes this: one carries the story without the evidence, the
other carries the evidence without the story, and only one of them is a thing a
lawyer, a regulator or a reviewer will actually open.

The output of this tool is a single file that is simultaneously:

  * a valid ISO 32000 PDF — it opens in Preview, Acrobat or a browser and reads
    as a document, for the reader who will never run anything; and
  * a valid Python script — `python3 pack.pdf --extract DIR` writes the warrant
    store back out, byte for byte, for the reader who will.

The polyglot works because the two formats seek from opposite ends: Python reads
forward from byte 0 and sees the whole PDF inside a raw docstring; a PDF reader
seeks backward from `%%EOF` to `startxref`. Neither trips over the other.

WHAT THIS IS NOT — READ THIS BEFORE TRUSTING THE OUTPUT
-------------------------------------------------------
**This file is a transport, not a trust root, and it does not verify itself.**

A self-executing document that prints its own green checkmark proves nothing: an
attacker who edits the evidence edits the verifier in the same file, in the same
edit. Running a stranger's document to find out whether the stranger's document
is honest is not verification, it is theatre — and it is the exact defect an
audit of a sibling project (`black-heart`, review 9) found being shipped as an
`audit` command.

So `python3 pack.pdf` DELIBERATELY does not adjudicate anything. It extracts,
lists what it holds, and prints the commands to run against a verifier you
obtained independently of this file. The claim it makes about itself is only:
*here are the bytes; check them with something I did not give you.*

DETERMINISM
-----------
The same store produces byte-identical output: tar entries are sorted with
zeroed metadata and gzip is mtime-free, so the artifact is content-addressable
and two builds can be compared by hash.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path

PDF_HEADER = b"# coding: utf-8\n" + b'r"""%PDF-1.7\n' + b"%\xe2\x9a\x93\xf0\x9f\x93\x84\n"
MARKER = "# ---- WARRANT-PACK-V0 (base64 tar.gz of the store) ----"
WRAP = 96


# ------------------------------------------------------------------ archive
def pack_store(store_dir: Path, prefix: str = ".warrants") -> bytes:
    """Deterministic tar.gz of a warrant store: sorted names, zeroed metadata,
    no gzip timestamp. Same input bytes -> same output bytes, always.

    Members are named under `prefix`, so extracting to DIR yields a directory
    the verifier can be pointed at as `DIR/.warrants` — the same shape the
    demo packs have on disk."""
    files = sorted(
        (p for p in store_dir.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(store_dir).as_posix())
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for p in files:
            info = tarfile.TarInfo(
                f"{prefix}/{p.relative_to(store_dir).as_posix()}")
            data = p.read_bytes()
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.type = tarfile.REGTYPE
            tar.addfile(info, io.BytesIO(data))
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def _plan(members, dest: Path):
    """Validate EVERY member and resolve every target before one byte is
    written. Extraction used to validate and write member by member, so a
    hostile member late in the archive was refused only after an earlier one
    had already replaced a file in the destination (review F5): the refusal was
    real, the destination was not left alone. Returns [(member, target)]."""
    plan, seen = [], {}
    for m in members:
        if not m.isreg():
            raise ValueError(f"refusing non-regular archive member {m.name!r}")
        target = (dest / m.name).resolve()
        if not str(target).startswith(str(dest) + os.sep):
            raise ValueError(f"refusing member outside destination: {m.name!r}")
        if target in seen:
            raise ValueError(
                f"refusing archive: {m.name!r} and {seen[target]!r} resolve to "
                "the same path")
        seen[target] = m.name
        plan.append((m, target))
    return plan


def unpack_store(blob: bytes, dest: Path) -> list[str]:
    """Extract the archive under `dest`.

    Nothing is written until every member has been validated: absolute paths,
    `..` traversal, links, devices and colliding targets are all refused with
    the destination untouched."""
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(blob)), mode="r:") as t:
        plan = _plan(t.getmembers(), dest)      # refuses before any write
        written = []
        for m, target in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(t.extractfile(m).read())
            written.append(m.name)
    return sorted(written)


# ---------------------------------------------------------------------- PDF
def _esc(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _page_stream(lines) -> bytes:
    out = ["BT", "/F1 15 Tf", "56 760 Td", "17 TL"]
    font = "/F1 15 Tf"
    for kind, text in lines:
        want = {"h": "/F1 15 Tf", "b": "/F2 10 Tf", "m": "/F3 9 Tf"}[kind]
        if want != font:
            out.append(want)
            font = want
        out.append(f"({_esc(text)}) Tj T*")
    out.append("ET")
    return "\n".join(out).encode("latin-1", "replace")


def build_pdf(lines, archive_b64: str, runner: str) -> bytes:
    """Assemble the polyglot. The xref offsets are computed from the real byte
    positions and asserted below, because a `startxref` that points into a
    content stream is exactly the silent corruption a strict validator would
    catch and a lenient reader would repair without telling anyone."""
    stream = _page_stream(lines)
    objs = [
        b"<</Type /Catalog /Pages 2 0 R>>",
        b"<</Type /Pages /Kids [3 0 R] /Count 1>>",
        b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources <</Font <</F1 5 0 R /F2 6 0 R /F3 7 0 R>>>> /Contents 4 0 R>>",
        b"<</Length " + str(len(stream)).encode() + b">>\nstream\n" + stream
        + b"\nendstream",
        b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold>>",
        b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>",
        b"<</Type /Font /Subtype /Type1 /BaseFont /Courier>>",
    ]
    body = bytearray(PDF_HEADER)
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(body))
        body += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xstart = len(body)
    body += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        body += f"{off:010d} 00000 n \n".encode()
    body += (f"trailer\n<</Size {len(objs) + 1} /Root 1 0 R>>\n"
             f"startxref\n{xstart}\n%%EOF\n").encode()
    body += b'"""\n'

    # The offsets must actually address their objects. Assert, do not hope.
    for i, off in enumerate(offsets, 1):
        assert body[off:off + len(f"{i} 0 obj")] == f"{i} 0 obj".encode(), \
            f"xref entry {i} does not address `{i} 0 obj`"
    assert body[xstart:xstart + 4] == b"xref", "startxref does not address the table"

    # The archive is bound BEFORE the runner: the runner ends with a
    # `__main__` guard that calls into it, so a name defined after that guard
    # does not exist when it runs.
    body += f"{MARKER}\nPACK = '''\\\n".encode()
    for i in range(0, len(archive_b64), WRAP):
        body += archive_b64[i:i + WRAP].encode() + b"\n"
    body += b"'''\n"
    body += runner.encode("utf-8")
    return bytes(body)


# ------------------------------------------------------------------- runner
RUNNER = '''
import base64, gzip, hashlib, io, json, os, sys, tarfile

# This file is a TRANSPORT, not a trust root. It does not adjudicate anything
# about itself: whoever edited the evidence could edit this code in the same
# edit. It extracts, lists, and points at a verifier you obtained elsewhere.

def _blob():
    return base64.b64decode("".join(PACK.split()))

def _members():
    raw = gzip.decompress(_blob())
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as t:
        return [(m.name, m.size) for m in t.getmembers() if m.isreg()]

def _extract(dest):
    # Every member is validated and every target resolved BEFORE one byte is
    # written. Validating and writing member by member meant a hostile member
    # late in the archive was refused only after an earlier one had already
    # replaced a file in the destination: the refusal was real, the
    # destination was not left alone.
    dest = os.path.realpath(dest)
    os.makedirs(dest, exist_ok=True)
    raw = gzip.decompress(_blob())
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as t:
        plan, seen = [], {}
        for m in t.getmembers():
            if not m.isreg():
                raise SystemExit("refusing non-regular archive member: " + m.name)
            p = os.path.realpath(os.path.join(dest, m.name))
            if not p.startswith(dest + os.sep):
                raise SystemExit("refusing member outside destination: " + m.name)
            if p in seen:
                raise SystemExit("refusing archive: %s and %s resolve to the "
                                 "same path" % (m.name, seen[p]))
            seen[p] = m.name
            plan.append((m, p))
        for m, p in plan:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(t.extractfile(m).read())
    return dest, len(plan)

def main():
    args = sys.argv[1:]
    if args and args[0] == "--extract":
        dest = args[1] if len(args) > 1 else "extracted-store"
        where, n = _extract(dest)
        print("extracted %d file(s) to %s" % (n, where))
        print()
        print("Now verify with a verifier you did NOT get from this file:")
        print("  pip install warrant-verify   # or clone the repository")
        print("  warrant --store %s verify" % os.path.join(where, ".warrants"))
        return 0
    print(MANIFEST_TEXT)
    print("archive: %d file(s), sha256 %s" % (len(_members()),
          hashlib.sha256(_blob()).hexdigest()[:16] + "..."))
    print()
    print("  python3 %s --extract DIR    write the store back out"
          % os.path.basename(__file__))
    print()
    print("This file does not verify itself, on purpose. A document that prints")
    print("its own green checkmark proves nothing: an attacker who edits the")
    print("evidence edits the checker in the same edit. Extract, then check the")
    print("bytes with a verifier obtained independently of this file.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


def make_manifest_text(title, subtitle, lines):
    body = "\n".join(t for _, t in lines)
    return json.dumps(f"{title}\n{subtitle}\n\n{body}")


# --------------------------------------------------------------------- main
def compose(store_dir: Path, title: str, subtitle: str, summary_lines):
    archive = pack_store(store_dir)
    b64 = base64.b64encode(archive).decode()
    lines = [("h", title), ("b", subtitle), ("b", "")] + summary_lines
    lines += [
        ("b", ""),
        ("m", "This file is also a Python script:"),
        ("m", "    python3 <thisfile> --extract DIR"),
        ("m", ""),
        ("m", "It does not verify itself. A document that prints its own green"),
        ("m", "checkmark proves nothing, because whoever edited the evidence"),
        ("m", "edited the checker in the same edit. Extract, then check with a"),
        ("m", "verifier obtained independently of this file."),
        ("m", ""),
        ("m", f"archive sha256: {hashlib.sha256(archive).hexdigest()}"),
    ]
    runner = ("MANIFEST_TEXT = " + make_manifest_text(title, subtitle, summary_lines)
              + "\n" + RUNNER)
    return build_pdf(lines, b64, runner)


def summarize_pack(pack_dir: Path):
    """Read a demo pack's manifest.json into display lines, if it has one."""
    mf = pack_dir / "manifest.json"
    if not mf.exists():
        return []
    m = json.loads(mf.read_text())
    out = [("b", m.get("title", "")), ("b", "")]
    if m.get("story"):
        out += [("m", "story: " + m["story"][:88]), ("b", "")]
    for name, wid in (m.get("chain") or {}).items():
        out.append(("m", f"  {name:<14} {wid[:24]}…"))
    for name, wid in (m.get("reopening") or {}).items():
        out.append(("m", f"  {name:<14} {wid[:24]}…"))
    if m.get("ski_checks"):
        out += [("b", ""), ("m", "re-runnable checks:")]
        for c in m["ski_checks"]:
            out.append(("m", f"  {c.get('name', '?'):<20} answer="
                             f"{str(c.get('answer')).lower():<6} "
                             f"{c.get('atp')} ATP"))
    for k, v in (m.get("derived_facts") or {}).items():
        out.append(("m", f"  {k:<20} -> {v.get('state_after_reopening')}"))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="pack_pdf",
        description="Put a warrant evidence pack into one file that is both a "
                    "readable PDF and its own portable archive.")
    ap.add_argument("pack", help="directory holding .warrants (a demo pack)")
    ap.add_argument("-o", "--out", required=True, help="output .pdf path")
    ap.add_argument("-t", "--title", default="Warrant evidence pack")
    ap.add_argument("-s", "--subtitle", default="")
    a = ap.parse_args(argv)

    pack_dir = Path(a.pack)
    store = pack_dir / ".warrants"
    if not (store / "records").is_dir():
        sys.exit(f"no warrant store at {store}")

    data = compose(store, a.title, a.subtitle, summarize_pack(pack_dir))
    Path(a.out).write_bytes(data)
    print(f"wrote {a.out}  ({len(data):,} bytes, sha256 "
          f"{hashlib.sha256(data).hexdigest()[:16]}…)")
    print("  opens as a PDF; runs as: python3 " + a.out + " --extract DIR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
