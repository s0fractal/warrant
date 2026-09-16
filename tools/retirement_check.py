#!/usr/bin/env python3
"""Check the retirement records in history/retirement-records/.

A retirement record says that exact bytes left the default tree at an exact
commit, what took over their role, what was lost, and how to get them back
with status. This checker reads those records AS DATA and refuses when an
operand is not what the record says it is. It never checks that retiring was
wise, and it prints no repository-level "forgetting" badge: VALID is per
record and means only that the record's operands bound and its postconditions
replayed green.

Profile `warrant.retirement-record@v0.1` is the in-repo APPLIED slice of
Manifesto's RetirementRecord form (CONTROLLED-FORGETTING-0.1 §6, as narrowed
by its Phase 2 consumer). It is a LOCAL profile: Manifesto's checker is not the
consumer of these records and no authority is borrowed from it. Every other
status/scope combination is refused rather than half-checked.

The oracle is EXPECTED below, not the records: a record cannot certify its
own verdict, and the record set must equal the manifest, so deleting a fixture
is a failure rather than a quiet pass.

Ported from sigma-glyph's checker at its post-review state (PR #52 + Codex
corrections: inventory pinned here, relative citations scanned); only the
profile, the manifest and the tombstone class differ.

    python3 tools/retirement_check.py               # validate + replay every record
    python3 tools/retirement_check.py --surface ID  # one record's live-surface postcondition
    python3 tools/retirement_check.py --selftest    # burn each refusal with a mutation
"""
from __future__ import annotations

import copy
import hashlib
import json
import posixpath
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "history" / "retirement-records"
PROFILE = "warrant.retirement-record@v0.1"

# The closed oracle: ids, filenames and verdicts live here, where a fixture
# cannot edit them.
EXPECTED = {
    "review-corpus-2026-07": "VALID",
    "work-orders-2026-07": "VALID",
    "wrt-002-model": "VALID",
}

# Independent subject inventory: omission, reassignment or mode drift requires
# an explicit checker change, not just an edited receipt. Not a trust anchor
# against an author who also edits this checker.
SUBJECT_INVENTORIES = {"review-corpus-2026-07": "45bc6f8e629c506082097d89154a02ed80e17729de4cc134b5e193cfbc1a5122", "work-orders-2026-07": "7a4591075141e82830070e0c5b256bc71d49fad93b505d1cd30f9ede128ec24e", "wrt-002-model": "538d410b580a613186705f9f99c388474566243e63be1f719286f4eff6282f6d"}

# Tombstone and immutable-history class, excluded from the zombie scan: the
# ledger and records name retired paths on purpose; `.warrants/` is a signed,
# content-addressed store whose blobs cannot be edited without corrupting it;
# the changelog is a dated log. Nothing else is excluded.
TOMBSTONE_CLASS = ("history/", ".warrants/", "CHANGELOG.md")

ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
REV_RE = re.compile(r"^[0-9a-f]{40}$")
MODES = {"SUPERSEDED", "WITHDRAWN", "REFUTED", "ARCHIVED", "ABANDONED", "QUARANTINED"}
RELATIONS = {"replaced-by", "extracted-from", "none"}
RUNNERS = {"python3"}
ADMISSION = {"default": {"EXCLUDED"},
             "historical_review": {"ALLOWED_WITH_STATUS", "FORBIDDEN"},
             "normative_use": {"FORBIDDEN_WITHOUT_READOPTION", "FORBIDDEN"}}
REQUIRED = {"profile", "id", "status", "subject_scope", "before_revision", "subjects",
            "replacement", "loss", "preservation", "admission", "authority", "applied",
            "postconditions"}
TIMEOUT_SECONDS = 300


class Refusal(Exception):
    pass


# --- primitives -------------------------------------------------------------

def strict_loads(text: str):
    def hook(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise Refusal(f"DUPLICATE_JSON_KEY:{key}")
            out[key] = value
        return out
    try:
        return json.loads(text, object_pairs_hook=hook)
    except json.JSONDecodeError as exc:
        raise Refusal(f"JSON_INVALID:{exc}") from exc


def nonempty(value, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refusal(code)
    return value


def string_list(value, code: str, allow_empty: bool = False) -> list:
    if not isinstance(value, list) or (not value and not allow_empty):
        raise Refusal(code)
    for item in value:
        nonempty(item, code)
    return value


def rel_path(rel, code: str) -> Path:
    if (not isinstance(rel, str) or not rel or Path(rel).is_absolute()
            or ".." in Path(rel).parts or Path(rel).as_posix() != rel):
        raise Refusal(f"{code}:PATH_INVALID")
    cursor = ROOT
    for part in Path(rel).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise Refusal(f"{code}:SYMLINK:{rel}")
    return ROOT / rel


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True)


def pinned_operand(operand, code: str) -> str:
    if not isinstance(operand, dict) or set(operand) != {"path", "sha256"}:
        raise Refusal(f"{code}:SCHEMA")
    rel, expected = operand["path"], operand["sha256"]
    target = rel_path(rel, code)
    if not isinstance(expected, str) or not HEX64_RE.fullmatch(expected):
        raise Refusal(f"{code}:PIN_INVALID")
    if not target.is_file():
        raise Refusal(f"{code}:MISSING:{rel}")
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise Refusal(f"{code}:DIGEST_MISMATCH:{rel}")
    return rel


def historical_digest(revision: str, rel: str, code: str) -> str:
    """The subject is gone from the tree -- that is the point -- so its digest
    comes from the object git holds at the before revision."""
    proc = git("cat-file", "blob", f"{revision}:{rel}")
    if proc.returncode != 0:
        raise Refusal(f"{code}:SUBJECT_ABSENT_AT_BEFORE_REVISION:{rel}")
    return hashlib.sha256(proc.stdout).hexdigest()


# --- validation ---------------------------------------------------------------

def check_applied(record, revision: str) -> str:
    applied = record["applied"]
    if not isinstance(applied, dict) or set(applied) != {"apply_commit", "apply_tree", "receipt"}:
        raise Refusal("APPLIED_SCHEMA")
    for field in ("apply_commit", "apply_tree"):
        if not isinstance(applied[field], str) or not REV_RE.fullmatch(applied[field]):
            raise Refusal(f"APPLIED_{field.upper()}_INVALID")
    nonempty(applied["receipt"], "APPLIED_RECEIPT_EMPTY")
    parent = git("rev-parse", f"{applied['apply_commit']}^")
    if parent.returncode != 0 or parent.stdout.decode().strip() != revision:
        raise Refusal("APPLY_COMMIT_NOT_CHILD_OF_BEFORE_REVISION")
    tree = git("rev-parse", f"{applied['apply_commit']}^{{tree}}")
    if tree.returncode != 0 or tree.stdout.decode().strip() != applied["apply_tree"]:
        raise Refusal("APPLY_TREE_MISMATCH")
    return applied["apply_tree"]


def check_subjects(record, revision: str, apply_tree: str) -> list:
    subjects = record["subjects"]
    if not isinstance(subjects, list) or not subjects:
        raise Refusal("SUBJECTS_EMPTY")
    seen = set()
    for subject in subjects:
        if not isinstance(subject, dict) or set(subject) != {"path", "sha256", "mode", "reason"}:
            raise Refusal("SUBJECT_FIELDS_NOT_CLOSED")
        if subject["mode"] not in MODES:
            raise Refusal(f"SUBJECT_MODE_UNKNOWN:{subject['mode']!r}")
        nonempty(subject["reason"], "SUBJECT_REASON_EMPTY")
        rel, expected = subject["path"], subject["sha256"]
        rel_path(rel, "SUBJECT")
        if not isinstance(expected, str) or not HEX64_RE.fullmatch(expected):
            raise Refusal(f"SUBJECT_PIN_INVALID:{rel}")
        # The transition itself: the subject existed at the before revision
        # with these bytes, and the named apply commit is where it stopped.
        if historical_digest(revision, rel, "SUBJECT") != expected:
            raise Refusal(f"SUBJECT_DIGEST_MISMATCH:{rel}")
        if git("cat-file", "-e", f"{apply_tree}:{rel}").returncode == 0:
            raise Refusal(f"SUBJECT_PRESENT_IN_APPLY_TREE:{rel}")
        if (ROOT / rel).exists():
            raise Refusal(f"RETIRED_SUBJECT_STILL_PRESENT:{rel}")
        if rel in seen:
            raise Refusal(f"SUBJECT_DUPLICATE:{rel}")
        seen.add(rel)
    return [s["path"] for s in subjects]


def check_subject_inventory(record) -> None:
    rid = record.get("id")
    if rid not in SUBJECT_INVENTORIES:
        raise Refusal(f"RECORD_NOT_IN_MANIFEST:{rid}")
    subjects = record.get("subjects")
    if not isinstance(subjects, list) or not subjects:
        raise Refusal("SUBJECTS_EMPTY")
    if any(not isinstance(s, dict) or any(not isinstance(s.get(k), str)
           for k in ("path", "sha256", "mode")) for s in subjects):
        raise Refusal("SUBJECT_FIELDS_NOT_CLOSED")
    inventory = sorted((s["path"], s["sha256"], s["mode"]) for s in subjects)
    digest = hashlib.sha256(json.dumps(inventory, separators=(",", ":")).encode()).hexdigest()
    if digest != SUBJECT_INVENTORIES[rid]:
        raise Refusal(f"SUBJECT_INVENTORY_MISMATCH:{rid}")


def postcondition_argv(post) -> list:
    """argv is CONSTRUCTED here, never taken from the record: a record that
    supplied its own argv could pin an entrypoint and pass it as an inert
    argument to something else, so the pin would bind and nothing would run."""
    if not isinstance(post, dict) or set(post) != {"runner", "entrypoint", "args", "falsifier"}:
        raise Refusal("POSTCONDITION_SCHEMA")
    if post["runner"] not in RUNNERS:
        raise Refusal(f"POSTCONDITION_RUNNER_NOT_ALLOWED:{post['runner']!r}")
    args = string_list(post["args"], "POSTCONDITION_ARGS_INVALID", allow_empty=True)
    nonempty(post["falsifier"], "POSTCONDITION_FALSIFIER_EMPTY")
    rel = pinned_operand(post["entrypoint"], "POSTCONDITION_ENTRYPOINT")
    return [post["runner"], rel, *args]


def validate(record) -> dict:
    if not isinstance(record, dict):
        raise Refusal("RECORD_NOT_AN_OBJECT")
    if record.get("profile") != PROFILE:
        raise Refusal("PROFILE_UNKNOWN")
    rid = record.get("id")
    if not isinstance(rid, str) or not ID_RE.fullmatch(rid):
        raise Refusal(f"RECORD_ID_INVALID:{rid!r}")
    if record.get("status") != "APPLIED":
        raise Refusal(f"STATUS_UNSUPPORTED_IN_V0_1:{record.get('status')!r}")
    if record.get("subject_scope") != "in-repo":
        raise Refusal(f"SCOPE_UNSUPPORTED_IN_V0_1:{record.get('subject_scope')!r}")
    # Exact shape BEFORE anything indexes a field: a missing key is a typed
    # refusal, not a traceback.
    missing = sorted(REQUIRED - set(record))
    if missing:
        raise Refusal(f"REQUIRED_FIELD_MISSING:{','.join(missing)}")
    unknown = sorted(set(record) - REQUIRED)
    if unknown:
        raise Refusal(f"RECORD_FIELDS_UNKNOWN:{','.join(unknown)}")

    revision = record["before_revision"]
    if not isinstance(revision, str) or not REV_RE.fullmatch(revision):
        raise Refusal("BEFORE_REVISION_INVALID")
    if git("cat-file", "-e", f"{revision}^{{commit}}").returncode != 0:
        raise Refusal(f"BEFORE_REVISION_UNRESOLVABLE:{revision}")
    apply_tree = check_applied(record, revision)
    paths = check_subjects(record, revision, apply_tree)

    replacement = record["replacement"]
    if not isinstance(replacement, dict) or set(replacement) != {"relation", "operands"}:
        raise Refusal("REPLACEMENT_SCHEMA")
    relation, operands = replacement["relation"], replacement["operands"]
    if relation not in RELATIONS:
        raise Refusal(f"RELATION_UNKNOWN:{relation!r}")
    if not isinstance(operands, list):
        raise Refusal("REPLACEMENT_OPERANDS_SCHEMA")
    if relation == "none" and operands:
        raise Refusal("RELATION_NONE_CARRIES_OPERANDS")
    if relation != "none" and not operands:
        raise Refusal(f"RELATION_WITHOUT_OPERANDS:{relation}")
    for operand in operands:
        if isinstance(operand, dict) and set(operand) == {"path", "sha256"}:
            pinned_operand(operand, "REPLACEMENT_OPERAND")
        elif isinstance(operand, dict) and set(operand) == {"locator", "note"}:
            nonempty(operand["locator"], "REPLACEMENT_OPERAND:LOCATOR_EMPTY")
            nonempty(operand["note"], "REPLACEMENT_OPERAND:NOTE_EMPTY")
        else:
            raise Refusal("REPLACEMENT_OPERAND:SCHEMA")

    # Loss is mandatory for every mode. An empty list is unmeasured, not zero.
    string_list(record["loss"], "LOSS_EMPTY")

    preservation = record["preservation"]
    if not isinstance(preservation, dict) or set(preservation) != {"policy", "locator"}:
        raise Refusal("PRESERVATION_SCHEMA")
    nonempty(preservation["policy"], "PRESERVATION_POLICY_EMPTY")
    nonempty(preservation["locator"], "PRESERVATION_LOCATOR_EMPTY")

    admission = record["admission"]
    if not isinstance(admission, dict) or set(admission) != set(ADMISSION):
        raise Refusal("ADMISSION_SCHEMA")
    for field, allowed in ADMISSION.items():
        if admission[field] not in allowed:
            raise Refusal(f"ADMISSION_{field.upper()}_UNKNOWN")

    # An ADDRESS for the act, never a proof it was within anyone's power.
    authority = record["authority"]
    if not isinstance(authority, dict) or set(authority) != {"owner", "act"}:
        raise Refusal("AUTHORITY_SCHEMA")
    nonempty(authority["owner"], "AUTHORITY_OWNER_EMPTY")
    nonempty(authority["act"], "AUTHORITY_ACT_UNADDRESSED")

    posts = record["postconditions"]
    if not isinstance(posts, list):
        raise Refusal("POSTCONDITIONS_SCHEMA")
    if not posts:
        # An applied retirement whose only evidence is prose is the failure
        # this discipline exists to stop being.
        raise Refusal("APPLIED_WITHOUT_POSTCONDITION")
    check_subject_inventory(record)
    argvs = [postcondition_argv(post) for post in posts]
    return {"id": rid, "subjects": paths, "relation": relation, "argvs": argvs}


def replay(summary) -> int:
    for argv in summary["argvs"]:
        try:
            proc = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=TIMEOUT_SECONDS)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Refusal(f"POSTCONDITION_ERROR:{type(exc).__name__}") from exc
        if proc.returncode != 0:
            raise Refusal(f"POSTCONDITION_RED:{' '.join(argv)}:exit={proc.returncode}")
    return len(summary["argvs"])


# --- live surface (the postcondition each record pins) ------------------------

def tracked_files() -> list:
    proc = git("ls-files", "-z")
    if proc.returncode != 0:
        raise Refusal("GIT_LS_FILES_FAILED")
    out = []
    for rel in proc.stdout.decode().split("\0"):
        if not rel or rel.startswith(TOMBSTONE_CLASS) or rel in TOMBSTONE_CLASS:
            continue
        path = ROOT / rel
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            # A binary artifact is preservation or data, not a citation.
            continue
        out.append((rel, data))
    return out


def surface_scan(retired: list, tracked: list, present) -> int:
    """Two predicates over the live tree: no retired subject is back, and no
    tracked file outside the tombstone class cites a retired path as if it
    were current. `tracked` and `present` are injected so the selftest can
    exercise both refusals without touching the repository."""
    for rel in retired:
        if present(rel):
            raise Refusal(f"RETIRED_SUBJECT_STILL_PRESENT:{rel}")
    for file_rel, data in tracked:
        for rel in retired:
            relative = posixpath.relpath(rel, posixpath.dirname(file_rel) or ".")
            if rel.encode() in data or relative.encode() in data:
                raise Refusal(f"ZOMBIE_REFERENCE:{file_rel}:{rel}")
    return len(retired)


def surface(rid: str) -> int:
    if rid not in EXPECTED:
        raise Refusal(f"RECORD_NOT_IN_MANIFEST:{rid}")
    path = RECORDS / f"{rid}.json"
    if not path.is_file():
        raise Refusal(f"RECORD_MISSING:{rid}")
    record = strict_loads(path.read_text(encoding="utf-8"))
    subjects = record.get("subjects") if isinstance(record, dict) else None
    if not isinstance(subjects, list) or not subjects:
        raise Refusal("SUBJECTS_EMPTY")
    check_subject_inventory(record)
    retired = [s.get("path") for s in subjects]
    if any(not isinstance(rel, str) or not rel for rel in retired):
        raise Refusal("SUBJECT_FIELDS_NOT_CLOSED")
    count = surface_scan(retired, tracked_files(), lambda rel: (ROOT / rel).exists())
    print(f"RETIRED-SURFACE {rid}: {count} retired, 0 zombie references")
    return 0


# --- record set -----------------------------------------------------------------

def check_manifest(found: dict) -> None:
    missing = sorted(set(EXPECTED) - set(found))
    if missing:
        raise Refusal(f"RECORD_MISSING:{','.join(missing)}")
    unexpected = sorted(set(found) - set(EXPECTED))
    if unexpected:
        raise Refusal(f"RECORD_NOT_IN_MANIFEST:{','.join(unexpected)}")
    for rid, stem in sorted(found.items()):
        if stem != rid:
            raise Refusal(f"RECORD_FILENAME_ID_MISMATCH:{stem}!={rid}")


def load_records(directory: Path = RECORDS) -> list:
    """The loader is the membrane: every hostile shape a file can take is a
    typed refusal here, before anything downstream assumes a mapping."""
    if not directory.is_dir():
        raise Refusal("RECORDS_DIR_MISSING")
    out = []
    for path in sorted(directory.glob("*.json")):
        if path.is_symlink():
            raise Refusal(f"RECORD_SYMLINK:{path.name}")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise Refusal(f"RECORD_UNREADABLE:{path.name}:{type(exc).__name__}") from exc
        record = strict_loads(text)
        if not isinstance(record, dict):
            raise Refusal(f"RECORD_NOT_AN_OBJECT:{path.name}")
        out.append((path, record))
    return out


def run(directory: Path = RECORDS) -> int:
    records = load_records(directory)
    found = {}
    for path, record in records:
        rid = record.get("id")
        if not isinstance(rid, str) or not rid:
            raise Refusal(f"RECORD_ID_MISSING:{path.name}")
        if rid in found:
            raise Refusal(f"RECORD_ID_DUPLICATE:{rid}")
        found[rid] = path.stem
    check_manifest(found)

    mismatched = replayed = 0
    for _, record in sorted(records, key=lambda item: item[1]["id"]):
        rid = record["id"]
        try:
            summary = validate(record)
            n = replay(summary)
        except Refusal as exc:
            actual = f"REFUSED:{exc}"
        else:
            actual = "VALID"
        if actual != EXPECTED[rid]:
            print(f"MISMATCH {rid}  expected={EXPECTED[rid]}  actual={actual}")
            mismatched += 1
            continue
        replayed += n
        print(f"VALID    {rid}  subjects={len(summary['subjects'])} "
              f"relation={summary['relation']} postconditions-replayed={n}")
    # No repository-level badge: this counts records and says nothing about
    # whether the repository has forgotten well.
    print(f"RETIREMENT-RECORDS: records={len(records)} mismatched={mismatched} "
          f"postconditions-replayed={replayed} semantic-credit=none")
    if mismatched:
        print("RETIREMENT-RECORDS: FAIL")
        return 1
    print("RETIREMENT-RECORDS: ALL PASS")
    return 0


# --- selftest -----------------------------------------------------------------------

def selftest() -> int:
    loaded = load_records()
    found = {r["id"]: path.stem for path, r in loaded if isinstance(r.get("id"), str)}
    check_manifest(found)
    controls = ["live-record-set-matches-manifest"]
    records = {r["id"]: r for _, r in loaded}
    good = records["work-orders-2026-07"]
    pinned = records["review-corpus-2026-07"]  # the record whose replacement operands are pinned

    def refuses(name, base, mutate, expected):
        mutant = copy.deepcopy(base)
        mutate(mutant)
        try:
            validate(mutant)
        except Refusal as exc:
            if expected not in str(exc):
                raise AssertionError(f"{name}: wrong refusal {exc}") from exc
            controls.append(name)
            return
        raise AssertionError(f"{name}: mutation survived")

    refuses("subject-omission", good, lambda r: r["subjects"].pop(0),
            "SUBJECT_INVENTORY_MISMATCH")
    refuses("subject-mode-relabel", good,
            lambda r: r["subjects"][0].__setitem__("mode", "REFUTED"),
            "SUBJECT_INVENTORY_MISMATCH")
    refuses("empty-loss", good, lambda r: r.__setitem__("loss", []), "LOSS_EMPTY")
    refuses("loss-of-blanks", good, lambda r: r.__setitem__("loss", ["  "]), "LOSS_EMPTY")
    refuses("subject-digest-drift", good,
            lambda r: r["subjects"][0].__setitem__("sha256", "0" * 64), "SUBJECT_DIGEST_MISMATCH")
    refuses("subject-absent-at-before-revision", good,
            lambda r: r["subjects"][0].__setitem__("path", "NEVER-EXISTED.md"),
            "SUBJECT_ABSENT_AT_BEFORE_REVISION")
    refuses("empty-subjects", good, lambda r: r.__setitem__("subjects", []), "SUBJECTS_EMPTY")
    refuses("unknown-mode", good,
            lambda r: r["subjects"][0].__setitem__("mode", "DELETED"), "SUBJECT_MODE_UNKNOWN")
    refuses("redacted-is-not-this-profile", good,
            lambda r: r["subjects"][0].__setitem__("mode", "REDACTED"), "SUBJECT_MODE_UNKNOWN")
    refuses("unknown-relation", pinned,
            lambda r: r["replacement"].__setitem__("relation", "supersedes"), "RELATION_UNKNOWN")
    refuses("relation-none-with-operands", pinned,
            lambda r: r["replacement"].__setitem__("relation", "none"), "RELATION_NONE_CARRIES_OPERANDS")
    refuses("relation-without-operands", good,
            lambda r: r["replacement"].__setitem__("relation", "replaced-by"), "RELATION_WITHOUT_OPERANDS")
    refuses("replacement-operand-drift", pinned,
            lambda r: r["replacement"]["operands"][0].__setitem__("sha256", "0" * 64),
            "REPLACEMENT_OPERAND:DIGEST_MISMATCH")
    refuses("replacement-operand-shapeless", pinned,
            lambda r: r["replacement"]["operands"].append({"path": "README.md"}),
            "REPLACEMENT_OPERAND:SCHEMA")
    refuses("authority-unaddressed", good,
            lambda r: r["authority"].__setitem__("act", " "), "AUTHORITY_ACT_UNADDRESSED")
    refuses("apply-tree-drift", good,
            lambda r: r["applied"].__setitem__("apply_tree", "0" * 40), "APPLY_TREE_MISMATCH")
    refuses("apply-commit-not-child", good,
            lambda r: r["applied"].__setitem__("apply_commit", r["before_revision"]),
            "APPLY_COMMIT_NOT_CHILD_OF_BEFORE_REVISION")
    refuses("before-revision-unresolvable", good,
            lambda r: r.__setitem__("before_revision", "0" * 40), "BEFORE_REVISION_UNRESOLVABLE")
    refuses("applied-without-postcondition", good,
            lambda r: r.__setitem__("postconditions", []), "APPLIED_WITHOUT_POSTCONDITION")
    refuses("dry-run-unsupported", good,
            lambda r: r.__setitem__("status", "DRY_RUN"), "STATUS_UNSUPPORTED_IN_V0_1")
    refuses("external-unsupported", good,
            lambda r: r.__setitem__("subject_scope", "external"), "SCOPE_UNSUPPORTED_IN_V0_1")
    refuses("foreign-profile", good,
            lambda r: r.__setitem__("profile", "manifesto.retirement-record@v0.1"), "PROFILE_UNKNOWN")
    refuses("required-field-missing", good, lambda r: r.pop("loss"), "REQUIRED_FIELD_MISSING:loss")
    refuses("unknown-field", good, lambda r: r.__setitem__("expect", "VALID"), "RECORD_FIELDS_UNKNOWN")
    refuses("runner-not-allowed", good,
            lambda r: r["postconditions"][0].__setitem__("runner", "/usr/bin/true"),
            "POSTCONDITION_RUNNER_NOT_ALLOWED")
    refuses("postcondition-supplies-argv", good,
            lambda r: r["postconditions"][0].__setitem__("argv", ["/usr/bin/true"]),
            "POSTCONDITION_SCHEMA")
    refuses("postcondition-entrypoint-drift", good,
            lambda r: r["postconditions"][0]["entrypoint"].__setitem__("sha256", "0" * 64),
            "POSTCONDITION_ENTRYPOINT:DIGEST_MISMATCH")
    still_there = "README.md"
    refuses("subject-present-in-apply-tree", good,
            lambda r: r["subjects"].append({
                "path": still_there,
                "sha256": historical_digest(r["before_revision"], still_there, "CONTROL"),
                "mode": "ARCHIVED", "reason": "never actually removed"}),
            "SUBJECT_PRESENT_IN_APPLY_TREE")

    built = postcondition_argv(copy.deepcopy(good)["postconditions"][0])
    post = good["postconditions"][0]
    assert built == ["python3", post["entrypoint"]["path"], *post["args"]], built
    controls.append("constructed-argv-runs-the-pinned-entrypoint")

    def manifest_refuses(name, found, expected):
        try:
            check_manifest(found)
        except Refusal as exc:
            if expected not in str(exc):
                raise AssertionError(f"{name}: wrong refusal {exc}") from exc
            controls.append(name)
            return
        raise AssertionError(f"{name}: mutation survived")

    ids = {k: k for k in EXPECTED}
    manifest_refuses("manifest-record-deleted", {k: k for k in list(EXPECTED)[1:]}, "RECORD_MISSING")
    manifest_refuses("manifest-record-smuggled", {**ids, "friendly-extra": "friendly-extra"},
                     "RECORD_NOT_IN_MANIFEST")
    manifest_refuses("manifest-filename-id-mismatch", {**ids, "wrt-002-model": "other-name"},
                     "RECORD_FILENAME_ID_MISMATCH")

    def loader_refuses(name, payload, expected):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "x.json").write_bytes(payload)
            try:
                load_records(Path(tmp))
            except Refusal as exc:
                if expected not in str(exc):
                    raise AssertionError(f"{name}: wrong refusal {exc}") from exc
                controls.append(name)
                return
            raise AssertionError(f"{name}: mutation survived")

    loader_refuses("loader-non-object-json", b'["not", "a", "record"]', "RECORD_NOT_AN_OBJECT")
    loader_refuses("loader-malformed-json", b"{ broken", "JSON_INVALID")
    loader_refuses("loader-duplicate-key", b'{"id": "a", "id": "b"}', "DUPLICATE_JSON_KEY")

    # The live-surface predicates, each burned on its own.
    retired = ["gone/one.md", "gone/two.md"]
    try:
        surface_scan(retired, [], lambda rel: rel == "gone/two.md")
    except Refusal as exc:
        assert "RETIRED_SUBJECT_STILL_PRESENT:gone/two.md" in str(exc), exc
        controls.append("surface-resurrection")
    else:
        raise AssertionError("surface-resurrection: mutation survived")
    try:
        surface_scan(retired, [("docs/x.md", b"see gone/one.md for the rule")], lambda rel: False)
    except Refusal as exc:
        assert "ZOMBIE_REFERENCE:docs/x.md:gone/one.md" in str(exc), exc
        controls.append("surface-zombie-reference")
    else:
        raise AssertionError("surface-zombie-reference: mutation survived")
    assert surface_scan(retired, [("docs/x.md", b"unrelated")], lambda rel: False) == 2
    controls.append("surface-clean-passes")
    for file_rel, content in [("gone/index.md", b"[current](one.md)"),
                              ("docs/index.md", b"[current](../gone/one.md)")]:
        try:
            surface_scan(retired, [(file_rel, content)], lambda rel: False)
        except Refusal as exc:
            assert "ZOMBIE_REFERENCE" in str(exc), exc
            controls.append("surface-relative-zombie:" + file_rel)
        else:
            raise AssertionError("relative zombie survived")
    # ...and the real tree, through the real ls-files, must be clean now.
    for rid, record in records.items():
        surface_scan([s["path"] for s in record["subjects"]], tracked_files(),
                     lambda rel: (ROOT / rel).exists())
    controls.append("live-tree-surface-clean")

    # A green postcondition that is not actually run is the label-wider-than-
    # predicate failure in its purest form, so the red path is burned too.
    summary = validate(copy.deepcopy(good))
    with mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
        try:
            replay(summary)
        except Refusal as exc:
            assert "POSTCONDITION_RED" in str(exc)
            controls.append("red-postcondition")
        else:
            raise AssertionError("red-postcondition: mutation survived")

    print(f"RETIREMENT-CHECK-SELFTEST: ALL PASS ({len(controls)} mutation controls)")
    return 0


def main(argv: list) -> int:
    try:
        if "--selftest" in argv:
            return selftest()
        if "--surface" in argv:
            i = argv.index("--surface")
            if i + 1 >= len(argv):
                raise Refusal("SURFACE_NEEDS_RECORD_ID")
            return surface(argv[i + 1])
        return run()
    except (Refusal, AssertionError) as exc:
        print(f"REFUSED  {exc}")
        return 1
    except Exception as exc:  # the LAST membrane, never the schema
        print(f"REFUSED  INTERNAL_UNTYPED:{type(exc).__name__}:{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
