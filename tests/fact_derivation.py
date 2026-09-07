#!/usr/bin/env python3
"""Fail-closed harness for tools/fact_derivation_check.py (WRT-008 rev 2).

  A. the tool's own selftest passes;
  B. five mutants of the TOOL must make that selftest fail -- a harness that
     cannot go red is the defect one level up;
  C. end to end on a real .warrants layout: a WPL policy compiled with
     --store, its check cited by a synthetic (unsigned) record, evidence and
     profile blobs put beside it; the CLI reports per fact, exit 0 on a clean
     profile, 1 once the evidence contradicts the term; a blob wearing the
     wrong name is UNRESOLVED; the record path refuses uncited blobs;
  D. the five counterexamples of the PR #60 review, with exact verdicts and
     exit codes: unknown extractor with missing evidence, `~2` pointer, NaN,
     newline addresses, and a profile whose source is not the cited check.
Every relation is asserted; any deviation exits 1.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "fact_derivation_check.py"
PY = sys.executable
ok = []


def chk(cond, what, detail=""):
    ok.append(bool(cond))
    print(("ok   " if cond else "FAIL ") + what + (f"  [{detail}]" if detail and not cond else ""))


def run(args, cwd=ROOT):
    return subprocess.run([PY, *args], cwd=cwd, capture_output=True, text=True)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":")).encode()


def section_a():
    r = run([str(TOOL), "--selftest"])
    chk(r.returncode == 0 and "FACT-DERIVATION-SELFTEST: ALL PASS" in r.stdout, "A. tool selftest passes", r.stdout[-200:] + r.stderr[-200:])


def section_b():
    src = TOOL.read_text()
    mutants = {
        "diverged never reported": ('results.append((name, "DIVERGED",', 'results.append((name, "DERIVED",'),
        "cmd executed by default": ("if not execute:\n        return \"UNRUN\"", "if False:\n        return \"UNRUN\""),
        "profile value unchecked": ('raise Refusal(f"PROFILE_VALUE_NOT_IN_TERM:{name}")', "pass"),
        "check binding removed": ('    if compiled.doc["term"] != doc["term"]:\n        raise Refusal("CHECK_TERM_MISMATCH', '    if False:\n        raise Refusal("CHECK_TERM_MISMATCH'),
        "pointer escapes unchecked": ("if POINTER_TOKEN.fullmatch(raw) is None:", "if False:"),
    }
    for name, (old, new) in mutants.items():
        assert src.count(old) == 1, (name, src.count(old))
        with tempfile.TemporaryDirectory() as td:
            tools = Path(td) / "tools"; tools.mkdir()
            (tools / "fact_derivation_check.py").write_text(src.replace(old, new))
            os.symlink(ROOT / "impl", Path(td) / "impl")
            r = run([str(tools / "fact_derivation_check.py"), "--selftest"], cwd=td)
            chk(r.returncode != 0, f"B. mutant '{name}' is caught by the selftest", r.stdout[-200:])


class Store:
    def __init__(self, td):
        self.root = Path(td) / ".warrants"; (self.root / "blobs").mkdir(parents=True); (self.root / "records").mkdir()

    def put(self, b):
        h = sha(b); (self.root / "blobs" / h).write_bytes(b); return h

    def record(self, body):
        wid = sha(canon(body)); (self.root / "records" / f"{wid}.json").write_bytes(canon({"body": body, "sigs": []})); return wid


def compile_into(store, text):
    policy = store.root.parent / "policy.wpl"; policy.write_text(text)
    r = run([str(ROOT / "impl" / "policy_lang.py"), "compile", str(policy), "--store", str(store.root), "--json"])
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout), store.put(policy.read_bytes())


def section_c():
    with tempfile.TemporaryDirectory() as td:
        store = Store(td)
        compiled, src_hex = compile_into(store, "fact files_changed: int = 2\nfact lines_added: int = 267\n"
                                                "fact label: string = \"docs\"\n"
                                                "check files_changed <= 30 && lines_added <= 600 && label == \"docs\"\n")
        chk(compiled["result"] is True and compiled["check"], "C. policy compiles into the store")
        evidence = store.put(b'{"lines_added": 267, "paths": ["a.md", "b.md"], "label": "docs"}')
        profile = {"profile": "warrant.fact-derivation@v0", "check": compiled["check"], "policy_source": src_hex, "facts": {
            "files_changed": {"from": evidence, "via": {"kind": "json-len", "pointer": "/paths"}, "value": 2},
            "lines_added": {"from": evidence, "via": {"kind": "json", "pointer": "/lines_added"}, "value": 267},
            "label": {"from": evidence, "via": {"kind": "json", "pointer": "/label"}, "value": "docs"}}}
        prof_hex = store.put(canon(profile))
        r = run([str(TOOL), "--store", str(store.root), "--profile", prof_hex])
        chk(r.returncode == 0 and r.stdout.count("DERIVED") == 3, "C. clean profile: three DERIVED, exit 0", r.stdout)
        chk(re.search(r"FACT-DERIVATION [0-9a-f]{12}: facts=3 derived=3 diverged=0 .* check=bound record=unverified semantic-credit=none", r.stdout) is not None,
            "C. summary names check=bound and record=unverified without --record", r.stdout)
        # A record that cites everything.
        body = {"warrant": "0.2", "decision": "accept", "subject": {"hash": "1" * 64}, "under": ["2" * 64],
                "because": [{"kind": "check", "runtime": "ski@v1", "check": compiled["check"], "verdict": "pass"}],
                "evidence": [src_hex, evidence, prof_hex], "actor": {"id": "t@test"}, "prior": [], "ts": 1}
        wid = store.record(body)
        r = run([str(TOOL), "--store", str(store.root), "--profile", prof_hex, "--record", wid])
        chk(r.returncode == 0 and "record=cited (signatures not checked here" in r.stdout, "C. --record: cited record passes and says signatures are not checked", r.stdout)
        # A record that does not cite the evidence blob.
        wid2 = store.record(dict(body, evidence=[src_hex, prof_hex]))
        r = run([str(TOOL), "--store", str(store.root), "--profile", prof_hex, "--record", wid2])
        chk(r.returncode == 1 and "REFUSED  RECORD_EVIDENCE_NOT_CITED:files_changed" in r.stdout, "C. --record: uncited evidence is a typed refusal", r.stdout)
        # Evidence that contradicts the term -> DIVERGED, exit 1.
        tampered = store.put(b'{"lines_added": 601, "paths": ["a.md", "b.md"], "label": "docs"}')
        bad = json.loads(json.dumps(profile)); bad["facts"]["lines_added"]["from"] = tampered
        r = run([str(TOOL), "--store", str(store.root), "--profile", store.put(canon(bad))])
        chk(r.returncode == 1 and "DIVERGED   lines_added" in r.stdout, "C. contradicting evidence -> DIVERGED, exit 1", r.stdout)
        # Bytes wearing the evidence blob's name are not that blob.
        (store.root / "blobs" / evidence).write_bytes(b'{"lines_added": 267, "paths": ["a.md", "b.md"], "label": "docs", "x": 1}')
        r = run([str(TOOL), "--store", str(store.root), "--profile", prof_hex])
        chk(r.returncode == 0 and r.stdout.count("UNRESOLVED") == 3, "C. blob not hashing to its address is UNRESOLVED, never read", r.stdout)
        r = run([str(TOOL), "--store", str(store.root), "--profile", "f" * 64])
        chk(r.returncode == 1 and "REFUSED  PROFILE_UNRESOLVED" in r.stdout, "C. missing profile is a typed refusal", r.stdout)
        r = run([str(TOOL), "--store", str(store.root), "--profile", prof_hex + "\n"])
        chk(r.returncode == 1 and "PROFILE_ADDRESS_INVALID" in r.stdout, "C. profile address with a newline is refused", r.stdout)


def section_d():
    """The PR #60 review's counterexamples, each with its exact verdict."""
    with tempfile.TemporaryDirectory() as td:
        store = Store(td)
        compiled, src_hex = compile_into(store, "fact x: int = 1\ncheck x == 1\n")

        def profile(ev, via, value=1, check=compiled["check"], src=src_hex):
            return store.put(canon({"profile": "warrant.fact-derivation@v0", "check": check, "policy_source": src,
                                    "facts": {"x": {"from": ev, "via": via, "value": value}}}))

        def expect(name, prof_hex, code, needle):
            r = run([str(TOOL), "--store", str(store.root), "--profile", prof_hex])
            chk(r.returncode == code and needle in r.stdout, f"D. {name}: exit {code}, {needle}", r.stdout)

        expect("unknown extractor, evidence missing", profile("f" * 64, {"kind": "not-a-kind"}), 1, "REFUSED  VIA_UNKNOWN")
        expect("unknown extractor, evidence present", profile(store.put(b'{"x":1}'), {"kind": "not-a-kind"}), 1, "REFUSED  VIA_UNKNOWN")
        expect("~2 is invalid RFC 6901 syntax", profile(store.put(b'{"a~2b":1}'), {"kind": "json", "pointer": "/a~2b"}), 1, "REFUSED  POINTER_INVALID")
        expect("NaN is outside JSON", profile(store.put(b'{"items":[NaN]}'), {"kind": "json-len", "pointer": "/items"}), 1, "MALFORMED  x")
        bool_compiled, bool_src = compile_into(store, "fact x: bool = true\ncheck x\n")
        expect("newline addresses are refused", profile("a" * 64 + "\n", {"kind": "digest-eq", "other": "a" * 64 + "\n"}, True, bool_compiled["check"], bool_src), 1, "REFUSED  FACT_ENTRY_SHAPE")
        other, _ = compile_into(store, "fact x: bool = false\ncheck x\n")
        expect("source is not the cited check", profile(store.put(b'{"x":true}'), {"kind": "json", "pointer": "/x"}, True, other["check"], bool_src), 1, "REFUSED  CHECK_TERM_MISMATCH")
        expect("source IS the cited check", profile(store.put(b'{"x":true}'), {"kind": "json", "pointer": "/x"}, True, bool_compiled["check"], bool_src), 0, "DERIVED    x")


def main():
    section_a(); section_b(); section_c(); section_d()
    print(f"\n{sum(ok)}/{len(ok)} checks")
    print("FACT-DERIVATION: ALL PASS" if all(ok) else "FACT-DERIVATION: FAILURES PRESENT")
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
