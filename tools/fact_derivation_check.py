#!/usr/bin/env python3
"""Check a `warrant.fact-derivation@v0` profile: are a WPL check's facts
DERIVED from cited evidence, or merely ASSERTED?

A compiled WPL check bakes every `fact` into the term as a constant. The core
format proves the term re-executes; nothing says where the constants came
from (docs/authoring-checks.md §8: "nothing about the facts is proven"). This
profile is an additive blob, cited in a record's `evidence`, that names for
each fact the evidence blob it was read from and the closed extractor that
read it. A profile-aware tool re-derives the value and reports, PER FACT:

    DERIVED     re-derived value == the value baked into the term
    DIVERGED    re-derived value != the baked value  (the term contradicts its
                own cited evidence; the only verdict that fails the run)
    ASSERTED    the fact has no derivation in the profile
    UNRESOLVED  the evidence blob (or program) is absent or does not hash to
                its address, or the pointer names nothing
    UNRUN       a `cmd` derivation that was not executed (the default: SPEC
                §14 -- never run a program merely because it arrived)
    MALFORMED   the evidence has the wrong shape for the fact's type

There is no document-level badge. The summary counts facts and says
`semantic-credit=none`: DERIVED binds a constant to bytes and a pinned
extractor, never to the truth of those bytes.

Profile (JCS-canonical, integers only):

    { "profile": "warrant.fact-derivation@v0",
      "policy_source": "<hex64 WPL source blob>",
      "facts": { "<name>": { "from": "<hex64 evidence blob>",
                             "via":  <extractor>,
                             "value": <bool | int | string> } } }

Extractors (closed set, v0):
    {"kind": "json",      "pointer": "/a/b"}    RFC 6901 pointer into a JSON blob
    {"kind": "json-len",  "pointer": "/items"}  length of the array at pointer
    {"kind": "digest-eq", "other": "<hex64>"}   `from` == `other`, no bytes read
    {"kind": "cmd",       "program": "<hex64>", "args": [..]}
        python3 <program> <evidence-path> <args...>; stdout is one JSON literal.
        Executed only with --execute-cmd; otherwise UNRUN. Container trust.

    python3 tools/fact_derivation_check.py --store .warrants --profile <hex64>
    python3 tools/fact_derivation_check.py --selftest

Nothing here touches `warrant verify`, the ski@v1 check blob, WPL syntax or the
SPEC. WRT-004 (reason-binding, on the paper branch) binds a fact to an
evidence *item* `{fact,type,value}`; this profile binds it to a *derivation*.
The two compose: a reason-binding fact-item may be the `from` of nothing, and
a derived fact may also be listed there.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "impl"))
import policy_lang as PL  # noqa: E402

PROFILE = "warrant.fact-derivation@v0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"json", "json-len", "digest-eq", "cmd"}
RUNNER = "python3"
CMD_TIMEOUT = 60
MAX_BLOB = 2 * 1024 * 1024


class Refusal(Exception):
    """The profile itself is not checkable; nothing per fact is reported."""


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def strict_loads(raw: bytes):
    def hook(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f"duplicate key {k!r}")
            out[k] = v
        return out
    return json.loads(raw.decode("utf-8"), object_pairs_hook=hook)


def store_resolver(store: Path):
    """hex64 -> bytes | None, refusing traversal and bytes that do not hash to
    their address (a file wearing a blob's name is not that blob)."""
    blobs = store / "blobs"

    def resolve(h):
        if not isinstance(h, str) or not HEX64.match(h):
            return None
        p = blobs / h
        if not p.is_file() or p.is_symlink() or p.stat().st_size > MAX_BLOB:
            return None
        data = p.read_bytes()
        return data if sha(data) == h else None
    return resolve


def pointer_get(doc, pointer: str):
    """RFC 6901. Returns (found, value)."""
    if pointer == "":
        return True, doc
    if not pointer.startswith("/"):
        raise Refusal(f"POINTER_INVALID:{pointer!r}")
    cur = doc
    for raw in pointer.split("/")[1:]:
        tok = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, dict):
            if tok not in cur:
                return False, None
            cur = cur[tok]
        elif isinstance(cur, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", tok) or int(tok) >= len(cur):
                return False, None
            cur = cur[int(tok)]
        else:
            return False, None
    return True, cur


def literal_ok(value, ftype: str) -> bool:
    if ftype == "bool":
        return isinstance(value, bool)
    if ftype == "int":
        return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 2 ** 32
    if ftype == "string":
        return isinstance(value, str) and len(value.encode("utf-8")) <= PL.MAX_STRING_BYTES
    return False


def derive(entry, ftype, resolve, execute):
    """One fact: returns (verdict, detail). Raises Refusal for a profile shape
    that cannot be checked at all."""
    via = entry["via"]
    kind = via.get("kind")
    if kind == "digest-eq":
        other = via.get("other")
        if set(via) != {"kind", "other"} or not (isinstance(other, str) and HEX64.match(other)):
            raise Refusal("VIA_SHAPE:digest-eq")
        if ftype != "bool":
            raise Refusal("VIA_TYPE:digest-eq needs a bool fact")
        return "value", entry["from"] == other
    data = resolve(entry["from"])
    if data is None:
        return "UNRESOLVED", "evidence blob absent or not hashing to its address"
    if kind in ("json", "json-len"):
        pointer = via.get("pointer")
        if set(via) != {"kind", "pointer"} or not isinstance(pointer, str):
            raise Refusal(f"VIA_SHAPE:{kind}")
        try:
            doc = strict_loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            return "MALFORMED", f"evidence is not strict JSON: {exc}"
        found, value = pointer_get(doc, pointer)
        if not found:
            return "UNRESOLVED", f"pointer {pointer} names nothing"
        if kind == "json-len":
            if not isinstance(value, list):
                return "MALFORMED", f"pointer {pointer} is not an array"
            value = len(value)
            if ftype != "int":
                raise Refusal("VIA_TYPE:json-len needs an int fact")
        if not literal_ok(value, ftype):
            return "MALFORMED", f"value at {pointer} is not a WPL {ftype} literal"
        return "value", value
    if kind == "cmd":
        program, args = via.get("program"), via.get("args")
        if (set(via) != {"kind", "program", "args"} or not (isinstance(program, str) and HEX64.match(program))
                or not isinstance(args, list) or not all(isinstance(a, str) for a in args)):
            raise Refusal("VIA_SHAPE:cmd")
        if not execute:
            return "UNRUN", "cmd derivation not executed (pass --execute-cmd to run it under container trust)"
        code = resolve(program)
        if code is None:
            return "UNRESOLVED", "program blob absent or not hashing to its address"
        with tempfile.TemporaryDirectory() as td:
            prog = Path(td) / "extract.py"; prog.write_bytes(code)
            ev = Path(td) / "evidence"; ev.write_bytes(data)
            try:
                p = subprocess.run([RUNNER, str(prog), str(ev), *args], capture_output=True,
                                   timeout=CMD_TIMEOUT, cwd=td)
            except (OSError, subprocess.SubprocessError) as exc:
                return "UNRESOLVED", f"program did not run: {type(exc).__name__}"
        if p.returncode != 0:
            return "DIVERGED", f"program exited {p.returncode}"
        try:
            value = json.loads(p.stdout.decode("utf-8").strip())
        except (ValueError, UnicodeDecodeError):
            return "MALFORMED", "program output is not one JSON literal"
        if not literal_ok(value, ftype):
            return "MALFORMED", f"program output is not a WPL {ftype} literal"
        return "value", value
    raise Refusal(f"VIA_UNKNOWN:{kind!r}")


def check_profile(profile, resolve, execute=False):
    """Returns (facts: list of (name, verdict, detail), summary dict).
    Raises Refusal when the profile is not checkable."""
    if not isinstance(profile, dict) or profile.get("profile") != PROFILE:
        raise Refusal("PROFILE_UNKNOWN")
    if set(profile) != {"profile", "policy_source", "facts"}:
        raise Refusal("PROFILE_SHAPE")
    src_hex = profile["policy_source"]
    src = resolve(src_hex) if isinstance(src_hex, str) else None
    if src is None:
        raise Refusal("POLICY_SOURCE_UNRESOLVED")
    try:
        prog = PL.parse(src.decode("utf-8"))
    except (UnicodeDecodeError, PL.PolicyError) as exc:
        raise Refusal(f"POLICY_SOURCE_INVALID:{exc}") from exc
    entries = profile["facts"]
    if not isinstance(entries, dict):
        raise Refusal("FACTS_SHAPE")
    for name, entry in entries.items():
        if name not in prog.facts:
            raise Refusal(f"FACT_NOT_IN_SOURCE:{name}")
        if (not isinstance(entry, dict) or set(entry) != {"from", "via", "value"}
                or not (isinstance(entry["from"], str) and HEX64.match(entry["from"]))
                or not isinstance(entry["via"], dict)):
            raise Refusal(f"FACT_ENTRY_SHAPE:{name}")
        f = prog.facts[name]
        if f.type not in ("bool", "int", "string"):
            raise Refusal(f"FACT_TYPE_UNSUPPORTED:{name}:{f.type}")
        if entry["value"] != f.value or type(entry["value"]) is not type(f.value):
            # The profile may not claim a derivation for a value the term does
            # not bake in; that would bind the wrong constant.
            raise Refusal(f"PROFILE_VALUE_NOT_IN_TERM:{name}")
    results = []
    for name, f in prog.facts.items():
        if name not in entries:
            results.append((name, "ASSERTED", "no derivation in the profile"))
            continue
        kind, payload = derive(entries[name], f.type, resolve, execute)
        if kind != "value":
            results.append((name, kind, payload))
        elif payload == f.value and type(payload) is type(f.value):
            results.append((name, "DERIVED", f"{entries[name]['via']['kind']} -> {PL._lit(payload)}"))
        else:
            results.append((name, "DIVERGED",
                            f"{entries[name]['via']['kind']} -> {PL._lit(payload)}, term bakes {PL._lit(f.value)}"))
    summary = {v: sum(1 for _, r, _ in results if r == v)
               for v in ("DERIVED", "DIVERGED", "ASSERTED", "UNRESOLVED", "UNRUN", "MALFORMED")}
    return results, summary


def report(profile_hex, results, summary) -> int:
    for name, verdict, detail in results:
        print(f"{verdict:10s} {name}  {detail}")
    counts = " ".join(f"{k.lower()}={v}" for k, v in summary.items())
    print(f"FACT-DERIVATION {profile_hex[:12]}: facts={len(results)} {counts} semantic-credit=none")
    return 1 if summary["DIVERGED"] or summary["MALFORMED"] else 0


# --- selftest -----------------------------------------------------------------

def selftest() -> int:
    controls = []
    store = {}

    def put(b):
        h = sha(b); store[h] = b; return h

    def resolve(h):
        return store.get(h)

    src = put(b'fact files_changed: int = 2\nfact lines_added: int = 267\n'
              b'fact touches_ci: bool = true\nfact anchors_equal: bool = true\n'
              b'fact proposed_by_agent: bool = true\nfact label: string = "docs"\n'
              b'check files_changed <= 30 && lines_added <= 600 && !touches_ci\n'
              b'      && anchors_equal && (!proposed_by_agent || lines_added <= 300)\n'
              b'      && label == "docs"\n')
    evidence = put(b'{"lines_added": 267, "paths": [".github/x.yml", "README.md"], "label": "docs", "meta": {"a~b": {"c/d": true}}}')
    program = put(b'import json, sys\nd = json.load(open(sys.argv[1]))\n'
                  b'print(json.dumps(any(p.startswith(sys.argv[2]) for p in d["paths"])))\n')
    digest_a = "a" * 64
    profile = {"profile": PROFILE, "policy_source": src, "facts": {
        "files_changed": {"from": evidence, "via": {"kind": "json-len", "pointer": "/paths"}, "value": 2},
        "lines_added": {"from": evidence, "via": {"kind": "json", "pointer": "/lines_added"}, "value": 267},
        "touches_ci": {"from": evidence, "via": {"kind": "cmd", "program": program, "args": [".github/"]}, "value": True},
        "anchors_equal": {"from": digest_a, "via": {"kind": "digest-eq", "other": digest_a}, "value": True},
        "label": {"from": evidence, "via": {"kind": "json", "pointer": "/label"}, "value": "docs"},
    }}

    def verdicts(p, execute=False, res=resolve):
        results, _ = check_profile(p, res, execute)
        return {n: v for n, v, _ in results}

    got = verdicts(profile)
    assert got == {"files_changed": "DERIVED", "lines_added": "DERIVED", "touches_ci": "UNRUN",
                   "anchors_equal": "DERIVED", "label": "DERIVED", "proposed_by_agent": "ASSERTED"}, got
    controls.append("positive: json, json-len, digest-eq derive; cmd unrun by default; unlisted fact asserted")
    got = verdicts(profile, execute=True)
    assert got["touches_ci"] == "DERIVED", got
    controls.append("cmd derives when executed")

    import copy

    def mutant(fn):
        p = copy.deepcopy(profile); fn(p); return p

    # Evidence contradicts the term: the only failing verdict.
    tampered = put(b'{"lines_added": 268, "paths": [".github/x.yml", "README.md"], "label": "docs"}')
    got = verdicts(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", tampered)))
    assert got["lines_added"] == "DIVERGED", got
    controls.append("diverged: evidence says 268, term bakes 267")
    got = verdicts(mutant(lambda p: p["facts"]["anchors_equal"].__setitem__("from", "b" * 64)))
    assert got["anchors_equal"] == "DIVERGED", got
    controls.append("diverged: digest-eq over unequal digests")
    bad_prog = put(b'print("false")\n')
    got = verdicts(mutant(lambda p: p["facts"]["touches_ci"]["via"].__setitem__("program", bad_prog)), execute=True)
    assert got["touches_ci"] == "DIVERGED", got
    controls.append("diverged: cmd output contradicts the term")

    # Shapes that cannot bind.
    def refuses(name, fn, expected):
        try:
            check_profile(mutant(fn), resolve)
        except Refusal as exc:
            assert expected in str(exc), (name, exc)
            controls.append(name); return
        raise AssertionError(f"{name}: survived")
    refuses("profile value not baked into the term", lambda p: p["facts"]["lines_added"].__setitem__("value", 266), "PROFILE_VALUE_NOT_IN_TERM")
    refuses("bool/int confusion is not equality", lambda p: p["facts"]["touches_ci"].__setitem__("value", 1), "PROFILE_VALUE_NOT_IN_TERM")
    refuses("fact not in source", lambda p: p["facts"].__setitem__("ghost", p["facts"]["label"]), "FACT_NOT_IN_SOURCE")
    refuses("unknown extractor", lambda p: p["facts"]["label"]["via"].__setitem__("kind", "regex"), "VIA_UNKNOWN")
    refuses("extra profile field", lambda p: p.__setitem__("bound", True), "PROFILE_SHAPE")
    refuses("json-len on a string fact", lambda p: p["facts"]["label"].__setitem__("via", {"kind": "json-len", "pointer": "/paths"}), "VIA_TYPE")
    refuses("pointer without leading slash", lambda p: p["facts"]["label"]["via"].__setitem__("pointer", "label"), "POINTER_INVALID")
    try:
        check_profile(dict(profile, policy_source=put(b"not wpl")), resolve)
    except Refusal as exc:
        assert "POLICY_SOURCE_INVALID" in str(exc); controls.append("policy source not WPL")
    else:
        raise AssertionError("policy source survived")

    # Unresolved and malformed, each named.
    got = verdicts(mutant(lambda p: p["facts"]["label"]["via"].__setitem__("pointer", "/missing")))
    assert got["label"] == "UNRESOLVED", got; controls.append("unresolved: pointer names nothing")
    got = verdicts(mutant(lambda p: p["facts"]["label"].__setitem__("from", "c" * 64)))
    assert got["label"] == "UNRESOLVED", got; controls.append("unresolved: evidence blob absent")
    got = verdicts(mutant(lambda p: p["facts"]["touches_ci"]["via"].__setitem__("program", "d" * 64)), execute=True)
    assert got["touches_ci"] == "UNRESOLVED", got; controls.append("unresolved: program blob absent")
    floaty = put(b'{"lines_added": 267.0, "paths": [], "label": "docs"}')
    got = verdicts(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", floaty)))
    assert got["lines_added"] == "MALFORMED", got; controls.append("malformed: float where an int fact is baked")
    longs = put(b'{"lines_added": 267, "paths": [], "label": "' + b"x" * 40 + b'"}')
    got = verdicts(mutant(lambda p: p["facts"]["label"].__setitem__("from", longs)))
    assert got["label"] == "MALFORMED", got; controls.append("malformed: string over 32 bytes")
    dup = put(b'{"lines_added": 1, "lines_added": 267, "paths": [], "label": "docs"}')
    got = verdicts(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", dup)))
    assert got["lines_added"] == "MALFORMED", got; controls.append("malformed: duplicate JSON key in evidence")
    # A pointer with RFC 6901 escapes reaches its value.
    esc = mutant(lambda p: p["facts"].__setitem__("touches_ci", {"from": evidence, "via": {"kind": "json", "pointer": "/meta/a~0b/c~1d"}, "value": True}))
    assert verdicts(esc)["touches_ci"] == "DERIVED"; controls.append("pointer escapes ~0 ~1 resolve")

    # The store resolver refuses bytes wearing a blob's name.
    with tempfile.TemporaryDirectory() as td:
        blobs = Path(td) / "blobs"; blobs.mkdir()
        (blobs / ("e" * 64)).write_bytes(b"not those bytes")
        assert store_resolver(Path(td))("e" * 64) is None
        h = sha(b"real"); (blobs / h).write_bytes(b"real")
        assert store_resolver(Path(td))(h) == b"real"
        assert store_resolver(Path(td))("../records") is None
    controls.append("store resolver: address must hash; no traversal")

    # Exit status: DIVERGED fails, everything else reports.
    import io, contextlib
    res, summ = check_profile(profile, resolve)
    with contextlib.redirect_stdout(io.StringIO()):
        assert report("x" * 64, res, summ) == 0
    res, summ = check_profile(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", tampered)), resolve)
    with contextlib.redirect_stdout(io.StringIO()):
        assert report("x" * 64, res, summ) == 1
    controls.append("exit 1 only on DIVERGED/MALFORMED")

    print(f"FACT-DERIVATION-SELFTEST: ALL PASS ({len(controls)} controls)")
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", help="a .warrants store (blobs/ under it)")
    ap.add_argument("--profile", help="hex64 of the profile blob in that store")
    ap.add_argument("--execute-cmd", action="store_true",
                    help="run `cmd` derivations (container trust; never the default)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.selftest:
            return selftest()
        if not (a.store and a.profile):
            ap.error("--store and --profile are required unless --selftest")
        resolve = store_resolver(Path(a.store))
        raw = resolve(a.profile)
        if raw is None:
            raise Refusal("PROFILE_UNRESOLVED")
        try:
            profile = strict_loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise Refusal(f"PROFILE_JSON:{exc}") from exc
        results, summary = check_profile(profile, resolve, a.execute_cmd)
        return report(a.profile, results, summary)
    except (Refusal, AssertionError) as exc:
        print(f"REFUSED  {exc}")
        return 1
    except Exception as exc:  # the last membrane, never the schema
        print(f"REFUSED  INTERNAL_UNTYPED:{type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
