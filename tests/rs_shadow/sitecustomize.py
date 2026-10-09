"""Shadow every reference-CLI invocation with the Rust implementation.

Loaded automatically (Python imports `sitecustomize` from sys.path at startup)
when tests/rs_parity.py puts this directory on PYTHONPATH. Inside a test
harness, every `subprocess.run([python, .../impl/warrant.py, ...])` is run as
usual AND, against a private copy of whatever it may write, as
`warrant-rs ...` with the same arguments. stdout, the exit status and — for the
writing verbs — the bytes left on disk must be identical. Each comparison is
appended as one JSON line to $WARRANT_RS_SHADOW_LOG.

The harness under test sees only the reference's result: shadowing never
changes what a test observes, so a harness that passes without the shadow
passes with it, and every mismatch is a finding about the Rust implementation
(or about the reference), never about the harness.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

def _chain():
    """Run the interpreter's own sitecustomize, which this one shadows (Homebrew
    Python uses it to put site-packages on the path)."""
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    for d in sys.path:
        if os.path.abspath(d or ".") == here:
            continue
        cand = os.path.join(d or ".", "sitecustomize.py")
        if os.path.isfile(cand):
            spec = importlib.util.spec_from_file_location("_chained_sitecustomize", cand)
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
            return


_chain()
_RS = os.environ.get("WARRANT_RS_SHADOW")
_LOG = os.environ.get("WARRANT_RS_SHADOW_LOG")
_orig_run = subprocess.run

# Verbs whose output is random by construction: compared on exit status only.
_RANDOM = {"keygen"}
_WRITERS = {"init", "blob", "policy", "propose", "accept", "reject", "supersede",
            "resign", "keygen"}


def _reference_argv(args):
    if not isinstance(args, (list, tuple)) or len(args) < 2:
        return None
    a0, a1 = str(args[0]), str(args[1])
    if Path(a1).name == "warrant.py" and Path(a1).parent.name == "impl" \
            and "python" in Path(a0).name:
        return [str(x) for x in args[2:]]
    return None


def _split(wargs):
    """(store_value, index_of_store_value or None, cmd, index_of_cmd)."""
    store, sidx, i = ".warrants", None, 0
    while i < len(wargs) and wargs[i].startswith("-"):
        if wargs[i] == "--store" and i + 1 < len(wargs):
            store, sidx = wargs[i + 1], i + 1
            i += 2
        elif wargs[i].startswith("--store="):
            store, sidx = wargs[i][8:], i
            i += 1
        else:
            i += 1
    return store, sidx, (wargs[i] if i < len(wargs) else None), i


def _tree(root):
    out = {}
    root = Path(root)
    if not root.exists():
        return out
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        out[rel] = None if p.is_dir() else p.read_bytes()
    return out


def _log(rec):
    if _LOG:
        with open(_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=True) + "\n")


def _as_text(x):
    if x is None:
        return ""
    return x.decode("utf-8", "replace") if isinstance(x, bytes) else x


def run(*popenargs, **kw):
    args = popenargs[0] if popenargs else kw.get("args")
    wargs = _reference_argv(args)
    if wargs is None or not _RS:
        return _orig_run(*popenargs, **kw)
    env = kw.get("env") or os.environ
    cwd = kw.get("cwd") or os.getcwd()
    store, sidx, cmd, cidx = _split(wargs)
    if env.get("SIGMA_GLYPH") or env.get("WARRANT_SIGMA_DIFFERENTIAL"):
        # An unpinned evaluator override is a Python-only mode by design.
        return _orig_run(*popenargs, **kw)
    tmp = tempfile.mkdtemp(prefix="rs-shadow-")
    rs_args = list(wargs)
    mapping = []                      # (rust-side path, reference-side text)
    copies = []                       # (reference path, rust-side path)
    if cmd in _WRITERS:
        src = Path(cwd, store)
        dst = Path(tmp, "store")
        if src.exists():
            shutil.copytree(src, dst, symlinks=True)
        if sidx is None:
            rs_args = ["--store", str(dst)] + rs_args
            cidx += 2
        elif rs_args[sidx].startswith("--store="):
            rs_args[sidx] = "--store=" + str(dst)
        else:
            rs_args[sidx] = str(dst)
        mapping.append((str(dst), str(Path(store))))
        copies.append((src, dst))
        if cmd == "resign":
            # Explicit envelope files are rewritten in place: give Rust copies.
            j = cidx + 1
            while j < len(rs_args):
                if rs_args[j] == "--key":
                    j += 2
                    continue
                if not rs_args[j].startswith("-"):
                    f = Path(cwd, rs_args[j])
                    if f.is_file():
                        c = Path(tmp, f"f{j}", f.name)
                        c.parent.mkdir()
                        shutil.copy2(f, c)
                        mapping.append((str(c), str(Path(rs_args[j]))))
                        copies.append((f, c))
                        rs_args[j] = str(c)
                j += 1
    want_text = kw.get("text") or kw.get("universal_newlines") or kw.get("encoding")
    pkw = dict(kw)
    pkw.pop("args", None)
    captured_by_caller = (kw.get("capture_output") or kw.get("stdout") is not None)
    if not captured_by_caller:
        pkw["capture_output"] = True
    pkw.pop("check", None)
    py = _orig_run(*popenargs, **pkw) if popenargs else _orig_run(args, **pkw)
    rkw = {k: v for k, v in kw.items() if k in ("cwd", "env", "input", "timeout",
                                                "text", "encoding", "errors",
                                                "universal_newlines")}
    try:
        rs = _orig_run([_RS] + rs_args, capture_output=True, **rkw)
        rs_out = _as_text(rs.stdout)
        for a, b in mapping:
            rs_out = rs_out.replace(a, b)
        rec = {"argv": wargs, "cwd": cwd, "cmd": cmd,
               "py_code": py.returncode, "rs_code": rs.returncode,
               "same_code": py.returncode == rs.returncode}
        py_out = _as_text(py.stdout)
        if cmd == "probe":
            try:
                req = json.loads(_as_text(kw.get("input")))
            except Exception:
                req = {}
            if isinstance(req, dict) and req.get("class") == "capabilities":
                py_out = rs_out = "(capabilities differ by design: the name)"
        if cmd in _RANDOM:
            py_out = rs_out = "(random)"
        rec["same_out"] = py_out == rs_out
        if not rec["same_out"]:
            rec["py_out"], rec["rs_out"] = py_out[-4000:], rs_out[-4000:]
            rec["py_err"], rec["rs_err"] = _as_text(py.stderr)[-2000:], _as_text(rs.stderr)[-2000:]
        if cmd in _WRITERS and cmd not in _RANDOM:
            same_disk = True
            for a, b in copies:
                ta, tb = (_tree(a), _tree(b)) if Path(a).is_dir() or Path(b).is_dir() else (
                    {"": Path(a).read_bytes() if Path(a).exists() else None},
                    {"": Path(b).read_bytes() if Path(b).exists() else None})
                if ta != tb:
                    same_disk = False
                    rec.setdefault("disk_diff", []).append(sorted(
                        k for k in set(ta) | set(tb) if ta.get(k) != tb.get(k))[:20])
            rec["same_disk"] = same_disk
        _log(rec)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not captured_by_caller:
        # Give the caller the terminal output it would have had.
        sys.stdout.write(_as_text(py.stdout))
        sys.stderr.write(_as_text(py.stderr))
        py = subprocess.CompletedProcess(py.args, py.returncode, None, None)
    elif not want_text and isinstance(py.stdout, str):
        pass
    if kw.get("check") and py.returncode:
        raise subprocess.CalledProcessError(py.returncode, py.args, py.stdout, py.stderr)
    return py


if _RS:
    subprocess.run = run
