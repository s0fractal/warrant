#!/usr/bin/env python3
"""Negative controls for the closed NEED-002-A3 evidence bundle."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "needs" / "need-002-a3-base"
SPEC = importlib.util.spec_from_file_location("need002_verify", ROOT / "tools" / "verify_need002_a3.py")
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)

failures = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global failures
    print(f"{'ok ' if condition else 'BAD'}  {label}{f' [{detail}]' if detail else ''}")
    failures += not condition


def errors(bundle: Path) -> list[str]:
    return VERIFY.verify(bundle, integrity_only=True)


def record_errors(bundle: Path, record_path: Path) -> list[str]:
    return VERIFY.verify(bundle, integrity_only=True, record_path=record_path)


check("baseline compact bundle is closed", errors(SOURCE) == [])

with tempfile.TemporaryDirectory(prefix="need002-a3-mutations-") as td:
    base = Path(td)

    original_record = json.loads(VERIFY.RECORD.read_text(encoding="utf-8"))
    widened_record = base / "widened-record.json"
    widened = dict(original_record)
    widened["status"] = "MET_ALL"
    widened_record.write_text(json.dumps(widened), encoding="utf-8")
    observed = record_errors(SOURCE, widened_record)
    check("widened status is not inherited from base evidence", any(item.startswith("RECORD_STATUS") for item in observed), str(observed))

    widened_claim_record = base / "widened-claim-record.json"
    widened_claim = json.loads(json.dumps(original_record))
    widened_claim["claim"] = "A collaborative process produced a conforming JavaScript implementation."
    widened_claim_record.write_text(json.dumps(widened_claim), encoding="utf-8")
    observed = record_errors(SOURCE, widened_claim_record)
    check("claim cannot drop its base-grade boundary", any(item.startswith("RECORD_CLAIM") for item in observed), str(observed))

    weakened_exclusions_record = base / "weakened-exclusions-record.json"
    weakened_exclusions = json.loads(json.dumps(original_record))
    weakened_exclusions["exclusions"].remove("settlement-grade implementation or conformance")
    weakened_exclusions_record.write_text(json.dumps(weakened_exclusions), encoding="utf-8")
    observed = record_errors(SOURCE, weakened_exclusions_record)
    check("settlement exclusion cannot be removed", any(item.startswith("RECORD_EXCLUSIONS") for item in observed), str(observed))

    credited_transport_record = base / "credited-transport-record.json"
    credited_transport = json.loads(json.dumps(original_record))
    credited_transport["transport_module"]["semantic_credit"] = True
    credited_transport_record.write_text(json.dumps(credited_transport), encoding="utf-8")
    observed = record_errors(SOURCE, credited_transport_record)
    check("experiment transport cannot inherit semantic credit", any(item.startswith("RECORD_TRANSPORT") for item in observed), str(observed))

    malformed_transport_record = base / "malformed-transport-record.json"
    malformed_transport = json.loads(json.dumps(original_record))
    malformed_transport["transport_module"] = None
    malformed_transport_record.write_text(json.dumps(malformed_transport), encoding="utf-8")
    observed = record_errors(SOURCE, malformed_transport_record)
    check("malformed transport refuses without crashing", any(item.startswith("RECORD_SCHEMA") for item in observed), str(observed))

    independent_record = base / "independent-record.json"
    independent = json.loads(json.dumps(original_record))
    independent["adjudication"]["status"] = "INDEPENDENTLY_VALIDATED"
    independent["adjudication"]["independent"] = True
    independent_record.write_text(json.dumps(independent), encoding="utf-8")
    observed = record_errors(SOURCE, independent_record)
    check("self-certified evidence cannot relabel itself independent", any(item.startswith("RECORD_ADJUDICATION") for item in observed), str(observed))

    open_record = base / "open-record.json"
    opened = json.loads(json.dumps(original_record))
    opened["operands"]["implementation_sha256"] = "0" * 64
    open_record.write_text(json.dumps(opened), encoding="utf-8")
    observed = record_errors(SOURCE, open_record)
    check("unknown nested record field fails closed", any(item.startswith("RECORD_SCHEMA") for item in observed), str(observed))

    duplicate_record = base / "duplicate-record.json"
    duplicate_record.write_text(
        VERIFY.RECORD.read_text(encoding="utf-8").replace(
            '  "status": "MET_BASE_ONLY",',
            '  "status": "MET_ALL",\n  "status": "MET_BASE_ONLY",',
            1,
        ),
        encoding="utf-8",
    )
    observed = record_errors(SOURCE, duplicate_record)
    check("duplicate record key fails before last-key-wins", "DUPLICATE_JSON_KEY:status" in observed, str(observed))

    missing = base / "missing"
    shutil.copytree(SOURCE, missing)
    (missing / "candidate" / "canon.mjs").unlink()
    observed = errors(missing)
    check("missing operand fails closed", any(item.startswith("CLOSED_SET_MISMATCH") for item in observed), str(observed))

    extra = base / "extra"
    shutil.copytree(SOURCE, extra)
    (extra / "candidate" / "unlisted.mjs").write_text("export const unlisted = true;\n", encoding="utf-8")
    observed = errors(extra)
    check("extra operand fails closed", any(item.startswith("CLOSED_SET_MISMATCH") for item in observed), str(observed))

    linked = base / "linked"
    shutil.copytree(SOURCE, linked)
    target = linked / "candidate" / "canon.mjs"
    target.unlink()
    target.symlink_to(SOURCE / "candidate" / "canon.mjs")
    observed = errors(linked)
    check("external symlink cannot masquerade as a bundled operand", "SYMLINK_NOT_ALLOWED:candidate/canon.mjs" in observed, str(observed))

    linked_manifest = base / "linked-manifest"
    shutil.copytree(SOURCE, linked_manifest)
    manifest_link = linked_manifest / "EVIDENCE-MANIFEST.sha256"
    manifest_link.unlink()
    manifest_link.symlink_to(SOURCE / "EVIDENCE-MANIFEST.sha256")
    observed = errors(linked_manifest)
    check("manifest itself cannot escape the bundle through a symlink", "MANIFEST_SYMLINK_NOT_ALLOWED" in observed, str(observed))

    changed = base / "changed"
    shutil.copytree(SOURCE, changed)
    target = changed / "candidate" / "canon.mjs"
    target.write_bytes(target.read_bytes() + b"\n")
    observed = errors(changed)
    check("changed semantic module fails its operand digest", "OPERAND_DIGEST_MISMATCH:candidate/canon.mjs" in observed, str(observed))
    check("changed semantic module fails its claim binding", "FINAL_MODULE_MISMATCH:candidate/canon.mjs" in observed, str(observed))

    changed_transport = base / "changed-transport"
    shutil.copytree(SOURCE, changed_transport)
    transport_target = changed_transport / "candidate" / "main.mjs"
    transport_target.write_bytes(transport_target.read_bytes() + b"\n")
    observed = errors(changed_transport)
    check("changed transport fails its direct claim binding", "TRANSPORT_MODULE_MISMATCH:candidate/main.mjs" in observed, str(observed))

    reforged = base / "reforged"
    shutil.copytree(SOURCE, reforged)
    target = reforged / "candidate" / "canon.mjs"
    target.write_bytes(target.read_bytes() + b"\n")
    manifest = reforged / "EVIDENCE-MANIFEST.sha256"
    lines = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        if rel == "candidate/canon.mjs":
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    observed = errors(reforged)
    check("coherent local reforge fails the out-of-bundle claim-record pin", "MANIFEST_DIGEST_MISMATCH" in observed, str(observed))

print(f"\n{'FAIL' if failures else 'PASS'} — NEED-002-A3 evidence mutation controls")
raise SystemExit(1 if failures else 0)
