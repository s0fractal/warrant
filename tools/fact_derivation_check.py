#!/usr/bin/env python3
"""Check a `warrant.fact-derivation@v0` profile: are a WPL check's facts
DERIVED from cited evidence, or merely ASSERTED?

A compiled WPL check bakes every `fact` into the term as a constant. The core
format proves the term re-executes; nothing says where the constants came
from (docs/authoring-checks.md §8: "nothing about the facts is proven"). This
profile is an additive blob, cited in a record's `evidence`, that names the
ski@v1 check it describes, the WPL source that check was compiled from, and
for each fact the evidence blob it was read from and the closed extractor
that read it. A profile-aware tool then

  1. recompiles `policy_source` and REQUIRES the result to be exactly the
     cited check (`term` and `expect`), so "the value baked into the term" is
     a checked relation, not a claim about a source file;
  2. optionally (`--record`) reads a warrant record and REQUIRES the record to
     cite that check as a ski@v1 reason and to list the profile, the source
     and every evidence blob the profile reads; signatures are NOT verified
     here -- that is `warrant verify`'s job;
  3. re-derives each fact and reports, PER FACT:

    DERIVED     re-derived value == the value baked into the term
    DIVERGED    re-derived value != the baked value  (the term contradicts its
                own cited evidence)
    ASSERTED    the fact has no derivation in the profile
    UNRESOLVED  a well-formed derivation whose evidence blob (or program) is
                absent, does not hash to its address, or whose pointer names
                nothing
    UNRUN       a `cmd` derivation that was not executed (the default: SPEC
                §14 -- never run a program merely because it arrived)
    MALFORMED   the evidence has the wrong shape for the fact's type

DIVERGED and MALFORMED fail the run (exit 1); the others are reports. There
is no document-level badge: the summary counts facts and ends with
`semantic-credit=none`. DERIVED binds a constant to bytes and a pinned
extractor, never to the truth of those bytes.

Profile (JCS-canonical, integers only):

    { "profile": "warrant.fact-derivation@v0",
      "check":         "<hex64 ski@v1 check blob>",
      "policy_source": "<hex64 WPL source blob>",
      "facts": { "<name>": { "from": "<hex64 evidence blob>",
                             "via":  <extractor>,
                             "value": <bool | int | string> } } }

Extractors (closed set, v0; the whole shape is validated BEFORE any blob is
read, so a malformed extractor is a refusal whether or not its evidence is
present):
    {"kind": "json",      "pointer": "/a/b"}    RFC 6901 pointer (only ~0 ~1
                                                escapes) into a strict JSON blob
                                                (RFC 8259: no NaN/Infinity, no
                                                duplicate keys, no lone
                                                surrogates)
    {"kind": "json-len",  "pointer": "/items"}  length of the array at pointer
    {"kind": "digest-eq", "other": "<hex64>"}   `from` == `other`; no bytes read
    {"kind": "cmd",       "program": "<hex64>", "args": [..]}
        python3 <program> <evidence-path> <args...>; stdout is one JSON literal.
        Executed only with --execute-cmd, on the HOST python3 with the caller's
        environment, in a temporary directory: this tool provides no container;
        isolation is the caller's responsibility, and the program hash pins the
        program, not the interpreter or its environment.

    python3 tools/fact_derivation_check.py --store .warrants --profile <hex64> [--record <wid>]
    python3 tools/fact_derivation_check.py --selftest

Nothing here touches `warrant verify`, the ski@v1 check blob, WPL syntax or the
SPEC. WRT-004 (reason-binding, on the paper branch) binds a fact to an
evidence *item* `{fact,type,value}`; this profile binds it to a *derivation*.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "impl"))
import policy_lang as PL  # noqa: E402

PROFILE = "warrant.fact-derivation@v0"
HEX64 = re.compile(r"[0-9a-f]{64}")
POINTER_TOKEN = re.compile(r"(?:[^~]|~[01])*")
KINDS = {"json", "json-len", "digest-eq", "cmd"}
RUNNER = "python3"
CMD_TIMEOUT = 60
MAX_BLOB = 2 * 1024 * 1024
FACT_TYPES = ("bool", "int", "string")


class Refusal(Exception):
    """The profile is not checkable; nothing per fact is reported."""


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def is_hex64(v) -> bool:
    return isinstance(v, str) and HEX64.fullmatch(v) is not None


def _refuse_constant(name):
    raise ValueError(f"non-JSON constant {name}")


def strict_loads(raw: bytes):
    """RFC 8259 text, RFC 7493-strict: UTF-8, no duplicate keys, no NaN or
    Infinity, no lone surrogates. Raises ValueError."""
    def hook(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(f"duplicate key {k!r}")
            out[k] = v
        return out
    doc = json.loads(raw.decode("utf-8"), object_pairs_hook=hook, parse_constant=_refuse_constant)

    def surrogate_free(v):
        if isinstance(v, str):
            v.encode("utf-8")           # a lone surrogate raises here
        elif isinstance(v, dict):
            for k, x in v.items():
                k.encode("utf-8"); surrogate_free(x)
        elif isinstance(v, list):
            for x in v:
                surrogate_free(x)
    try:
        surrogate_free(doc)
    except UnicodeEncodeError as exc:
        raise ValueError("lone surrogate") from exc
    return doc


def store_resolver(store: Path):
    """hex64 -> bytes | None, refusing traversal and bytes that do not hash to
    their address (a file wearing a blob's name is not that blob)."""
    blobs = store / "blobs"

    def resolve(h):
        if not is_hex64(h):
            return None
        p = blobs / h
        if not p.is_file() or p.is_symlink() or p.stat().st_size > MAX_BLOB:
            return None
        data = p.read_bytes()
        return data if sha(data) == h else None
    return resolve


def pointer_tokens(pointer: str) -> list:
    """RFC 6901 §3: '' or '/'-prefixed tokens with only ~0 and ~1 escapes.
    Raises Refusal on any other syntax."""
    if not isinstance(pointer, str):
        raise Refusal("POINTER_INVALID:not a string")
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise Refusal(f"POINTER_INVALID:{pointer!r}")
    toks = pointer.split("/")[1:]
    for raw in toks:
        if POINTER_TOKEN.fullmatch(raw) is None:
            raise Refusal(f"POINTER_INVALID:{pointer!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in toks]


def pointer_get(doc, tokens: list):
    cur = doc
    for tok in tokens:
        if isinstance(cur, dict):
            if tok not in cur:
                return False, None
            cur = cur[tok]
        elif isinstance(cur, list):
            if re.fullmatch(r"0|[1-9][0-9]*", tok) is None or int(tok) >= len(cur):
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
        if not isinstance(value, str):
            return False
        try:
            return len(value.encode("utf-8")) <= PL.MAX_STRING_BYTES
        except UnicodeEncodeError:
            return False
    return False


def validate_via(via, ftype: str, name: str) -> list:
    """The whole extractor shape, checked before any I/O. Returns the
    parsed pointer tokens for json kinds (so syntax is refused up front)."""
    if not isinstance(via, dict) or not isinstance(via.get("kind"), str):
        raise Refusal(f"VIA_SHAPE:{name}")
    kind = via["kind"]
    if kind not in KINDS:
        raise Refusal(f"VIA_UNKNOWN:{name}:{kind!r}")
    if kind in ("json", "json-len"):
        if set(via) != {"kind", "pointer"}:
            raise Refusal(f"VIA_SHAPE:{name}:{kind}")
        if kind == "json-len" and ftype != "int":
            raise Refusal(f"VIA_TYPE:{name}:json-len needs an int fact")
        return pointer_tokens(via["pointer"])
    if kind == "digest-eq":
        if set(via) != {"kind", "other"} or not is_hex64(via["other"]):
            raise Refusal(f"VIA_SHAPE:{name}:digest-eq")
        if ftype != "bool":
            raise Refusal(f"VIA_TYPE:{name}:digest-eq needs a bool fact")
        return []
    if set(via) != {"kind", "program", "args"} or not is_hex64(via["program"]) \
            or not isinstance(via["args"], list) or not all(isinstance(a, str) for a in via["args"]):
        raise Refusal(f"VIA_SHAPE:{name}:cmd")
    return []


def derive(entry, ftype, tokens, resolve, execute):
    """One well-formed fact: returns ("value", v) or (verdict, detail)."""
    via = entry["via"]
    kind = via["kind"]
    if kind == "digest-eq":
        return "value", entry["from"] == via["other"]
    data = resolve(entry["from"])
    if data is None:
        return "UNRESOLVED", "evidence blob absent or not hashing to its address"
    if kind in ("json", "json-len"):
        try:
            doc = strict_loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            return "MALFORMED", f"evidence is not strict JSON: {exc}"
        found, value = pointer_get(doc, tokens)
        if not found:
            return "UNRESOLVED", f"pointer {via['pointer']} names nothing"
        if kind == "json-len":
            if not isinstance(value, list):
                return "MALFORMED", f"pointer {via['pointer']} is not an array"
            value = len(value)
        if not literal_ok(value, ftype):
            return "MALFORMED", f"value at {via['pointer']} is not a WPL {ftype} literal"
        return "value", value
    # cmd
    if not execute:
        return "UNRUN", "cmd derivation not executed (pass --execute-cmd to run it on the host python3; no container is provided)"
    code = resolve(via["program"])
    if code is None:
        return "UNRESOLVED", "program blob absent or not hashing to its address"
    with tempfile.TemporaryDirectory() as td:
        prog = Path(td) / "extract.py"; prog.write_bytes(code)
        ev = Path(td) / "evidence"; ev.write_bytes(data)
        try:
            p = subprocess.run([RUNNER, str(prog), str(ev), *via["args"]], capture_output=True,
                               timeout=CMD_TIMEOUT, cwd=td)
        except (OSError, subprocess.SubprocessError) as exc:
            return "UNRESOLVED", f"program did not run: {type(exc).__name__}"
    if p.returncode != 0:
        return "DIVERGED", f"program exited {p.returncode}"
    try:
        value = strict_loads(p.stdout.strip())
    except (ValueError, UnicodeDecodeError):
        return "MALFORMED", "program output is not one strict JSON literal"
    if not literal_ok(value, ftype):
        return "MALFORMED", f"program output is not a WPL {ftype} literal"
    return "value", value


def bind_check(profile, prog_src: str, resolve):
    """The profile describes ONE ski@v1 check: recompiling the source must
    reproduce exactly that check's term and expect."""
    check_hex = profile["check"]
    if not is_hex64(check_hex):
        raise Refusal("CHECK_ADDRESS_INVALID")
    raw = resolve(check_hex)
    if raw is None:
        raise Refusal("CHECK_UNRESOLVED")
    try:
        doc = strict_loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise Refusal(f"CHECK_BLOB_INVALID:{exc}") from exc
    if not isinstance(doc, dict) or set(doc) != {"ski", "term", "atp", "expect"} or doc["ski"] != 1 \
            or not is_hex64(doc["term"]) or not is_hex64(doc["expect"]) \
            or not (isinstance(doc["atp"], int) and not isinstance(doc["atp"], bool) and 0 <= doc["atp"] < 2 ** 32):
        raise Refusal("CHECK_BLOB_SHAPE")
    try:
        compiled = PL.compile_source(prog_src, put=None)
    except PL.PolicyError as exc:
        raise Refusal(f"POLICY_SOURCE_DOES_NOT_COMPILE:{exc}") from exc
    if compiled.doc["term"] != doc["term"]:
        raise Refusal("CHECK_TERM_MISMATCH:the cited check is not the compilation of policy_source")
    if compiled.doc["expect"] != doc["expect"]:
        raise Refusal("CHECK_EXPECT_MISMATCH")
    if doc["atp"] < compiled.doc["atp"]:
        raise Refusal("CHECK_ATP_BELOW_COMPILED")
    return doc


def bind_record(profile, profile_hex: str, body) -> None:
    """The record must cite the check as a ski@v1 reason and list the
    profile, the source and every blob the profile reads. Signatures are not
    checked here."""
    if not isinstance(body, dict):
        raise Refusal("RECORD_BODY_SHAPE")
    because = body.get("because")
    if not isinstance(because, list) or not any(
            isinstance(r, dict) and r.get("kind") == "check" and r.get("runtime") == "ski@v1"
            and r.get("check") == profile["check"] for r in because):
        raise Refusal("RECORD_CHECK_NOT_CITED")
    ev = body.get("evidence")
    if not isinstance(ev, list) or not all(is_hex64(e) for e in ev):
        raise Refusal("RECORD_EVIDENCE_SHAPE")
    ev = set(ev)
    if profile_hex not in ev:
        raise Refusal("RECORD_PROFILE_NOT_CITED")
    if profile["policy_source"] not in ev:
        raise Refusal("RECORD_SOURCE_NOT_CITED")
    for name, entry in profile["facts"].items():
        kind = entry["via"]["kind"]
        if kind == "digest-eq":
            continue                    # two addresses compared, no bytes read
        if entry["from"] not in ev:
            raise Refusal(f"RECORD_EVIDENCE_NOT_CITED:{name}")
        if kind == "cmd" and entry["via"]["program"] not in ev:
            raise Refusal(f"RECORD_PROGRAM_NOT_CITED:{name}")


def check_profile(profile, resolve, execute=False, profile_hex=None, record_body=None):
    """Returns (facts: list of (name, verdict, detail), summary dict).
    Raises Refusal when the profile is not checkable."""
    if not isinstance(profile, dict) or profile.get("profile") != PROFILE:
        raise Refusal("PROFILE_UNKNOWN")
    if set(profile) != {"profile", "check", "policy_source", "facts"}:
        raise Refusal("PROFILE_SHAPE")
    src_hex = profile["policy_source"]
    if not is_hex64(src_hex):
        raise Refusal("POLICY_SOURCE_ADDRESS_INVALID")
    src = resolve(src_hex)
    if src is None:
        raise Refusal("POLICY_SOURCE_UNRESOLVED")
    try:
        text = src.decode("utf-8")
        prog = PL.parse(text)
    except (UnicodeDecodeError, PL.PolicyError) as exc:
        raise Refusal(f"POLICY_SOURCE_INVALID:{exc}") from exc
    entries = profile["facts"]
    if not isinstance(entries, dict):
        raise Refusal("FACTS_SHAPE")
    # Every shape rule first, before any evidence is read (R2).
    tokens = {}
    for name, entry in entries.items():
        if name not in prog.facts:
            raise Refusal(f"FACT_NOT_IN_SOURCE:{name}")
        if (not isinstance(entry, dict) or set(entry) != {"from", "via", "value"}
                or not is_hex64(entry["from"])):
            raise Refusal(f"FACT_ENTRY_SHAPE:{name}")
        f = prog.facts[name]
        if f.type not in FACT_TYPES:
            raise Refusal(f"FACT_TYPE_UNSUPPORTED:{name}:{f.type}")
        if entry["value"] != f.value or type(entry["value"]) is not type(f.value):
            raise Refusal(f"PROFILE_VALUE_NOT_IN_TERM:{name}")
        tokens[name] = validate_via(entry["via"], f.type, name)
    # The source IS the cited check (R1); the record cites all of it (optional).
    bind_check(profile, text, resolve)
    if record_body is not None:
        if profile_hex is None:
            raise Refusal("RECORD_NEEDS_PROFILE_ADDRESS")
        bind_record(profile, profile_hex, record_body)
    results = []
    for name, f in prog.facts.items():
        if name not in entries:
            results.append((name, "ASSERTED", "no derivation in the profile"))
            continue
        kind, payload = derive(entries[name], f.type, tokens[name], resolve, execute)
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


def report(profile_hex, results, summary, record_state) -> int:
    for name, verdict, detail in results:
        print(f"{verdict:10s} {name}  {detail}")
    counts = " ".join(f"{k.lower()}={v}" for k, v in summary.items())
    print(f"FACT-DERIVATION {profile_hex[:12]}: facts={len(results)} {counts} "
          f"check=bound record={record_state} semantic-credit=none")
    return 1 if summary["DIVERGED"] or summary["MALFORMED"] else 0


# --- selftest -----------------------------------------------------------------

def selftest() -> int:
    import copy
    controls = []
    store = {}

    def put(b):
        h = sha(b); store[h] = b; return h

    def resolve(h):
        return store.get(h)

    src_text = ('fact files_changed: int = 2\nfact lines_added: int = 267\n'
                'fact touches_ci: bool = true\nfact anchors_equal: bool = true\n'
                'fact proposed_by_agent: bool = true\nfact label: string = "docs"\n'
                'check files_changed <= 30 && lines_added <= 600 && !touches_ci\n'
                '      && anchors_equal && (!proposed_by_agent || lines_added <= 300)\n'
                '      && label == "docs"\n')
    src = put(src_text.encode())
    compiled = PL.compile_source(src_text, put=put)
    check = compiled.blob
    other = PL.compile_source(src_text.replace("lines_added: int = 267", "lines_added: int = 268"), put=put).blob
    assert other != check
    evidence = put(b'{"lines_added": 267, "paths": [".github/x.yml", "README.md"], "label": "docs", "meta": {"a~b": {"c/d": true}}}')
    program = put(b'import json, sys\nd = json.load(open(sys.argv[1]))\n'
                  b'print(json.dumps(any(p.startswith(sys.argv[2]) for p in d["paths"])))\n')
    digest_a = "a" * 64
    profile = {"profile": PROFILE, "check": check, "policy_source": src, "facts": {
        "files_changed": {"from": evidence, "via": {"kind": "json-len", "pointer": "/paths"}, "value": 2},
        "lines_added": {"from": evidence, "via": {"kind": "json", "pointer": "/lines_added"}, "value": 267},
        "touches_ci": {"from": evidence, "via": {"kind": "cmd", "program": program, "args": [".github/"]}, "value": True},
        "anchors_equal": {"from": digest_a, "via": {"kind": "digest-eq", "other": digest_a}, "value": True},
        "label": {"from": evidence, "via": {"kind": "json", "pointer": "/label"}, "value": "docs"},
    }}
    canon = lambda d: json.dumps(d, sort_keys=True, separators=(",", ":")).encode()

    def verdicts(p, execute=False, **kw):
        results, _ = check_profile(p, resolve, execute, **kw)
        return {n: v for n, v, _ in results}

    def mutant(fn):
        p = copy.deepcopy(profile); fn(p); return p

    def refuses(name, p, expected, **kw):
        try:
            check_profile(p, resolve, **kw)
        except Refusal as exc:
            assert expected in str(exc), (name, exc)
            controls.append(name); return
        raise AssertionError(f"{name}: survived")

    got = verdicts(profile)
    assert got == {"files_changed": "DERIVED", "lines_added": "DERIVED", "touches_ci": "UNRUN",
                   "anchors_equal": "DERIVED", "label": "DERIVED", "proposed_by_agent": "ASSERTED"}, got
    controls.append("positive: json, json-len, digest-eq derive; cmd unrun by default; unlisted fact asserted")
    assert verdicts(profile, execute=True)["touches_ci"] == "DERIVED"
    controls.append("cmd derives when executed")

    # R1: the profile describes ONE check, and the source must compile to it.
    refuses("R1 check is not the compilation of the source", mutant(lambda p: p.__setitem__("check", other)), "CHECK_TERM_MISMATCH")
    refuses("R1 check blob absent", mutant(lambda p: p.__setitem__("check", "b" * 64)), "CHECK_UNRESOLVED")
    refuses("R1 check blob wrong shape", mutant(lambda p: p.__setitem__("check", put(b'{"ski":1,"term":"x"}'))), "CHECK_BLOB_SHAPE")
    refuses("R1 check atp below compiled", mutant(lambda p: p.__setitem__("check", put(canon(dict(compiled.doc, atp=1))))), "CHECK_ATP_BELOW_COMPILED")
    body = {"decision": "accept", "evidence": [src, evidence, program, "0" * 64],
            "because": [{"kind": "check", "runtime": "ski@v1", "check": check, "verdict": "pass"}]}
    prof_hex = put(canon(profile)); body["evidence"].append(prof_hex)
    got = verdicts(profile, profile_hex=prof_hex, record_body=body)
    assert got["lines_added"] == "DERIVED"; controls.append("R1 record cites check, profile, source and evidence")
    refuses("R1 record does not cite the check", profile, "RECORD_CHECK_NOT_CITED", profile_hex=prof_hex,
            record_body=dict(body, because=[dict(body["because"][0], check=other)]))
    refuses("R1 record does not cite the profile", profile, "RECORD_PROFILE_NOT_CITED", profile_hex=prof_hex,
            record_body=dict(body, evidence=[e for e in body["evidence"] if e != prof_hex]))
    refuses("R1 record does not cite the source", profile, "RECORD_SOURCE_NOT_CITED", profile_hex=prof_hex,
            record_body=dict(body, evidence=[e for e in body["evidence"] if e != src]))
    refuses("R1 record does not cite a fact's evidence", profile, "RECORD_EVIDENCE_NOT_CITED", profile_hex=prof_hex,
            record_body=dict(body, evidence=[e for e in body["evidence"] if e != evidence]))
    refuses("R1 record does not cite the cmd program", profile, "RECORD_PROGRAM_NOT_CITED", profile_hex=prof_hex,
            record_body=dict(body, evidence=[e for e in body["evidence"] if e != program]))

    # R2: extractor shape is validated before any evidence is read.
    for present in (evidence, "f" * 64):
        tag = "present" if present == evidence else "missing"
        refuses(f"R2 unknown kind, evidence {tag}", mutant(lambda p: p["facts"]["label"].update(via={"kind": "regex"}, **{"from": present})), "VIA_UNKNOWN")
        refuses(f"R2 json without pointer, evidence {tag}", mutant(lambda p: p["facts"]["label"].update(via={"kind": "json"}, **{"from": present})), "VIA_SHAPE")
        refuses(f"R2 json-len on a string fact, evidence {tag}", mutant(lambda p: p["facts"]["label"].update(via={"kind": "json-len", "pointer": "/paths"}, **{"from": present})), "VIA_TYPE")
        refuses(f"R2 cmd with non-list args, evidence {tag}", mutant(lambda p: p["facts"]["touches_ci"].update(via={"kind": "cmd", "program": program, "args": "x"}, **{"from": present})), "VIA_SHAPE")
        refuses(f"R2 digest-eq with a bad other, evidence {tag}", mutant(lambda p: p["facts"]["anchors_equal"].update(via={"kind": "digest-eq", "other": "zz"}, **{"from": present})), "VIA_SHAPE")

    # R3: the advertised grammars.
    esc = put(b'{"a~2b": 1}')
    refuses("R3 pointer with ~2 is invalid syntax", mutant(lambda p: p["facts"]["lines_added"].update(via={"kind": "json", "pointer": "/a~2b"}, **{"from": esc})), "POINTER_INVALID")
    refuses("R3 pointer without leading slash", mutant(lambda p: p["facts"]["label"]["via"].__setitem__("pointer", "label")), "POINTER_INVALID")
    nan = put(b'{"items": [NaN], "lines_added": 267, "label": "docs"}')
    got = verdicts(mutant(lambda p: p["facts"]["files_changed"].update(via={"kind": "json-len", "pointer": "/items"}, **{"from": nan})))
    assert got["files_changed"] == "MALFORMED", got; controls.append("R3 NaN is outside JSON: MALFORMED")
    lone = put(b'{"lines_added": 267, "label": "\\udc00"}')
    got = verdicts(mutant(lambda p: p["facts"]["label"].__setitem__("from", lone)))
    assert got["label"] == "MALFORMED", got; controls.append("R3 lone surrogate is not UTF-8 text: MALFORMED")
    good_esc = mutant(lambda p: p["facts"].__setitem__("touches_ci", {"from": evidence, "via": {"kind": "json", "pointer": "/meta/a~0b/c~1d"}, "value": True}))
    assert verdicts(good_esc)["touches_ci"] == "DERIVED"; controls.append("R3 ~0 ~1 escapes resolve")

    # R4: addresses are exactly 64 hex characters, everywhere.
    for bad in ("a" * 64 + "\n", "a" * 65, "a" * 63, "A" * 64):
        refuses(f"R4 bad from address {bad[-3:]!r}", mutant(lambda p: p["facts"]["anchors_equal"].__setitem__("from", bad)), "FACT_ENTRY_SHAPE")
        refuses(f"R4 bad other address {bad[-3:]!r}", mutant(lambda p: p["facts"]["anchors_equal"]["via"].__setitem__("other", bad)), "VIA_SHAPE")
    refuses("R4 bad program address", mutant(lambda p: p["facts"]["touches_ci"]["via"].__setitem__("program", "c" * 64 + "\n")), "VIA_SHAPE")
    refuses("R4 bad policy_source address", mutant(lambda p: p.__setitem__("policy_source", src + "\n")), "POLICY_SOURCE_ADDRESS_INVALID")
    refuses("R4 bad check address", mutant(lambda p: p.__setitem__("check", check + "\n")), "CHECK_ADDRESS_INVALID")

    # Divergence, the failing verdict.
    tampered = put(b'{"lines_added": 268, "paths": [".github/x.yml", "README.md"], "label": "docs"}')
    assert verdicts(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", tampered)))["lines_added"] == "DIVERGED"
    controls.append("diverged: evidence says 268, term bakes 267")
    assert verdicts(mutant(lambda p: p["facts"]["anchors_equal"].__setitem__("from", "b" * 64)))["anchors_equal"] == "DIVERGED"
    controls.append("diverged: digest-eq over unequal digests")
    bad_prog = put(b'print("false")\n')
    assert verdicts(mutant(lambda p: p["facts"]["touches_ci"]["via"].__setitem__("program", bad_prog)), execute=True)["touches_ci"] == "DIVERGED"
    controls.append("diverged: cmd output contradicts the term")

    # Other shapes.
    refuses("profile value not baked into the term", mutant(lambda p: p["facts"]["lines_added"].__setitem__("value", 266)), "PROFILE_VALUE_NOT_IN_TERM")
    refuses("bool/int confusion is not equality", mutant(lambda p: p["facts"]["touches_ci"].__setitem__("value", 1)), "PROFILE_VALUE_NOT_IN_TERM")
    refuses("fact not in source", mutant(lambda p: p["facts"].__setitem__("ghost", p["facts"]["label"])), "FACT_NOT_IN_SOURCE")
    refuses("extra profile field", mutant(lambda p: p.__setitem__("bound", True)), "PROFILE_SHAPE")
    refuses("policy source not WPL", mutant(lambda p: p.__setitem__("policy_source", put(b"not wpl"))), "POLICY_SOURCE_INVALID")
    got = verdicts(mutant(lambda p: p["facts"]["label"]["via"].__setitem__("pointer", "/missing")))
    assert got["label"] == "UNRESOLVED", got; controls.append("unresolved: pointer names nothing")
    got = verdicts(mutant(lambda p: p["facts"]["label"].__setitem__("from", "c" * 64)))
    assert got["label"] == "UNRESOLVED", got; controls.append("unresolved: evidence blob absent")
    got = verdicts(mutant(lambda p: p["facts"]["touches_ci"]["via"].__setitem__("program", "d" * 64)), execute=True)
    assert got["touches_ci"] == "UNRESOLVED", got; controls.append("unresolved: program blob absent")
    floaty = put(b'{"lines_added": 267.0, "paths": [], "label": "docs"}')
    assert verdicts(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", floaty)))["lines_added"] == "MALFORMED"
    controls.append("malformed: float where an int fact is baked")
    longs = put(b'{"lines_added": 267, "paths": [], "label": "' + b"x" * 40 + b'"}')
    assert verdicts(mutant(lambda p: p["facts"]["label"].__setitem__("from", longs)))["label"] == "MALFORMED"
    controls.append("malformed: string over 32 bytes")
    dup = put(b'{"lines_added": 1, "lines_added": 267, "paths": [], "label": "docs"}')
    assert verdicts(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", dup)))["lines_added"] == "MALFORMED"
    controls.append("malformed: duplicate JSON key in evidence")

    with tempfile.TemporaryDirectory() as td:
        blobs = Path(td) / "blobs"; blobs.mkdir()
        (blobs / ("e" * 64)).write_bytes(b"not those bytes")
        assert store_resolver(Path(td))("e" * 64) is None
        h = sha(b"real"); (blobs / h).write_bytes(b"real")
        assert store_resolver(Path(td))(h) == b"real"
        assert store_resolver(Path(td))("../records") is None
        assert store_resolver(Path(td))(h + "\n") is None
    controls.append("store resolver: address must hash; no traversal; exact length")

    import io, contextlib
    res, summ = check_profile(profile, resolve)
    with contextlib.redirect_stdout(io.StringIO()):
        assert report("x" * 64, res, summ, "unverified") == 0
    res, summ = check_profile(mutant(lambda p: p["facts"]["lines_added"].__setitem__("from", tampered)), resolve)
    with contextlib.redirect_stdout(io.StringIO()):
        assert report("x" * 64, res, summ, "unverified") == 1
    controls.append("exit 1 only on DIVERGED/MALFORMED")

    print(f"FACT-DERIVATION-SELFTEST: ALL PASS ({len(controls)} controls)")
    return 0


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", help="a .warrants store (blobs/ and records/ under it)")
    ap.add_argument("--profile", help="hex64 of the profile blob in that store")
    ap.add_argument("--record", help="WarrantID whose record must cite the check, the profile, "
                                     "the source and every evidence blob (signatures are not checked here)")
    ap.add_argument("--execute-cmd", action="store_true",
                    help="run `cmd` derivations on the host python3 (no container is provided; never the default)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.selftest:
            return selftest()
        if not (a.store and a.profile):
            ap.error("--store and --profile are required unless --selftest")
        if not is_hex64(a.profile):
            raise Refusal("PROFILE_ADDRESS_INVALID")
        store = Path(a.store)
        resolve = store_resolver(store)
        raw = resolve(a.profile)
        if raw is None:
            raise Refusal("PROFILE_UNRESOLVED")
        try:
            profile = strict_loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise Refusal(f"PROFILE_JSON:{exc}") from exc
        body = None
        record_state = "unverified"
        if a.record:
            if not is_hex64(a.record):
                raise Refusal("RECORD_ADDRESS_INVALID")
            rp = store / "records" / f"{a.record}.json"
            if not rp.is_file() or rp.is_symlink():
                raise Refusal("RECORD_UNRESOLVED")
            try:
                rec = strict_loads(rp.read_bytes())
            except (ValueError, UnicodeDecodeError) as exc:
                raise Refusal(f"RECORD_JSON:{exc}") from exc
            body = rec.get("body") if isinstance(rec, dict) else None
            record_state = "cited (signatures not checked here; run warrant verify)"
        results, summary = check_profile(profile, resolve, a.execute_cmd, profile_hex=a.profile, record_body=body)
        return report(a.profile, results, summary, record_state)
    except (Refusal, AssertionError) as exc:
        print(f"REFUSED  {exc}")
        return 1
    except Exception as exc:  # the last membrane, never the schema
        print(f"REFUSED  INTERNAL_UNTYPED:{type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
