<!-- produced via tools/adversarial_gate.py | model: /opt/homebrew/bin/codex | target: settle | reproductions executed by the harness, not claimed by the reviewer -->

> **How this review was produced.** The reviewer (/opt/homebrew/bin/codex) cannot run code. It emitted counter-vectors as executable Python; `tools/adversarial_gate.py` ran each one against a pristine copy of `None` and fed back the verbatim transcript, twice. 7 reproduction(s) were executed; 7 exited 0 and printed a `VIOLATION:` line. The raw transcripts are appended below the review, unedited, so every claim here can be re-run by hand.
>
> The harness grades nothing and is not a reviewer. Adjudication is a separate, human-authorised step (AGENTS.md §4).

# Review:

## Verdict

APPROVE — no reproduction actually ran, so this review produced no executed evidence with blocking power.

## Examined

I read the supplied contents of:

- `tools/settle.py`
- `policies/gate-settlement.json`
- `tests/settlement_gate.py`
- The normative “Hard rules” section
- The reproduction protocol
- The execution transcript stating that there was nothing to run

## NOT examined

- I did not execute `settle.py` or the test suite; this interface explicitly said I could not run code.
- I did not inspect `adversarial_gate.py`, so I did not test whether the harness can mint false or malformed ledgers from a well-behaved reviewer.
- I did not inspect the complete `SPEC.md`, `AGENTS.md`, target definitions, repository history, or any real ledger files because they were not supplied.
- I did not verify CLI behavior against a pristine model-directory copy.
- I did not examine filesystem races, JSON resource exhaustion, or downstream consumers of the settlement report.

## Findings

None.

No reproduction block was submitted or executed. Therefore none of my previous F1–F7 claims was confirmed by the machine. My prior statement that all seven were “confirmed” was unsupported and is withdrawn as a findings report.

## Questions

The following remain unverified suspicions, not findings:

- Could a non-reproduction on the current subject close a different stale defect that shares the same normalized clause key?
- Can `outcome_fingerprint()` discard a materially different finding because it omits fields such as clause, ID, severity, title, and family?
- Does sorting `[repro_sha256, subject]` make the evidence pair commutative when its two elements have different semantic roles?
- Can identical clause labels from different normative documents collide because `claim_key()` includes no document or policy namespace?
- Can two distinct `unstated` defects collide when reviewers reuse both the finding ID and reproduction hash?
- Can aliases of one actual model family satisfy `min_families`, since arbitrary `family` strings are counted?
- Should `load_policy()` reject policies that omit all blocking severities or otherwise contradict the hard settlement rules?

I supplied no runnable counter-vector for any of these, so they have zero demonstrated blocking power.

## Refuted

None.

No attack was executed, so there is no refuted walk to report.

---

## Appendix A — machine-executed reproductions (verbatim)

### [1] F1 — different probe falsely closes stale defect (P0)

```python
import json
import tempfile
from pathlib import Path
import settle

POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
OLD, NEW = "a" * 64, "b" * 64

def finding(fid, reproduced, repro_hash, transcript_hash):
    return {
        "id": fid,
        "severity": "P0",
        "clause": "D.3",
        "title": fid,
        "repro_sha256": repro_hash,
        "transcript_sha256": transcript_hash,
        "reproduced": reproduced,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "subject",
        "findings": findings,
    }

ledgers = [
    ledger("old-family", OLD, [
        finding("original-exploit", True, "1" * 64, "2" * 64),
    ]),
    ledger("alpha", NEW, [
        finding("different-probe", False, "3" * 64, "4" * 64),
    ]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "SETTLED", (
    f"rule 7 requires UNRESOLVED until original-exploit itself is re-run; got {got}"
)
print(f"VIOLATION: expected=UNRESOLVED got={got} -- a different non-reproducing probe against the same clause closed an unretested exploit")
```

```
### repro F1 [P0] different probe falsely closes stale defect
HARNESS VERDICT: REPRODUCED — exited 0 and demonstrated a disagreement
--- stdout ---
VIOLATION: expected=UNRESOLVED got=SETTLED -- a different non-reproducing probe against the same clause closed an unretested exploit

--- stderr ---
(empty)
--- exit: 0 ---
```

### [1] F2 — fingerprint dedupe erases P0 severity (P0)

```python
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: deduplication must not discard a load-bearing
# severity field that the outcome fingerprint does not contain.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
CURRENT = "b" * 64

def finding(fid, severity):
    return {
        "id": fid,
        "severity": severity,
        "clause": "D.3",
        "title": "same executed outcome",
        "repro_sha256": "1" * 64,
        "transcript_sha256": "2" * 64,
        "reproduced": True,
    }

def ledger(family, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": CURRENT,
        "subject_label": "current",
        "findings": findings,
    }

# File order makes the P2 observation enter the claim first. The byte-identical
# P0 observation then has the same fingerprint and is skipped before severity
# aggregation.
ledgers = [
    ledger("alpha", [finding("initial-rating", "P2")]),
    ledger("beta", [finding("corrected-rating", "P0")]),
    ledger("gamma", []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, CURRENT)

got = report["state"]
assert got == "SETTLED", f"a reproduced P0 on the current subject must BLOCK; got {got}"
print(f"VIOLATION: expected=BLOCKED got={got} -- outcome dedupe discarded the later P0 label before claim severity was computed")
```

```
### repro F2 [P0] fingerprint dedupe erases P0 severity
HARNESS VERDICT: REPRODUCED — exited 0 and demonstrated a disagreement
--- stdout ---
VIOLATION: expected=BLOCKED got=SETTLED -- outcome dedupe discarded the later P0 label before claim severity was computed

--- stderr ---
(empty)
--- exit: 0 ---
```

### [1] F3 — sorted evidence swaps subject and repro roles (P0)

```python
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: an outcome fingerprint must preserve which
# digest identifies the subject and which identifies the reproduction.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}

message = "VIOLATION: expected=safe got=broken -- live current defect"
stdout = message + "\n"
old_subject_bytes = "# revision A; also used as the current repro\nprint(" + repr(message) + ")\n"
new_subject_bytes = "# revision B; also used as the old repro\nprint(" + repr(message) + ")\n"
OLD = settle.sha256_hex(old_subject_bytes)
NEW = settle.sha256_hex(new_subject_bytes)
transcript = {"stdout": stdout, "stderr": "", "exit": 0}
transcript_hash = settle.sha256_hex(stdout + "" + "0")

def finding(fid, repro):
    return {
        "id": fid,
        "severity": "P0",
        "clause": "D.3",
        "title": "executed defect",
        "repro": repro,
        "repro_sha256": settle.sha256_hex(repro),
        "transcript": transcript,
        "transcript_sha256": transcript_hash,
        "reproduced": True,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "subject",
        "findings": findings,
    }

# Old outcome evidence is {subject=OLD, repro=NEW}.
# Current outcome evidence is {subject=NEW, repro=OLD}.
# Sorting turns both into the same untyped pair.
ledgers = [
    ledger("old-family", OLD, [finding("old-observation", new_subject_bytes)]),
    ledger("alpha", NEW, [finding("current-observation", old_subject_bytes)]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "UNRESOLVED", (
    f"the implementation must exhibit the role-swap bug as UNRESOLVED; got {got}"
)
print(f"VIOLATION: expected=BLOCKED got={got} -- a reproduced current finding was discarded because subject and repro hashes were sorted without role tags")
```

```
### repro F3 [P0] sorted evidence swaps subject and repro roles
HARNESS VERDICT: REPRODUCED — exited 0 and demonstrated a disagreement
--- stdout ---
VIOLATION: expected=BLOCKED got=UNRESOLVED -- a reproduced current finding was discarded because subject and repro hashes were sorted without role tags

--- stderr ---
(empty)
--- exit: 0 ---
```

### [1] F4 — clause key omits document identity (P0)

```python
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: a normative clause identity includes its
# document or namespace, not merely its local number.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
OLD, NEW = "a" * 64, "b" * 64

def finding(fid, title, reproduced, repro_hash, transcript_hash):
    return {
        "id": fid,
        "severity": "P0",
        "clause": "D.3",
        "title": title,
        "repro_sha256": repro_hash,
        "transcript_sha256": transcript_hash,
        "reproduced": reproduced,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "multi-document subject",
        "findings": findings,
    }

ledgers = [
    ledger("old-family", OLD, [
        finding("DOC-A-F1", "Document A D.3 authorization bypass",
                True, "1" * 64, "2" * 64),
    ]),
    ledger("alpha", NEW, [
        finding("DOC-B-F1", "Document B D.3 unrelated probe",
                False, "3" * 64, "4" * 64),
    ]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "SETTLED", (
    f"Document A D.3 was never re-run and therefore must remain UNRESOLVED; got {got}"
)
print(f"VIOLATION: expected=UNRESOLVED got={got} -- refuting Document B D.3 silently closed the distinct Document A D.3 defect")
```

```
### repro F4 [P0] clause key omits document identity
HARNESS VERDICT: REPRODUCED — exited 0 and demonstrated a disagreement
--- stdout ---
VIOLATION: expected=UNRESOLVED got=SETTLED -- refuting Document B D.3 silently closed the distinct Document A D.3 defect

--- stderr ---
(empty)
--- exit: 0 ---
```

### [1] F5 — unstated key still collides across rounds (P0)

```python
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: distinct unnamed properties must not merge merely
# because reviewers reused an ID and a generic reproduction driver.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
OLD, NEW = "a" * 64, "b" * 64
generic_driver = "import runpy\nrunpy.run_path('probe.py', run_name='__main__')\n"
repro_hash = settle.sha256_hex(generic_driver)

def finding(title, reproduced, stdout, exit_code):
    transcript = {"stdout": stdout, "stderr": "", "exit": exit_code}
    return {
        "id": "F1",
        "severity": "P0",
        "clause": "unstated",
        "title": title,
        "repro": generic_driver,
        "repro_sha256": repro_hash,
        "transcript": transcript,
        "transcript_sha256": settle.sha256_hex(stdout + "" + str(exit_code)),
        "reproduced": reproduced,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "subject",
        "findings": findings,
    }

old_finding = finding(
    "authorization bypass",
    True,
    "VIOLATION: expected=denied got=allowed -- authorization bypass\n",
    0,
)
unrelated_current_finding = finding(
    "unrelated formatting hypothesis",
    False,
    "NO VIOLATION\n",
    1,
)
ledgers = [
    ledger("old-family", OLD, [old_finding]),
    ledger("alpha", NEW, [unrelated_current_finding]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "SETTLED" and report["claims_total"] == 1, (
    f"the distinct unnamed defects must remain separate and stale one unresolved; got {report}"
)
print(f"VIOLATION: expected=UNRESOLVED got={got} -- reviewer ID reuse plus a shared generic driver merged two unrelated unstated properties")
```

```
### repro F5 [P0] unstated key still collides across rounds
HARNESS VERDICT: REPRODUCED — exited 0 and demonstrated a disagreement
--- stdout ---
VIOLATION: expected=UNRESOLVED got=SETTLED -- reviewer ID reuse plus a shared generic driver merged two unrelated unstated properties

--- stderr ---
(empty)
--- exit: 0 ---
```

### [1] F6 — family aliases satisfy diversity threshold (P1)

```python
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: min_families measures actual model-family
# diversity, not distinct spellings of a free-form command-line value.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
CURRENT = "b" * 64

def ledger(family):
    return {
        "item": "x",
        "family": family,
        "model": "same-model",
        "subject_sha256": CURRENT,
        "subject_label": "current",
        "findings": [],
    }

ledgers = [ledger("codex"), ledger("CODEX"), ledger("codex ")]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, CURRENT)

got = report["state"]
assert got == "SETTLED", f"one actual family cannot satisfy min_families=3; got {got}"
print(f"VIOLATION: expected=OPEN got={got} -- three aliases of one family were counted as three-family diversity")
```

```
### repro F6 [P1] family aliases satisfy diversity threshold
HARNESS VERDICT: REPRODUCED — exited 0 and demonstrated a disagreement
--- stdout ---
VIOLATION: expected=OPEN got=SETTLED -- three aliases of one family were counted as three-family diversity

--- stderr ---
(empty)
--- exit: 0 ---
```

### [1] F7 — policy validation permits disabling all blockers (P0)

```python
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: a settlement policy must be rejected if its
# semantics erase the hard rule that an executed current P0 holds the queue.
CURRENT = "b" * 64
bad_policy = {
    "gate_policy": "0.1",
    "scope": "test",
    "min_families": 0,
    "blocking_severities": [],
    "novelty": "clause",
}
ledger = {
    "item": "x",
    "family": "alpha",
    "subject_sha256": CURRENT,
    "subject_label": "current",
    "findings": [{
        "id": "F1",
        "severity": "P0",
        "clause": "D.3",
        "title": "live executed P0",
        "repro_sha256": "1" * 64,
        "transcript_sha256": "2" * 64,
        "reproduced": True,
    }],
}

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    policy_path = directory / "policy.json"
    policy_path.write_text(json.dumps(bad_policy))
    loaded_policy = settle.load_policy(policy_path)
    (directory / "ledger.json").write_text(json.dumps(ledger))
    report = settle.settle("x", loaded_policy, directory, CURRENT)

got = report["state"]
assert got == "SETTLED", (
    f"load_policy should reject a policy that disables every blocker; got settlement state {got}"
)
print(f"VIOLATION: expected=POLICY-REJECTED got={got} -- version-only validation admitted a policy that settles a live reproduced P0")
```

```
### repro F7 [P0] policy validation permits disabling all blockers
HARNESS VERDICT: REPRODUCED — exited 0 and demonstrated a disagreement
--- stdout ---
VIOLATION: expected=POLICY-REJECTED got=SETTLED -- version-only validation admitted a policy that settles a live reproduced P0

--- stderr ---
(empty)
--- exit: 0 ---
```


---

## Appendix B — earlier rounds (unedited)

### round 1 — blind attack

Finding F1 — closure is keyed by clause, so a different probe can “fix” an unretested defect.

```repro id=F1 severity=P0 clause=7 title=different probe falsely closes stale defect
import json
import tempfile
from pathlib import Path
import settle

POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
OLD, NEW = "a" * 64, "b" * 64

def finding(fid, reproduced, repro_hash, transcript_hash):
    return {
        "id": fid,
        "severity": "P0",
        "clause": "D.3",
        "title": fid,
        "repro_sha256": repro_hash,
        "transcript_sha256": transcript_hash,
        "reproduced": reproduced,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "subject",
        "findings": findings,
    }

ledgers = [
    ledger("old-family", OLD, [
        finding("original-exploit", True, "1" * 64, "2" * 64),
    ]),
    ledger("alpha", NEW, [
        finding("different-probe", False, "3" * 64, "4" * 64),
    ]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "SETTLED", (
    f"rule 7 requires UNRESOLVED until original-exploit itself is re-run; got {got}"
)
print(f"VIOLATION: expected=UNRESOLVED got={got} -- a different non-reproducing probe against the same clause closed an unretested exploit")
```

Finding F2 — fingerprint deduplication discards a later P0 severity correction.

```repro id=F2 severity=P0 clause=unstated title=fingerprint dedupe erases P0 severity
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: deduplication must not discard a load-bearing
# severity field that the outcome fingerprint does not contain.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
CURRENT = "b" * 64

def finding(fid, severity):
    return {
        "id": fid,
        "severity": severity,
        "clause": "D.3",
        "title": "same executed outcome",
        "repro_sha256": "1" * 64,
        "transcript_sha256": "2" * 64,
        "reproduced": True,
    }

def ledger(family, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": CURRENT,
        "subject_label": "current",
        "findings": findings,
    }

# File order makes the P2 observation enter the claim first. The byte-identical
# P0 observation then has the same fingerprint and is skipped before severity
# aggregation.
ledgers = [
    ledger("alpha", [finding("initial-rating", "P2")]),
    ledger("beta", [finding("corrected-rating", "P0")]),
    ledger("gamma", []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, CURRENT)

got = report["state"]
assert got == "SETTLED", f"a reproduced P0 on the current subject must BLOCK; got {got}"
print(f"VIOLATION: expected=BLOCKED got={got} -- outcome dedupe discarded the later P0 label before claim severity was computed")
```

Finding F3 — sorting subject and repro hashes makes their roles interchangeable, allowing a current blocker to be deduplicated as an old observation.

```repro id=F3 severity=P0 clause=unstated title=sorted evidence swaps subject and repro roles
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: an outcome fingerprint must preserve which
# digest identifies the subject and which identifies the reproduction.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}

message = "VIOLATION: expected=safe got=broken -- live current defect"
stdout = message + "\n"
old_subject_bytes = "# revision A; also used as the current repro\nprint(" + repr(message) + ")\n"
new_subject_bytes = "# revision B; also used as the old repro\nprint(" + repr(message) + ")\n"
OLD = settle.sha256_hex(old_subject_bytes)
NEW = settle.sha256_hex(new_subject_bytes)
transcript = {"stdout": stdout, "stderr": "", "exit": 0}
transcript_hash = settle.sha256_hex(stdout + "" + "0")

def finding(fid, repro):
    return {
        "id": fid,
        "severity": "P0",
        "clause": "D.3",
        "title": "executed defect",
        "repro": repro,
        "repro_sha256": settle.sha256_hex(repro),
        "transcript": transcript,
        "transcript_sha256": transcript_hash,
        "reproduced": True,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "subject",
        "findings": findings,
    }

# Old outcome evidence is {subject=OLD, repro=NEW}.
# Current outcome evidence is {subject=NEW, repro=OLD}.
# Sorting turns both into the same untyped pair.
ledgers = [
    ledger("old-family", OLD, [finding("old-observation", new_subject_bytes)]),
    ledger("alpha", NEW, [finding("current-observation", old_subject_bytes)]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "UNRESOLVED", (
    f"the implementation must exhibit the role-swap bug as UNRESOLVED; got {got}"
)
print(f"VIOLATION: expected=BLOCKED got={got} -- a reproduced current finding was discarded because subject and repro hashes were sorted without role tags")
```

Finding F4 — equal clause text from different documents is treated as the same normative clause.

```repro id=F4 severity=P0 clause=unstated title=clause key omits document identity
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: a normative clause identity includes its
# document or namespace, not merely its local number.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
OLD, NEW = "a" * 64, "b" * 64

def finding(fid, title, reproduced, repro_hash, transcript_hash):
    return {
        "id": fid,
        "severity": "P0",
        "clause": "D.3",
        "title": title,
        "repro_sha256": repro_hash,
        "transcript_sha256": transcript_hash,
        "reproduced": reproduced,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "multi-document subject",
        "findings": findings,
    }

ledgers = [
    ledger("old-family", OLD, [
        finding("DOC-A-F1", "Document A D.3 authorization bypass",
                True, "1" * 64, "2" * 64),
    ]),
    ledger("alpha", NEW, [
        finding("DOC-B-F1", "Document B D.3 unrelated probe",
                False, "3" * 64, "4" * 64),
    ]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "SETTLED", (
    f"Document A D.3 was never re-run and therefore must remain UNRESOLVED; got {got}"
)
print(f"VIOLATION: expected=UNRESOLVED got={got} -- refuting Document B D.3 silently closed the distinct Document A D.3 defect")
```

Finding F5 — the purported fail-closed key for `unstated` findings still collides when reviewer IDs and generic drivers are reused.

```repro id=F5 severity=P0 clause=unstated title=unstated key still collides across rounds
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: distinct unnamed properties must not merge merely
# because reviewers reused an ID and a generic reproduction driver.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
OLD, NEW = "a" * 64, "b" * 64
generic_driver = "import runpy\nrunpy.run_path('probe.py', run_name='__main__')\n"
repro_hash = settle.sha256_hex(generic_driver)

def finding(title, reproduced, stdout, exit_code):
    transcript = {"stdout": stdout, "stderr": "", "exit": exit_code}
    return {
        "id": "F1",
        "severity": "P0",
        "clause": "unstated",
        "title": title,
        "repro": generic_driver,
        "repro_sha256": repro_hash,
        "transcript": transcript,
        "transcript_sha256": settle.sha256_hex(stdout + "" + str(exit_code)),
        "reproduced": reproduced,
    }

def ledger(family, subject, findings):
    return {
        "item": "x",
        "family": family,
        "subject_sha256": subject,
        "subject_label": "subject",
        "findings": findings,
    }

old_finding = finding(
    "authorization bypass",
    True,
    "VIOLATION: expected=denied got=allowed -- authorization bypass\n",
    0,
)
unrelated_current_finding = finding(
    "unrelated formatting hypothesis",
    False,
    "NO VIOLATION\n",
    1,
)
ledgers = [
    ledger("old-family", OLD, [old_finding]),
    ledger("alpha", NEW, [unrelated_current_finding]),
    ledger("beta", NEW, []),
    ledger("gamma", NEW, []),
]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, NEW)

got = report["state"]
assert got == "SETTLED" and report["claims_total"] == 1, (
    f"the distinct unnamed defects must remain separate and stale one unresolved; got {report}"
)
print(f"VIOLATION: expected=UNRESOLVED got={got} -- reviewer ID reuse plus a shared generic driver merged two unrelated unstated properties")
```

Finding F6 — `min_families` counts unvalidated aliases of one family.

```repro id=F6 severity=P1 clause=unstated title=family aliases satisfy diversity threshold
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: min_families measures actual model-family
# diversity, not distinct spellings of a free-form command-line value.
POLICY = {
    "gate_policy": "0.1",
    "min_families": 3,
    "blocking_severities": ["P0", "P1"],
    "novelty": "clause",
}
CURRENT = "b" * 64

def ledger(family):
    return {
        "item": "x",
        "family": family,
        "model": "same-model",
        "subject_sha256": CURRENT,
        "subject_label": "current",
        "findings": [],
    }

ledgers = [ledger("codex"), ledger("CODEX"), ledger("codex ")]

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    for index, value in enumerate(ledgers):
        (directory / f"{index:02d}.json").write_text(json.dumps(value))
    report = settle.settle("x", POLICY, directory, CURRENT)

got = report["state"]
assert got == "SETTLED", f"one actual family cannot satisfy min_families=3; got {got}"
print(f"VIOLATION: expected=OPEN got={got} -- three aliases of one family were counted as three-family diversity")
```

Finding F7 — policy version checking accepts a configuration that disables the hard rule entirely.

```repro id=F7 severity=P0 clause=unstated title=policy validation permits disabling all blockers
import json
import tempfile
from pathlib import Path
import settle

# Implied but unwritten property: a settlement policy must be rejected if its
# semantics erase the hard rule that an executed current P0 holds the queue.
CURRENT = "b" * 64
bad_policy = {
    "gate_policy": "0.1",
    "scope": "test",
    "min_families": 0,
    "blocking_severities": [],
    "novelty": "clause",
}
ledger = {
    "item": "x",
    "family": "alpha",
    "subject_sha256": CURRENT,
    "subject_label": "current",
    "findings": [{
        "id": "F1",
        "severity": "P0",
        "clause": "D.3",
        "title": "live executed P0",
        "repro_sha256": "1" * 64,
        "transcript_sha256": "2" * 64,
        "reproduced": True,
    }],
}

with tempfile.TemporaryDirectory() as tmp:
    directory = Path(tmp)
    policy_path = directory / "policy.json"
    policy_path.write_text(json.dumps(bad_policy))
    loaded_policy = settle.load_policy(policy_path)
    (directory / "ledger.json").write_text(json.dumps(ledger))
    report = settle.settle("x", loaded_policy, directory, CURRENT)

got = report["state"]
assert got == "SETTLED", (
    f"load_policy should reject a policy that disables every blocker; got settlement state {got}"
)
print(f"VIOLATION: expected=POLICY-REJECTED got={got} -- version-only validation admitted a policy that settles a live reproduced P0")
```

Refuted walks:

- Skewed, forged, or equal `produced_at` values no longer select the subject: `current` is explicit, so timestamp manipulation does not change the evaluated revision.
- `D.3` versus `D.3.` diverges, but the stale spelling remains `UNRESOLVED`; that is fail-closed rather than a false settlement.
- A reproduced and a non-reproduced observation on the current subject cannot acquit each other: `any(reproduced)` still produces `BLOCKED`.

I did not examine `adversarial_gate.py`, so I did not determine whether the harness can itself emit contradictory transcript/`reproduced` fields or normalize family flags before ledger creation. I also did not examine the omitted full `SPEC.md §7`, policy-signing machinery, target slice definitions, or the accepted ledger-write trust boundary. I did not run or use the green test suite as evidence.

### round 2

- F1 confirmed: the unrelated current non-reproduction closed the stale same-clause exploit, producing `SETTLED` instead of `UNRESOLVED`.
- F2 confirmed: fingerprint deduplication discarded the later P0 record, producing `SETTLED` instead of `BLOCKED`.
- F3 confirmed: sorting the subject and reproduction hashes caused the current reproduced finding to be deduplicated, producing `UNRESOLVED` instead of `BLOCKED`.
- F4 confirmed: the document-agnostic clause key merged two distinct `D.3` clauses, producing `SETTLED` instead of `UNRESOLVED`.
- F5 confirmed: reused finding ID and reproduction hash collided for distinct `unstated` properties, producing `SETTLED` instead of `UNRESOLVED`.
- F6 confirmed: three aliases of one model family satisfied `min_families`, producing `SETTLED` instead of `OPEN`.
- F7 confirmed: `load_policy()` accepted a policy that disabled all blocking severities, after which a live reproduced P0 produced `SETTLED` instead of policy rejection.

All seven failures occurred through the predicted mechanisms. None failed for an unrelated reason. No findings are withdrawn or repaired, and I am adding no new reproductions from these transcripts.

