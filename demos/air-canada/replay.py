#!/usr/bin/env python3
"""Replay the air-canada evidence specimen through the PUBLIC `warrant` CLI.

This file drives an INSTALLED `warrant` command and compares what it prints
against the per-record vector frozen in `replay.json`. It imports nothing from
this repository — only the standard library — so it can be copied next to a
pack and run from any directory, against any installation, and it will refuse,
with a typed reason, rather than quietly test a checkout against itself.

What one run does, in order:

  1. REFUSE unless the environment is the frozen profile: the CLI exists, its
     interpreter can be located, `warrant.py` and the ski@v1 evaluator import
     from the installation prefix (not from a sibling checkout), and the
     evaluator's bytes hash to the pin in the manifest.
  2. REFUSE unless every input file hashes to its frozen digest and no file
     outside the frozen set is present.
  3. For every record: run `verify --json` at base and settlement grade and
     compare THAT RECORD's findings to the frozen list; re-run its ski@v1 check
     with `warrant check` and compare verdict, result and ATP; run `why` and
     compare the exit status. Results are printed per record. There is no
     document-level verdict line, because the CLI does not make one.
  4. Run the fail-closed controls on fresh copies of the pack: a check whose
     verdict must be `fail`; a configured evaluator that cannot load (absent,
     and present-but-broken), which must refuse rather than fall back to the
     bundled engine; a rewritten root blob and a rewritten nested thunk, which
     must be refused as Identity-by-Hash violations. Every control exercises
     the actual CLI path (`warrant check`, `warrant verify --json`).

Exit status: 0 every record and control matched; 1 a record or control did
not; 3 REFUSED (the run could not be performed as frozen — this is not a pass
and not a failure of the specimen).

    python3 replay.py --warrant /path/to/venv/bin/warrant --pack ./pack --manifest ./replay.json
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_FAIL, EXIT_REFUSED = 1, 3
CHECK_LINE = re.compile(r"^(pass|fail)  result=([0-9a-f]{64})  atp_spent=(\d+)$")

# Run with `-I` (isolated: no PYTHONPATH, no user site) by the installation's
# own interpreter. find_spec locates modules WITHOUT importing them, so this
# reports origins and never executes the artifact under test.
ORIGIN_SNIPPET = r"""
import importlib.util, json, sys
out = {}
for m in ("warrant", "sigma_glyph_v05"):
    s = importlib.util.find_spec(m)
    out[m] = s.origin if s else None
try:
    import importlib.metadata as md
    out["version"] = md.version("warrant-verify")
except Exception as e:
    out["version"] = None
    out["version_error"] = type(e).__name__
out["executable"] = sys.executable
out["prefix"] = sys.prefix
print(json.dumps(out))
"""


class Refused(Exception):
    """A typed refusal: `kind` names what could not be established."""

    def __init__(self, kind, detail):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def clean_env(extra=None):
    """The frozen profile: no evaluator override, no differential flag, no
    PYTHONPATH that could shadow the installed module. `extra` is applied AFTER
    scrubbing, so a control can set exactly the override it is testing."""
    env = dict(os.environ)
    for k in ("SIGMA_GLYPH", "WARRANT_SIGMA_DIFFERENTIAL", "PYTHONPATH"):
        env.pop(k, None)
    env["PYTHONNOUSERSITE"] = "1"
    if extra:
        env.update(extra)
    return env


class CLI:
    def __init__(self, warrant, cwd):
        self.warrant = str(warrant)
        self.cwd = str(cwd)

    def run(self, args, env=None):
        try:
            return subprocess.run([self.warrant] + list(args), capture_output=True,
                                  text=True, env=clean_env(env), cwd=self.cwd,
                                  stdin=subprocess.DEVNULL, timeout=120)
        except subprocess.TimeoutExpired:
            raise Refused("environment", f"`warrant {' '.join(args)}` did not finish in 120s")

    def verify_json(self, store, settlement=None, env=None):
        args = ["--store", store, "verify"]
        if settlement:
            args += ["--settlement", "--trust-config", settlement]
        args += ["--json"]
        r = self.run(args, env)
        lines = r.stdout.strip().splitlines()
        if len(lines) != 1:
            return r, None
        try:
            rep = json.loads(lines[0])
        except ValueError:
            return r, None
        if not isinstance(rep, dict) or rep.get("report") != "warrant.verify-report@v0":
            return r, None
        return r, rep

    def check(self, store, check_hex, env=None):
        r = self.run(["--store", store, "check", check_hex], env)
        m = CHECK_LINE.match(r.stdout.strip())
        parsed = (m.group(1), m.group(2), int(m.group(3))) if m else None
        return r, parsed


class Report:
    def __init__(self):
        self.fails = []

    def line(self, ok, label, detail=""):
        tag = "ok  " if ok else "BAD "
        print(f"    {tag} {label}" + (f"  [{detail}]" if (detail and not ok) else ""))
        if not ok:
            self.fails.append(label)
        return ok


# ---------------------------------------------------------------- preflight --
def locate_interpreter(warrant):
    bindir = Path(warrant).resolve().parent
    for name in ("python", "python3", "python.exe"):
        p = bindir / name
        if p.exists():
            return p
    raise Refused("environment",
                  f"no interpreter beside {warrant}; the replay cannot establish which "
                  f"module the command would import (expected a venv-style layout)")


def preflight(warrant, manifest):
    warrant = Path(warrant)
    if not warrant.is_file() or not os.access(warrant, os.X_OK):
        raise Refused("environment", f"`{warrant}` is not an executable warrant CLI")
    python = locate_interpreter(warrant)
    r = subprocess.run([str(python), "-I", "-c", ORIGIN_SNIPPET], capture_output=True,
                       text=True, env=clean_env(), stdin=subprocess.DEVNULL, timeout=60)
    if r.returncode != 0:
        raise Refused("artifact", f"could not interrogate the installation: {r.stderr.strip()[:200]}")
    info = json.loads(r.stdout.strip().splitlines()[-1])
    # The installation prefix is what the interpreter reports (a venv's
    # sys.prefix is the venv), NOT the resolved path of the `python` symlink,
    # which points at the base interpreter. Both sides are realpath'd so a
    # /var -> /private/var style alias cannot make the artifact look foreign.
    prefix = Path(os.path.realpath(info["prefix"]))
    if Path(os.path.realpath(warrant)).parent.parent != prefix:
        raise Refused("artifact", f"`{warrant}` is not the console script of the installation at "
                                  f"{prefix} (its interpreter reports a different prefix)")
    for mod in ("warrant", "sigma_glyph_v05"):
        origin = info.get(mod)
        if not origin:
            raise Refused("artifact", f"module `{mod}` is not importable from {python}")
        inside = os.path.realpath(origin).startswith(str(prefix) + os.sep)
        if not inside:
            raise Refused("artifact", f"`{mod}` would import from {origin}, which is outside the "
                                      f"installation prefix {prefix} — a sibling checkout, not the artifact")
    ev = manifest["evaluator"]
    got = sha256(info["sigma_glyph_v05"])
    if got != ev["sha256"]:
        raise Refused("artifact", f"installed {ev['module']} hashes to {got[:16]}…, not the frozen "
                                  f"{ev['tag']} pin {ev['sha256'][:16]}…")
    if Path(info["sigma_glyph_v05"]).name != ev["module"]:
        raise Refused("artifact", f"evaluator module is {Path(info['sigma_glyph_v05']).name}, "
                                  f"manifest freezes {ev['module']}")
    if info.get("version") is None:
        raise Refused("artifact", "distribution `warrant-verify` is not installed in this prefix "
                                  f"({info.get('version_error')})")
    scrubbed = [k for k in ("SIGMA_GLYPH", "WARRANT_SIGMA_DIFFERENTIAL", "PYTHONPATH") if k in os.environ]
    return {"python": str(python), "prefix": str(prefix), "version": info["version"],
            "warrant_py": info["warrant"], "warrant_py_sha256": sha256(info["warrant"]),
            "evaluator_sha256": got, "scrubbed": scrubbed}


def check_inputs(pack, manifest):
    pack = Path(pack)
    frozen = manifest["inputs"]
    present = sorted(str(p.relative_to(pack)).replace(os.sep, "/")
                     for p in pack.rglob("*") if p.is_file())
    extra = sorted(set(present) - set(frozen))
    missing = sorted(set(frozen) - set(present))
    if missing:
        raise Refused("inputs", f"frozen file(s) absent from the pack: {', '.join(missing[:3])}")
    if extra:
        raise Refused("inputs", f"file(s) outside the frozen input set: {', '.join(extra[:3])}")
    bad = [rel for rel, want in frozen.items() if sha256(pack / rel) != want]
    if bad:
        raise Refused("inputs", f"bytes differ from the frozen digest: {', '.join(bad[:3])}")
    return len(frozen)


# ------------------------------------------------------------------ records --
def findings_for(rep, wid):
    return [{"level": f["level"], "message": f["message"]}
            for f in rep["findings"] if f["subject"] == wid]


def replay_records(cli, pack, manifest, rep):
    store = str(Path(pack) / ".warrants")
    trust = str(Path(pack) / manifest["profile"]["trust_config"])
    records = manifest["records"]

    rb, base = cli.verify_json(store)
    rs, settle = cli.verify_json(store, settlement=trust)
    for label, r, x in (("base", rb, base), ("settlement", rs, settle)):
        if x is None:
            raise Refused("environment", f"`verify --json` ({label}) did not print one "
                                         f"warrant.verify-report@v0 object: {r.stderr.strip()[:160]}")
    print(f"  verify --json: base records={base['records']} grade={base['grade']}; "
          f"settlement records={settle['records']} grade={settle['grade']}")
    rep.line(base["records"] == len(records) and settle["records"] == len(records),
             "record count equals the frozen set", f"{base['records']}/{settle['records']} vs {len(records)}")
    foreign = sorted({f["subject"] for f in base["findings"] + settle["findings"]} - set(records))
    rep.line(not foreign, "no finding names a subject outside the frozen records", ", ".join(foreign))

    for wid, spec in records.items():
        print(f"  record {wid[:16]}…  {spec['decision']} by {spec['actor']}")
        for grade, report in (("base", base), ("settlement", settle)):
            got = findings_for(report, wid)
            want = spec[f"verify_{grade}"]
            rep.line(got == want, f"verify ({grade}): {len(got)} finding(s) for this record, as frozen",
                     f"got {got} want {want}")
        sk = spec.get("ski_check")
        if sk:
            r, parsed = cli.check(store, sk["check"])
            want = (sk["verdict"], sk["result"], sk["atp_spent"])
            rep.line(parsed == want and r.returncode == (0 if sk["verdict"] == "pass" else 1),
                     f"check {sk['check'][:12]}: {sk['verdict']} result={sk['result'][:12]}… "
                     f"atp_spent={sk['atp_spent']}, as frozen",
                     f"stdout={r.stdout.strip()!r} rc={r.returncode} stderr={r.stderr.strip()[:120]!r}")
        r = cli.run(["--store", store, "why", wid])
        rep.line(r.returncode == spec["why_exit"], f"why: exit {spec['why_exit']}",
                 f"rc={r.returncode} {r.stderr.strip()[:120]}")


# ----------------------------------------------------------------- controls --
def fresh_copy(pack, scratch, name):
    dst = Path(scratch) / name
    shutil.copytree(pack, dst)
    return dst


def no_pass(r):
    return not r.stdout.strip().startswith("pass")


def control_verdict_fail(cli, pack, scratch, manifest, rep):
    c = manifest["controls"]["verdict-fail"]
    d = fresh_copy(pack, scratch, "verdict-fail")
    doc = json.dumps({"atp": c["atp"], "expect": c["expect"], "ski": 1, "term": c["term"]},
                     sort_keys=True, separators=(",", ":")).encode()
    h = hashlib.sha256(doc).hexdigest()
    (d / ".warrants" / "blobs" / h).write_bytes(doc)
    print(f"  control verdict-fail: check {h[:12]} (true address, wrong expect)")
    r, parsed = cli.check(str(d / ".warrants"), h)
    e = c["expected"]
    rep.line(parsed == (e["verdict"], e["result"], e["atp_spent"]),
             f"check: {e['verdict']} result={e['result'][:12]}… atp_spent={e['atp_spent']} (the evaluator ran)",
             f"stdout={r.stdout.strip()!r} stderr={r.stderr.strip()[:120]!r}")
    rep.line(r.returncode != 0, "check: exit nonzero", f"rc={r.returncode}")


def control_evaluator(cli, pack, scratch, manifest, rep, name, override_dir):
    c = manifest["controls"][name]
    d = fresh_copy(pack, scratch, name)
    store = str(d / ".warrants")
    trust = str(d / manifest["profile"]["trust_config"])
    reject = next(w for w, s in manifest["records"].items() if s.get("ski_check"))
    chk = manifest["records"][reject]["ski_check"]["check"]
    print(f"  control {name}: SIGMA_GLYPH={override_dir}")
    for flag in (None, "1"):
        env = {"SIGMA_GLYPH": str(override_dir)}
        if flag:
            env["WARRANT_SIGMA_DIFFERENTIAL"] = flag
        r, parsed = cli.check(store, chk, env)
        tag = " (with WARRANT_SIGMA_DIFFERENTIAL=1)" if flag else ""
        rep.line(r.returncode != 0 and parsed is None and no_pass(r)
                 and f"ski@v1 unverified: {c['reason']}" in r.stderr and "Traceback" not in r.stderr,
                 f"check refuses `{c['reason']}`, prints no verdict, no traceback{tag}",
                 f"rc={r.returncode} stdout={r.stdout.strip()!r} stderr={r.stderr.strip()[:160]!r}")
    env = {"SIGMA_GLYPH": str(override_dir)}
    r, base = cli.verify_json(store, env=env)
    got = findings_for(base, reject) if base else None
    rep.line(base is not None and {"level": "WARN", "message": f"ski@v1 unverified: {c['reason']}"} in got
             and "Traceback" not in r.stderr,
             f"verify (base): the citing record reports `ski@v1 unverified: {c['reason']}`",
             f"findings={got} stderr={r.stderr.strip()[:120]!r}")
    r, settle = cli.verify_json(store, settlement=trust, env=env)
    rep.line(settle is not None and settle["ok"] is False and r.returncode != 0
             and settle["findings"] == [{"level": "ERR", "subject": "settlement",
                                         "message": c["settlement_error"]}],
             f"verify (settlement): ok=false, one global ERR `{c['settlement_error']}`",
             f"rc={r.returncode} report={settle}")


def control_cas(cli, pack, scratch, manifest, rep, name, mutate):
    c = manifest["controls"][name]
    d = fresh_copy(pack, scratch, name)
    store = str(d / ".warrants")
    trust = str(d / manifest["profile"]["trust_config"])
    reject = next(w for w, s in manifest["records"].items() if s.get("ski_check"))
    chk = manifest["records"][reject]["ski_check"]["check"]
    target = d / ".warrants" / "blobs" / c["blob"]
    before = target.read_bytes()
    target.write_bytes(mutate(before))
    assert target.read_bytes() != before
    print(f"  control {name}: blob {c['blob'][:12]} rewritten in place ({c['mutation']})")
    r, parsed = cli.check(store, chk)
    rep.line(r.returncode != 0 and parsed is None and no_pass(r)
             and r.stderr.strip() == f"ski@v1 unverified: {c['reason']}",
             f"check refuses `{c['reason']}` (path-free), prints no verdict",
             f"rc={r.returncode} stdout={r.stdout.strip()!r} stderr={r.stderr.strip()[:160]!r}")
    r, base = cli.verify_json(store)
    got = findings_for(base, reject) if base else None
    unverified = {"level": "WARN", "message": f"ski@v1 unverified: {c['reason']}"}
    if name == "cas-root":
        # a blob a record cites directly is checked by verify itself: ERR at both grades
        pref = c["verify_base_error_prefix"]
        rep.line(base is not None and base["ok"] is False and r.returncode != 0
                 and any(f["level"] == "ERR" and f["message"].startswith(pref) for f in got)
                 and unverified in got,
                 "verify (base): ok=false, ERR on the citing record + `ski@v1 unverified`",
                 f"rc={r.returncode} findings={got}")
    else:
        # a thunk only the evaluator reaches: base grade reports 'unverified' (WARN,
        # exit 0) — the named limitation; settlement grade makes it an ERR below.
        rep.line(base is not None and unverified in got and base["ok"] is True and r.returncode == 0
                 and not any(f["level"] == "ERR" for f in got),
                 "verify (base): WARN `ski@v1 unverified` on the citing record, exit 0 (limitation, as frozen)",
                 f"rc={r.returncode} findings={got}")
    r, settle = cli.verify_json(store, settlement=trust)
    got = findings_for(settle, reject) if settle else None
    rep.line(settle is not None and settle["ok"] is False and r.returncode != 0
             and {"level": "ERR", "message": f"ski@v1 unverified: {c['reason']}"} in got,
             "verify (settlement): ok=false, ERR `ski@v1 unverified` on the citing record",
             f"rc={r.returncode} findings={got}")


def mutate_root(raw):
    doc = json.loads(raw)
    doc["atp"] = doc["atp"] + 1
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def mutate_nested(raw):
    b = bytearray(raw)
    b[-1] ^= 0x01
    return bytes(b)


# --------------------------------------------------------------------- main --
def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    here = Path(__file__).resolve().parent
    ap.add_argument("--warrant", default=shutil.which("warrant"),
                    help="the installed `warrant` command (default: first on PATH)")
    ap.add_argument("--pack", default=str(here / "pack"))
    ap.add_argument("--manifest", default=str(here / "replay.json"))
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("replay") != "warrant-evidence-replay/0":
        print("REPLAY: REFUSED manifest: not a warrant-evidence-replay/0 document")
        return EXIT_REFUSED
    rep = Report()
    scratch = Path(tempfile.mkdtemp(prefix="warrant-replay-"))
    try:
        if not args.warrant:
            raise Refused("environment", "no `warrant` command given or on PATH")
        pack = Path(args.pack).resolve()
        info = preflight(args.warrant, manifest)
        n = check_inputs(pack, manifest)
        print(f"artifact: warrant-verify {info['version']} at {info['prefix']}")
        print(f"          warrant.py sha256={info['warrant_py_sha256'][:16]}…  "
              f"{manifest['evaluator']['tag']} evaluator sha256={info['evaluator_sha256'][:16]}… (pinned)")
        if info["scrubbed"]:
            print(f"          scrubbed from the environment: {', '.join(info['scrubbed'])}")
        print(f"inputs:   {n} files hash to their frozen digests; nothing else present")
        print(f"cwd:      {os.getcwd()}")
        cli = CLI(args.warrant, os.getcwd())

        print("\nrecords")
        replay_records(cli, pack, manifest, rep)

        print("\ncontrols (fresh copies; the frozen pack is not modified)")
        control_verdict_fail(cli, pack, scratch, manifest, rep)
        control_evaluator(cli, pack, scratch, manifest, rep, "evaluator-absent",
                          scratch / "no-such-sigma-dir")
        boom = scratch / "broken-sigma"
        boom.mkdir()
        (boom / "sigma_glyph.py").write_text('raise RuntimeError("import-boom")\n')
        control_evaluator(cli, pack, scratch, manifest, rep, "evaluator-broken", boom)
        control_cas(cli, pack, scratch, manifest, rep, "cas-root", mutate_root)
        control_cas(cli, pack, scratch, manifest, rep, "cas-nested", mutate_nested)
    except Refused as ex:
        print(f"\nREPLAY: REFUSED {ex.kind}: {ex.detail}")
        return EXIT_REFUSED
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    n_rec = len(manifest["records"])
    n_ctl = len(manifest["controls"])
    if rep.fails:
        print(f"\nREPLAY: FAIL — {len(rep.fails)} assertion(s) did not match the frozen vector:")
        for f in rep.fails:
            print(f"  - {f}")
        return EXIT_FAIL
    print(f"\nREPLAY: {n_rec} record vectors reproduced; {n_ctl} controls refused as frozen. "
          f"Per-record results only — this line is a count, not a verdict about the pack.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
