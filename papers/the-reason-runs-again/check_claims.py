#!/usr/bin/env python3
"""Recount the countable claims in paper.md against the repository.

Discipline copied from sigma-glyph/tools/paper_claims.py: the expected value is
read OUT OF THE PAPER, never carried here — a checker holding its own copy of
the answer only proves its two copies agree. Exit nonzero on any mismatch.

Run from anywhere; paths resolve relative to this file.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PAPER = (HERE / "paper.md").read_text(encoding="utf-8")

failures = []
checked = []


def claim(pattern, actual, label):
    """Find `pattern` (one int group) in the paper; compare to `actual`."""
    m = re.search(pattern, PAPER)
    if not m:
        failures.append(f"{label}: pattern not found in paper.md: {pattern!r}")
        return
    stated = int(m.group(1))
    if stated != actual:
        failures.append(f"{label}: paper says {stated}, repository measures {actual}")
    else:
        checked.append(f"{label}: {actual}")


# --- conformance pack: total vectors across vector files (index.json is a map)
total = 0
for f in sorted((REPO / "conformance" / "vectors").glob("*.json")):
    if f.name == "index.json":
        continue
    d = json.loads(f.read_text(encoding="utf-8"))
    for key in ("cases", "vectors"):
        if isinstance(d, dict) and key in d:
            total += len(d[key])
            break
    else:
        if isinstance(d, list):
            total += len(d)
claim(r"(\d+)-vector conformance pack", total, "conformance pack vectors")
claim(r"(\d+)\s+vectors in a runner-driven pack", total, "pack vectors (abstract)")

# grade split: ski-run and verify-store-settlement are the settlement-only files
settlement_only = 0
for name in ("ski-run.json", "verify-store-settlement.json"):
    d = json.loads((REPO / "conformance" / "vectors" / name).read_text(encoding="utf-8"))
    settlement_only += len(d.get("vectors") or d.get("cases"))
claim(r"(\d+)\s+base-grade", total - settlement_only, "base-grade vectors")
claim(r"(\d+) settlement-grade", settlement_only, "settlement-grade vectors")

# the pack's canon file = the examples battery + the spec-table record vectors
pack_canon = json.loads(
    (REPO / "conformance" / "vectors" / "canon.json").read_text(encoding="utf-8"))
claim(r"its (\d+) canonicalization vectors", len(pack_canon["vectors"]),
      "pack canon vectors")

# --- canonicalization battery (examples/canon-vectors.json)
canon = json.loads((REPO / "examples" / "canon-vectors.json").read_text(encoding="utf-8"))
claim(r"a (\d+)-case canonicalization battery", len(canon["cases"]), "canon battery")

# --- negative batteries
neg = json.loads((REPO / "examples" / "conformance-negatives.json").read_text(encoding="utf-8"))
claim(r"(\d+) weak\s+or non-canonical Ed25519 public keys",
      len(neg["weak_ed25519_pubkeys"]), "weak-key battery")
claim(r"(\d+)\s+bodies for which validation must return an error",
      len(neg["schema_invalid"]), "schema-invalid battery")
claim(r"(\d+) weak\s+Ed25519 keys that must\s+fail",
      len(neg["weak_ed25519_pubkeys"]), "weak-key battery (abstract)")

# --- signature vectors
sig = json.loads((REPO / "examples" / "signature-vectors.json").read_text(encoding="utf-8"))
claim(r"(\d+) signature\s+constructions that must \*\*not\*\* verify",
      len(sig["reject"]), "signature reject battery")

# --- review ledger
docs = [p for p in (REPO / "reviews").glob("*.md") if p.name != "README.md"]
responses = [p for p in docs if "response" in p.name]
claim(r"holds (\d+) documents", len(docs), "review-ledger documents")
claim(r"(\d+) inbound reviews and gates", len(docs) - len(responses), "inbound reviews")
claim(r"plus (\d+) written\s+responses", len(responses), "responses")
claim(r"review ledger of (\d+) documents", len(docs), "review ledger (abstract)")

# --- reviewer identities and vendors (mapping is a judgment; it lives here,
#     visibly, rather than being asserted without a basis)
VENDOR = {
    "codex": "OpenAI", "gptoss120b": "OpenAI", "chatgpt": "OpenAI",
    "annaglova": "OpenAI",  # GitHub account; ChatGPT-authored gate (manifest)
    "gpt56sol": "OpenAI",   # GPT-5.6 Sol via ChatGPT (manifest)
    "gemini": "Google", "gemini31pro": "Google", "antigravity": "Google",
    "deepseek": "DeepSeek",
    "kimi": "Moonshot",
    "opus48": "Anthropic",
    "qwen": "Alibaba", "qwen3": "Alibaba",
}
labels = set()
for p in docs:
    m = re.match(r"20\d\d-\d\d-([a-z0-9]+)", p.name)
    if m and m.group(1) in VENDOR:
        labels.add(m.group(1))
words = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
         8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
         13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen"}
m = re.search(r"(\w+) reviewer labels", PAPER)
if not m or m.group(1) != words.get(len(labels)):
    failures.append(f"reviewer labels: paper says "
                    f"{m.group(1) if m else '<missing>'!r}, "
                    f"measured {len(labels)} ({sorted(labels)})")
else:
    checked.append(f"reviewer labels: {len(labels)}")
vendors = {VENDOR[l] for l in labels}
m = re.search(r"(\w+) model\s+vendors", PAPER)
if m and m.group(1) != words.get(len(vendors)):
    failures.append(f"vendors: paper says {m.group(1)!r}, "
                    f"measured {len(vendors)} ({sorted(vendors)})")
else:
    checked.append(f"model vendors: {len(vendors)}")

# --- default re-execution budget: the paper's 10^8 must match SPEC's number
spec = (REPO / "SPEC.md").read_text(encoding="utf-8")
if "default to 100,000,000 ATP" not in spec:
    failures.append("SPEC.md no longer states the 100,000,000 ATP default "
                    "the paper renders as 10^8")
else:
    checked.append("default ATP budget: 100,000,000 (SPEC 3.1)")

# --- the word count the papers/ index states for this paper
index = (HERE.parent / "README.md").read_text(encoding="utf-8")
m = re.search(r"the-reason-runs-again/\)\s*\|\s*([\d\s ]+?)\s*\|", index)
words_actual = len(re.findall(r"\S+", PAPER.split("---", 2)[2]))
if m:
    stated = int(re.sub(r"[\s ]", "", m.group(1)))
    if stated != words_actual:
        failures.append(f"word count: papers/README.md says {stated}, "
                        f"paper.md measures {words_actual}")
    else:
        checked.append(f"word count (papers/README.md): {words_actual}")
else:
    failures.append("word count row for this paper not found in papers/README.md")

# --- report
for line in checked:
    print(f"  ok  {line}")

# The claims this script deliberately does NOT recompute. Named as data, not
# prose, and COUNTED — because a checker that says "all verified" while quietly
# excluding a list is the very defect the sibling guard paper is about (a
# control whose scope is chosen by the thing it controls). Qwen round-3 gate,
# 2026-08-27: the old final line "all countable claims verified" overstated,
# so the summary now reports verified AND unchecked, and never claims "all".
UNCHECKED = [
    '"43/43" canon differential and "472 cases incl. 20 mixed-torsion": '
    "measurements of harness RUNS (ARCHITECT.md progress log). Recomputing "
    "means running the harnesses — python3 tools/check.py does; this script "
    "must not half-do it.",
    "the five SPEC §8 hashes: the paper cites their existence, not values; "
    "the conformance suites pin the values.",
    "prose claims (flag-day rationale, threat-model rows): not countable.",
    "external citation status (e.g. the VAC draft title / 2026-08-29 expiry): "
    "needs the network; this build stays reproducible offline. Follow-up: a "
    "check_sources.py in CI (chatgpt-web review response).",
]
print("\nNOT checked here (excluded by design, counted, never called verified):")
for u in UNCHECKED:
    print(f"  --  {u}")

if failures:
    print("\nFAILED:", file=sys.stderr)
    for f in failures:
        print(f"  {f}", file=sys.stderr)
    sys.exit(1)
print(f"\n{len(checked)} countable claims verified against {REPO}; "
      f"{len(UNCHECKED)} claim classes UNCHECKED (listed above). "
      "This is not a statement that every number in the paper was recomputed.")
