#!/usr/bin/env python3
"""QUICKSTART.md, run from the document itself: every command it shows, and every output.

The page is read under one closed format, and anything else in it is refused, so nothing can
render as a command that is not run, or run without being shown:
- a fence is a line that is exactly "```sh NAME" (NAME: lowercase letters, digits, "-"; each
  once), "```output" or "```"; any other line starting with ``` or ~~~ is refused, as is a
  line outside a fence starting with four spaces or a tab (Markdown would show it as code)
  and "<!--" (a comment would hide a fence from the reader);
- each `sh` block may be followed, before the next `sh` block, by one `output` block: its
  standard output, byte for byte (each line ends in a newline). An `sh` block with none must
  print nothing.

The blocks run in order, in one `bash --noprofile --norc -eu -o pipefail` process, in a fresh
empty directory, with the interpreter running this test first on PATH (its `warrant` and
`python3`) and WARRANT_IMPL, when set, on PYTHONPATH (so a mutant copy is what runs). One
substitution is made before comparing, and the page states it: the 64-hex value of
`"assessment_id"` reads `…`, since it names the installed engine's code and the optional
compute provider. Standard error may hold only the warning a reading command prints when no
compute provider is installed.

    python3 tests/quickstart_test.py
    python3 tests/quickstart_test.py --write     # put the outputs the commands print now into the page
"""
import argparse
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from world import ROOT, check, finish

PAGE = ROOT / "QUICKSTART.md"
OPEN_SH = re.compile(r"```sh ([a-z][a-z0-9-]*)\Z")
ASSESSMENT = re.compile(r'("assessment_id": ")[0-9a-f]{64}(")')
NO_PROVIDER = ("warning: provider unavailable, replays are UNVERIFIED: no Sigma provider installed "
               "(pip install the sigma-glyph wheel that ships sigma_provider)")


class Refused(Exception):
    pass


def parse(text):
    """[{name, code, output (None or text), at: line indexes of the output block's two fences}]."""
    steps, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        if line.startswith(("```", "~~~")):
            m = OPEN_SH.match(line)
            if not m and line != "```output":
                raise Refused(f"line {i + 1}: not a fence of this page's format: {line!r}")
            body, j = [], i + 1
            while j < len(lines) and lines[j] != "```":
                if lines[j].startswith(("```", "~~~")):
                    raise Refused(f"line {j + 1}: a fence inside a block: {lines[j]!r}")
                body.append(lines[j])
                j += 1
            if j == len(lines):
                raise Refused(f"line {i + 1}: block never closed")
            if m:
                if m.group(1) in {s["name"] for s in steps}:
                    raise Refused(f"line {i + 1}: step {m.group(1)!r} named twice")
                steps.append({"name": m.group(1), "code": "\n".join(body) + "\n", "output": None, "at": None})
            elif not steps or steps[-1]["output"] is not None:
                raise Refused(f"line {i + 1}: an output block with no command block before it")
            elif not any(body):
                raise Refused(f"line {i + 1}: an empty output block (leave it out instead)")
            else:
                steps[-1].update(output="\n".join(body) + "\n", at=(i, j))
            i = j + 1
            continue
        if line.startswith(("    ", "\t")) or "<!--" in line:
            raise Refused(f"line {i + 1}: outside a fence, Markdown would show this as code or hide it: {line!r}")
        i += 1
    if not steps:
        raise Refused("no command block: the page would test nothing")
    return steps


# Pages the format must refuse, each for one reason, and one it reads.
PLANTED = {
    "an unknown fence": "```bash\necho hi\n```\n",
    "an unnamed command block": "```sh\necho hi\n```\n",
    "a tilde fence": "~~~sh x\necho hi\n~~~\n",
    "an indented line": "    echo hi\n```sh x\necho\n```\n",
    "a tab-indented line": "\techo hi\n```sh x\necho\n```\n",
    "a comment": "<!--\n```sh x\necho hi\n```\n-->\n",
    "a fence inside a block": "```sh x\n```output\n```\n",
    "an unclosed block": "```sh x\necho hi\n",
    "a name used twice": "```sh x\necho\n```\n```sh x\necho\n```\n",
    "an output with no command": "```output\nhi\n```\n",
    "two outputs for one command": "```sh x\necho hi\n```\n```output\nhi\n```\n```output\nhi\n```\n",
    "an empty output": "```sh x\ntrue\n```\n```output\n```\n",
    "no command at all": "# a page\n",
}
READABLE = "# a page\n\n```sh x\necho hi\n```\n\n```output\nhi\n```\n\n```sh y\ntrue\n```\n"


def refused(text):
    try:
        parse(text)
    except Refused:
        return True
    return False


def run(steps):
    """[(stdout, stderr) of each step, or None for a step the script never reached], exit status."""
    tmp = Path(tempfile.mkdtemp(prefix="warrant-quickstart-"))
    work, page = tmp / "work", tmp / "page.sh"
    work.mkdir()
    try:
        mark = f"@@quickstart-{uuid.uuid4().hex}@@"
        script = "".join(f"printf '%s\\n' '{mark}{n}'; printf '%s\\n' '{mark}{n}' >&2\n{s['code']}"
                         for n, s in enumerate(steps)) + f"printf '%s\\n' '{mark}end'; printf '%s\\n' '{mark}end' >&2\n"
        page.write_text(script)
        bindir = str(Path(sys.executable).parent)
        env = dict(os.environ, PATH=bindir + os.pathsep + os.environ.get("PATH", ""), PYTHONIOENCODING="utf-8",
                   PYTHONDONTWRITEBYTECODE="1")
        if os.environ.get("WARRANT_IMPL"):
            env["PYTHONPATH"] = os.environ["WARRANT_IMPL"]
        if shutil.which("warrant", path=env["PATH"]) is None:
            sys.exit(f"no `warrant` command beside {sys.executable} or on PATH: install warrant-graph first")
        p = subprocess.run(["bash", "--noprofile", "--norc", "-eu", "-o", "pipefail", str(page)],
                           cwd=work, env=env, capture_output=True, timeout=300, check=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    def split(stream):
        parts, cur = {}, None
        for line in stream.decode().splitlines(keepends=True):
            if line.startswith(mark) and line.rstrip("\n")[len(mark):] in [*map(str, range(len(steps))), "end"]:
                cur = line.rstrip("\n")[len(mark):]
                parts[cur] = ""
            elif cur is not None:
                parts[cur] += line
        return parts
    out, err = split(p.stdout), split(p.stderr)
    got = [(ASSESSMENT.sub(r"\1…\2", out[str(n)]), err[str(n)]) if str(n) in out else None for n in range(len(steps))]
    return got, p.returncode, "end" in out


def write(text, steps, got):
    """The page with each step's output block set to what it printed (added after the command
    block, changed or left out)."""
    lines = text.split("\n")
    for s, g in sorted(zip(steps, got), key=lambda x: -(x[0]["at"] or (0,))[0]):
        if g is None:
            sys.exit(f"step {s['name']} did not run; nothing written")
        new = ["```output", *g[0].rstrip("\n").split("\n"), "```"] if g[0] else []
        if s["at"]:
            lines[s["at"][0]:s["at"][1] + 1] = new
        else:
            close = _close_of(lines, s["name"])
            lines[close + 1:close + 1] = ["", *new] if new else []
    return "\n".join(lines)


def _close_of(lines, name):
    start = lines.index(f"```sh {name}")
    return lines.index("```", start + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    wrong = [k for k, t in PLANTED.items() if not refused(t)]
    steps = parse(READABLE)
    check("refusals", not wrong and [(x["name"], x["output"]) for x in steps] == [("x", "hi\n"), ("y", None)],
          "the page format refuses each planted page and reads a well-formed one", wrong)
    text = PAGE.read_text()
    try:
        steps = parse(text)
    except Refused as e:
        check("format", False, "QUICKSTART.md is in the page's closed format", str(e))
        return finish("quickstart_test")
    check("format", True, f"QUICKSTART.md is in the page's closed format ({len(steps)} command blocks)")
    got, status, ended = run(steps)
    if a.write:
        PAGE.write_text(write(text, steps, got))
        print(f"wrote {PAGE}")
    for s, g in zip(steps, got):
        if g is None:
            check(s["name"], False, f"{s['name']}: ran", "the page stopped before this block")
            continue
        out, err = g
        bad_err = [line for line in err.splitlines() if line != NO_PROVIDER]
        want = s["output"] or ""
        diff = "".join(difflib.unified_diff(want.splitlines(True), out.splitlines(True), "page", "printed", n=1))
        check(s["name"], out == want and not bad_err, f"{s['name']}: prints exactly the output shown",
              diff[:2000] + ("\nstderr: " + "\n".join(bad_err)[:1000] if bad_err else ""))
    check("end", status == 0 and ended, "the page runs to its end with exit status 0", f"exit {status}")
    return finish("quickstart_test")


if __name__ == "__main__":
    sys.exit(main())
