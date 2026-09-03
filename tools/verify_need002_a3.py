#!/usr/bin/env python3
"""Verify the closed NEED-002-A3 base evidence bundle and replay its claim."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "needs" / "need-002-a3-base"
RECORD = ROOT / "needs" / "NEED-002-A3-BASE.json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_LINE = re.compile(r"^([0-9a-f]{64})  ([^\0\r\n]+)$")
EXIT_UNRUN = 3


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def loads_strict(source: str) -> dict:
    def closed_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"DUPLICATE_JSON_KEY:{key}")
            result[key] = value
        return result

    value = json.loads(source, object_pairs_hook=closed_object)
    if not isinstance(value, dict):
        raise ValueError("RECORD_SCHEMA: record must be an object")
    return value


def load_record(path: Path = RECORD) -> dict:
    record = loads_strict(path.read_text(encoding="utf-8"))
    required = {
        "tag", "need", "status", "claim", "source_experiment", "operands",
        "result", "final_semantic_modules", "exclusions",
    }
    if set(record) != required:
        raise ValueError("RECORD_SCHEMA: top-level fields are not closed")
    if (record["tag"], record["need"], record["status"]) != (
        "warrant.need-evidence@v1", "NEED-002-BASE", "MET_BASE_ONLY"
    ):
        raise ValueError("RECORD_STATUS: expected the narrow base-only evidence status")
    source = record["source_experiment"]
    if set(source) != {"id", "commit", "evidence_manifest_sha256"}:
        raise ValueError("RECORD_SCHEMA: source_experiment fields are not closed")
    if source["id"] != "NEED-002-A3-COLLAB-JS" or not HEX64.fullmatch(source["evidence_manifest_sha256"]):
        raise ValueError("RECORD_SOURCE: malformed source experiment binding")
    if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
        raise ValueError("RECORD_SOURCE: malformed source commit")
    operands = record["operands"]
    if set(operands) != {
        "warrant_revision", "spec_sha256", "pack_version",
        "pack_manifest_digest", "pack_tarball_sha256",
    }:
        raise ValueError("RECORD_SCHEMA: operand fields are not closed")
    if not re.fullmatch(r"[0-9a-f]{40}", operands["warrant_revision"]):
        raise ValueError("RECORD_OPERANDS: malformed Warrant revision")
    if operands["pack_version"] != "1.2.0" or not all(
        HEX64.fullmatch(operands[key])
        for key in ("spec_sha256", "pack_manifest_digest", "pack_tarball_sha256")
    ):
        raise ValueError("RECORD_OPERANDS: malformed frozen operand binding")
    result = record["result"]
    if set(result) != {
        "report_sha256", "grade_claimed", "grade_achieved", "counts",
        "base_negative_vectors_answered", "base_negative_vectors_accepted",
        "runner_mutations_detected",
    }:
        raise ValueError("RECORD_SCHEMA: result fields are not closed")
    expected_counts = {"PASS": 135, "FAIL": 0, "UNRUN": 0, "ERROR": 0, "NOT-CLAIMED": 4}
    expected_mutations = {"accept-all", "legacy-sig", "false-unsupported", "crash"}
    if (
        not HEX64.fullmatch(result["report_sha256"])
        or result["grade_claimed"] != "base"
        or result["grade_achieved"] != "base"
        or result["counts"] != expected_counts
        or result["base_negative_vectors_answered"] != 60
        or result["base_negative_vectors_accepted"] != 0
        or set(result["runner_mutations_detected"]) != expected_mutations
        or len(result["runner_mutations_detected"]) != len(expected_mutations)
    ):
        raise ValueError("RECORD_RESULT: MET_BASE_ONLY does not carry the complete base vector")
    modules = record["final_semantic_modules"]
    expected_modules = {
        "candidate/canon.mjs", "candidate/hashing.mjs", "candidate/parse.mjs",
        "candidate/validate.mjs", "candidate/verify-sig.mjs",
        "candidate/verify-store.mjs",
    }
    if set(modules) != expected_modules or not all(HEX64.fullmatch(v) for v in modules.values()):
        raise ValueError("RECORD_MODULES: final module set or digest is invalid")
    if not isinstance(record["claim"], str) or not record["claim"]:
        raise ValueError("RECORD_CLAIM: missing claim text")
    if not isinstance(record["exclusions"], list) or not record["exclusions"] or not all(
        isinstance(item, str) and item for item in record["exclusions"]
    ):
        raise ValueError("RECORD_EXCLUSIONS: exclusions must be a nonempty string list")
    return record


def verify_integrity(bundle: Path, record: dict) -> list[str]:
    errors: list[str] = []
    manifest_path = bundle / "EVIDENCE-MANIFEST.sha256"
    if manifest_path.is_symlink():
        return ["MANIFEST_SYMLINK_NOT_ALLOWED"]
    if not manifest_path.is_file():
        return ["MANIFEST_MISSING"]
    actual_manifest_digest = sha256(manifest_path)
    if actual_manifest_digest != record["source_experiment"]["evidence_manifest_sha256"]:
        errors.append("MANIFEST_DIGEST_MISMATCH")

    entries: dict[str, str] = {}
    for number, line in enumerate(manifest_path.read_text(encoding="utf-8").splitlines(), 1):
        match = MANIFEST_LINE.fullmatch(line)
        if not match:
            errors.append(f"MANIFEST_MALFORMED:{number}")
            continue
        digest, rel = match.groups()
        if rel in entries or rel.startswith("/") or ".." in Path(rel).parts:
            errors.append(f"MANIFEST_PATH_INVALID:{rel}")
            continue
        entries[rel] = digest

    actual = set()
    for operand in bundle.rglob("*"):
        if operand == manifest_path or operand.is_dir() and not operand.is_symlink():
            continue
        rel = operand.relative_to(bundle).as_posix()
        actual.add(rel)
        if operand.is_symlink():
            errors.append(f"SYMLINK_NOT_ALLOWED:{rel}")
    declared = set(entries)
    if actual != declared:
        missing = sorted(declared - actual)
        extra = sorted(actual - declared)
        errors.append(f"CLOSED_SET_MISMATCH:missing={missing}:extra={extra}")
    for rel, expected in entries.items():
        operand = bundle / rel
        if operand.is_file() and sha256(operand) != expected:
            errors.append(f"OPERAND_DIGEST_MISMATCH:{rel}")

    for rel, expected in record["final_semantic_modules"].items():
        operand = bundle / rel
        if not operand.is_file() or sha256(operand) != expected:
            errors.append(f"FINAL_MODULE_MISMATCH:{rel}")
    direct_bindings = {
        "operands/SPEC.md": record["operands"]["spec_sha256"],
        "operands/warrant-conformance-1.2.0.tar.gz": record["operands"]["pack_tarball_sha256"],
        "operands/warrant-conformance-1.2.0/MANIFEST.sha256": record["operands"]["pack_manifest_digest"],
        "reports/s2.json": record["result"]["report_sha256"],
    }
    for rel, expected in direct_bindings.items():
        operand = bundle / rel
        if not operand.is_file() or sha256(operand) != expected:
            errors.append(f"CLAIM_OPERAND_MISMATCH:{rel}")
    return errors


def run_checked(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=180)


def replay(bundle: Path, record: dict, self_check: bool) -> list[str]:
    errors: list[str] = []
    if shutil.which("node") is None:
        return ["PREREQUISITE_UNAVAILABLE:node"]

    audit = run_checked(["node", "audit-provenance.mjs"], bundle)
    if audit.returncode != 0 or "PASS — A2→A3 provenance" not in audit.stdout:
        errors.append("PROVENANCE_AUDIT_FAILED")

    pack = bundle / "operands" / "warrant-conformance-1.2.0"
    candidate = bundle / "candidate" / "main.mjs"
    candidate_command = shlex.join(["node", str(candidate)])
    run = run_checked([
        sys.executable, str(pack / "run.py"), "--candidate", candidate_command, "--json",
    ], bundle)
    if run.returncode != 0:
        errors.append(f"CONFORMANCE_EXIT:{run.returncode}")
    else:
        try:
            observed = json.loads(run.stdout)
        except json.JSONDecodeError:
            errors.append("CONFORMANCE_REPORT_MALFORMED")
        else:
            expected = record["result"]
            if observed.get("pack_digest") != record["operands"]["pack_manifest_digest"]:
                errors.append("PACK_BINDING_MISMATCH")
            if observed.get("grade_claimed") != expected["grade_claimed"] or observed.get("grade_achieved") != expected["grade_achieved"]:
                errors.append("GRADE_MISMATCH")
            if observed.get("counts") != expected["counts"]:
                errors.append("VECTOR_MISMATCH")
            if (observed.get("negatives_answered"), observed.get("negatives_accepted")) != (
                expected["base_negative_vectors_answered"], expected["base_negative_vectors_accepted"]
            ):
                errors.append("NEGATIVE_VECTOR_MISMATCH")

    if self_check:
        control = run_checked([
            sys.executable, str(pack / "run.py"), "--candidate", candidate_command, "--self-check",
        ], bundle)
        wanted = record["result"]["runner_mutations_detected"]
        if control.returncode != 0:
            errors.append(f"SELF_CHECK_EXIT:{control.returncode}")
        for mutation in wanted:
            if f"DETECTED      mutation={mutation}" not in control.stdout:
                errors.append(f"SELF_CHECK_NOT_DETECTED:{mutation}")
    return errors


def verify(
    bundle: Path,
    *,
    integrity_only: bool = False,
    self_check: bool = True,
    record_path: Path = RECORD,
) -> list[str]:
    try:
        record = load_record(record_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    errors = verify_integrity(bundle, record)
    if not errors and not integrity_only:
        errors.extend(replay(bundle, record, self_check))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--integrity-only", action="store_true")
    parser.add_argument("--skip-self-check", action="store_true")
    args = parser.parse_args()
    errors = verify(args.bundle.resolve(), integrity_only=args.integrity_only, self_check=not args.skip_self_check)
    if errors == ["PREREQUISITE_UNAVAILABLE:node"]:
        print("UNRUN — NEED-002-A3 base evidence needs Node.js")
        return EXIT_UNRUN
    if errors:
        for error in errors:
            print(f"REFUSED  {error}")
        return 1
    mode = "integrity" if args.integrity_only else "integrity + provenance + base replay"
    print(f"CHECKED — NEED-002-BASE ({mode}); settlement remains OPEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
