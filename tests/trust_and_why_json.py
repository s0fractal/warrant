#!/usr/bin/env python3
"""`warrant trust` and `warrant why --json`: the path to green, and a chain an agent can read.

WHY
---
The README quickstart ended at `0 errors, 3 warnings` ("binding unverified (no
keyring)") with no next step but hand-writing a trust config: the act that
answers SA-2 -- which key may speak for which actor -- had no tool. And `why`
answered only in prose, so an agent asking "did this decision's chain verify,
and on what" had to parse text.

Following the quickstart all the way to settlement grade also showed that its
own accept was a re-litigation that cited nothing new: the second check run
filed no transcript, so it carried no new evidence and no new outcome
fingerprint (SA-1's territory). The quickstart now files the transcripts, and
the case without them is pinned here, so the warning stays visible rather than
fixed by deleting the step that produced it.

WHAT IS ASSERTED, FOR PYTHON AND RUST ALIKE
  1. The quickstart (with transcripts) at base grade: 0 errors, 3 binding
     warnings. After `trust add` + `trust root`, at settlement grade:
     0 errors, 0 warnings.
  2. The same flow without transcripts, at settlement grade: exactly one
     warning, "re-litigation cites nothing new", on the accept.
  3. `why --json` and `why` agree on the exit status, on a clean chain, a chain
     with a missing prior, and a chain with a tampered record; `ok` equals
     (exit status == 0); every walked record appears once per visit.
  4. `trust` writes only what it is told: idempotent, refuses a weak key, a
     non-hex root, and an existing config that does not validate -- leaving
     that file byte-for-byte unchanged -- and writes nothing outside the
     working directory (`../`, absolute, symlinked out) or to a non-`.json`.
  5. The README's "Try it" section, executed VERBATIM (its bash blocks, minus
     the install line) with each implementation as `warrant` on PATH, ends at
     `0 errors, 0 warnings`. A promise in the README is checked by running it.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RS = ROOT / "impl-rs" / "target" / "release" / "warrant-rs"
IMPLS = {"py": [sys.executable, str(ROOT / "impl" / "warrant.py")]}
ENV = {k: v for k, v in os.environ.items() if k not in ("SIGMA_GLYPH", "WARRANT_SIGMA_DIFFERENTIAL")}

ok = True


def check(label, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("OK   " if cond else "FAIL "), label, "" if cond else f"-> {detail}")


def counts(text):
    import re
    m = re.search(r"verify: (\d+) records, (\d+) errors, (\d+) warnings", text)
    return tuple(map(int, m.groups())) if m else None


def quickstart(cli, d, transcripts=True):
    def w(*a):
        r = subprocess.run(cli + list(a), cwd=d, capture_output=True, text=True, env=ENV)
        return r
    w("init")
    w("keygen", "--out", "me.key")
    Path(d, "diff.patch").write_text("demo diff\n")
    Path(d, "policy.txt").write_text("clause 1: no coverage drop\n")
    pol = w("policy", "add", "policy.txt").stdout.strip()
    p = w("propose", "--subject", "diff.patch", "--under", pol, "--reason", "needed",
          "--actor", "me@host", "--key", "me.key", "--ts", "100").stdout.strip()
    Path(d, "check.sh").write_text("#!/bin/sh\necho FAIL; exit 1\n")
    Path(d, "run1.txt").write_text("FAIL\n")
    t1 = ["--transcript", "run1.txt"] if transcripts else []
    r = w("reject", p, "--check", "check.sh", "--verdict", "fail", *t1,
          "--reason", "coverage drop", "--actor", "me@host", "--key", "me.key", "--ts", "101").stdout.strip()
    Path(d, "check.sh").write_text("#!/bin/sh\necho ok; exit 0\n")
    Path(d, "run2.txt").write_text("ok\n")
    t2 = ["--transcript", "run2.txt"] if transcripts else []
    a = w("accept", r, "--check", "check.sh", "--verdict", "pass", *t2,
          "--actor", "me@host", "--key", "me.key", "--ts", "102").stdout.strip()
    return w, p, r, a


def readme_try_it():
    """The bash blocks of README.md's "## Try it" section, install lines removed."""
    import re
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    sec = text.split("\n## Try it\n", 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(r"```bash\n(.*?)```", sec, re.S)
    lines = [l for b in blocks for l in b.splitlines() if not l.startswith("pipx install")]
    return "\n".join(lines) + "\n"


def main():
    if RS.is_file():
        IMPLS["rs"] = [str(RS)]
    else:
        print(f"SKIP  rust half: warrant-rs not built ({RS})")
    for name, cli in IMPLS.items():
        tmp = tempfile.mkdtemp(prefix=f"trustwhy-{name}-")
        try:
            d = Path(tmp, "q")
            d.mkdir()
            w, p, r, a = quickstart(cli, d)
            base = counts(w("verify").stdout)
            check(f"{name}: quickstart at base grade: 0 errors, 3 binding warnings",
                  base == (3, 0, 3), base)
            w("trust", "add", "--actor", "me@host", "--key", "me.key")
            w("trust", "root", p)
            v = w("verify", "--settlement", "--trust-config", "trust.json")
            check(f"{name}: after trust add + trust root, settlement grade is green",
                  counts(v.stdout) == (3, 0, 0) and v.returncode == 0, v.stdout)

            d2 = Path(tmp, "nt")
            d2.mkdir()
            w2, p2, _, a2 = quickstart(cli, d2, transcripts=False)
            w2("trust", "add", "--actor", "me@host", "--key", "me.key")
            w2("trust", "root", p2)
            v2 = w2("verify", "--settlement", "--trust-config", "trust.json").stdout
            warns = [l for l in v2.splitlines() if l.startswith("WARN")]
            check(f"{name}: without transcripts the accept re-litigates on nothing new",
                  len(warns) == 1 and a2[:12] in warns[0] and "re-litigation cites nothing new" in warns[0],
                  warns)

            # why and why --json: same walk, same verdict, three chains.
            def both(store_dir, wid):
                t = subprocess.run(cli + ["--store", str(store_dir), "why", wid], capture_output=True, text=True, env=ENV)
                j = subprocess.run(cli + ["--store", str(store_dir), "why", wid, "--json"], capture_output=True, text=True, env=ENV)
                rep = json.loads(j.stdout)
                return t, j, rep
            store = d / ".warrants"
            t, j, rep = both(store, a)
            walked = [n["warrant_id"] for n in rep["nodes"]]
            check(f"{name}: why --json on a clean chain: ok, 3 verified nodes in walk order",
                  t.returncode == j.returncode == 0 and rep["ok"] is True
                  and walked == [a, r, p] and all(n["status"] == "verified" for n in rep["nodes"]),
                  (t.returncode, j.returncode, walked))
            (store / "records" / f"{p}.json").unlink()
            t, j, rep = both(store, a)
            check(f"{name}: why --json with a missing prior: same failing exit, status missing",
                  t.returncode == j.returncode == 1 and rep["ok"] is False and rep["missing"] == 1
                  and rep["nodes"][-1] == {"warrant_id": p, "depth": 2, "status": "missing"},
                  (t.returncode, j.returncode, rep.get("missing")))
            rec = store / "records" / f"{r}.json"
            env = json.loads(rec.read_text())
            env["body"]["ts"] = 999
            rec.write_text(json.dumps(env))
            t, j, rep = both(store, a)
            check(f"{name}: why --json with a tampered record: verify_failed, failed=1, exit 1",
                  t.returncode == j.returncode == 1 and rep["failed"] == 1
                  and rep["nodes"][1]["status"] == "verify_failed",
                  (t.returncode, j.returncode, rep.get("failed")))

            # trust writes only what it is told.
            cfg = d / "trust.json"
            before = cfg.read_bytes()
            again = w("trust", "add", "--actor", "me@host", "--key", "me.key")
            check(f"{name}: trust add is idempotent", "already in" in again.stdout and cfg.read_bytes() == before,
                  again.stdout)
            weak = w("trust", "add", "--actor", "x@y", "--pubkey", "01" + "00" * 31)
            bad_root = w("trust", "root", "not-a-warrant-id")
            check(f"{name}: trust refuses a weak key and a non-hex root, file unchanged",
                  weak.returncode == 1 and bad_root.returncode == 1 and cfg.read_bytes() == before,
                  (weak.returncode, bad_root.returncode))
            # Nothing is written outside the working directory, nor to a non-.json.
            outside = Path(tmp, "outside.json")
            (d / "sub").mkdir()
            (d / "link.json").symlink_to(outside)
            refusals = [w("trust", "root", p, "--config", c).returncode
                        for c in ("../outside.json", str(outside), "trust.txt", "link.json", "sub")]
            check(f"{name}: trust refuses a config outside the working directory or not .json",
                  refusals == [1] * 5 and not outside.exists() and not (d / "trust.txt").exists(),
                  refusals)
            inner = w("trust", "root", p, "--config", "sub/t.json")
            check(f"{name}: trust writes a .json in a subdirectory of the working directory",
                  inner.returncode == 0 and (d / "sub" / "t.json").is_file(), inner.returncode)
            junk = d / "junk.json"
            junk.write_text('{"actors": null}')
            j0 = junk.read_bytes()
            refused = w("trust", "root", p, "--config", "junk.json")
            check(f"{name}: an invalid existing config is refused, never rewritten",
                  refused.returncode == 1 and junk.read_bytes() == j0, refused.returncode)
            # 5. The README, run as written.
            rd = Path(tmp, "readme")
            (rd / "bin").mkdir(parents=True)
            shim = rd / "bin" / "warrant"
            shim.write_text("#!/bin/sh\nexec " + " ".join(f"'{c}'" for c in cli) + ' "$@"\n')
            shim.chmod(0o755)
            env = dict(ENV, PATH=f"{rd / 'bin'}{os.pathsep}{ENV.get('PATH', '')}")
            run = subprocess.run(["bash", "-c", readme_try_it()], cwd=rd, capture_output=True,
                                 text=True, env=env)
            last = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
            check(f"{name}: README 'Try it', run verbatim, ends green at settlement grade",
                  run.returncode == 0 and last == "verify: 3 records, 0 errors, 0 warnings",
                  (run.returncode, last, run.stderr[-300:]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nTRUST-AND-WHY-JSON: {'ALL PASS' if ok else 'FAILURES PRESENT'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
