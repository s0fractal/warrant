#!/usr/bin/env python3
"""Recount the countable claims in paper.md against the repository.

Discipline copied from sigma-glyph/tools/paper_claims.py: the expected value is
read OUT OF THE PAPER, never carried here — a checker holding its own copy of
the answer only proves its two copies agree. Exit nonzero on any mismatch.

Run from anywhere; paths resolve relative to this file.

`--ref COMMIT` measures the repository AT THAT COMMIT (a `git archive` of it,
extracted to a temporary directory) instead of the working tree, while the
paper is still read from this directory. That is the binding a deposited paper
needs: paper v1.0.0 was measured at `d83984f` and its numbers were true there;
later commits move the counts (the review census dropped from 92 to 22 files
when the July corpus was retired) without making the frozen paper wrong. CI
runs this mode against the deposited commit, so an edit to `paper.md` that
breaks the binding fails closed, and a rebuild for a new deposit points `--ref`
at its own candidate commit. A commit missing from a shallow clone is fetched
once from `origin` by SHA; if it still is not there, that is a failure, not a
skip.

In `--ref` mode the paper's SOURCE IDENTITY is checked too: `paper.md`,
`references.bib` and `build.sh` in this directory must be byte-identical to
the same files at the commit. The count check alone is a census of selected
numbers -- a retitled paper passes it (Codex, PR #62 review) -- so the
identity check is what makes "edited past its deposited commit" a failure
rather than a hope. `--selftest` proves both refusals fire: a retitled copy
and a miscounted copy each go red against the real deposit commit.
"""
import argparse
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import os
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
# The selftest points this at a mutated COPY of the paper directory; nothing
# else should ever set it, and the repository tree is never the thing mutated.
PAPER_DIR = Path(os.environ.get("CHECK_CLAIMS_PAPER_DIR", str(HERE)))
SOURCE_FILES = ("paper.md", "references.bib", "build.sh")
PAPER = (PAPER_DIR / "paper.md").read_text(encoding="utf-8")

_ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
_ap.add_argument("--ref", metavar="COMMIT",
                 help="measure the repository at this git commit, not the working tree; "
                      "also require paper.md/references.bib/build.sh to equal that commit's")
_ap.add_argument("--selftest", metavar="COMMIT",
                 help="prove the --ref refusals fire against this commit, on mutated copies")
ARGS = _ap.parse_args()


def _selftest(ref):
    me = Path(__file__).resolve()
    def run(paper_dir=None):
        env = dict(os.environ)
        if paper_dir:
            env["CHECK_CLAIMS_PAPER_DIR"] = str(paper_dir)
        return subprocess.run([sys.executable, str(me), "--ref", ref],
                              capture_output=True, text=True, env=env)
    base = run()
    ok = [("baseline: the real paper passes at the deposit commit", base.returncode == 0)]
    with tempfile.TemporaryDirectory(prefix="check_claims-selftest-") as tmp:
        rel = Path(tmp) / "papers" / "x"
        rel.mkdir(parents=True)
        for f in SOURCE_FILES:
            shutil.copy(HERE / f, rel / f)
        text = (rel / "paper.md").read_text(encoding="utf-8")
        (rel / "paper.md").write_text(text.replace("The Reason Runs Again",
                                                    "The Fiction Runs Again", 1), encoding="utf-8")
        r = run(rel)
        ok.append(("retitled copy: refused for source identity",
                   r.returncode != 0 and "SOURCE_IDENTITY" in r.stderr))
        m = re.search(r"holds (\d+) documents", text)
        mutated = text.replace(m.group(0), f"holds {int(m.group(1)) + 1} documents", 1)
        (rel / "paper.md").write_text(mutated, encoding="utf-8")
        r = run(rel)
        ok.append(("miscounted copy: refused for the count AND for identity",
                   r.returncode != 0 and "paper says" in r.stderr and "SOURCE_IDENTITY" in r.stderr))
    for label, good in ok:
        print(("ok    " if good else "FAIL  ") + label)
    verdict = all(g for _, g in ok)
    print("CHECK-CLAIMS-SELFTEST: " + ("ALL PASS" if verdict else "FAILURES PRESENT"))
    return 0 if verdict else 1


if ARGS.selftest:
    sys.exit(_selftest(ARGS.selftest))

MEASURED_AT = "the working tree"
_identity_failures = []
if ARGS.ref:
    def _git(*a, **k):
        return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, **k)
    if _git("cat-file", "-e", f"{ARGS.ref}^{{commit}}").returncode != 0:
        _git("fetch", "--depth=1", "origin", ARGS.ref)
        if _git("cat-file", "-e", f"{ARGS.ref}^{{commit}}").returncode != 0:
            sys.exit(f"check_claims: commit {ARGS.ref} is not in this clone and "
                     "could not be fetched from origin -- refusing to measure something else")
    _tmp = tempfile.TemporaryDirectory(prefix="check_claims-")
    _tar = tarfile.open(fileobj=io.BytesIO(_git("archive", "--format=tar", ARGS.ref, check=True).stdout))
    # The "data" filter (3.12+) rejects links and absolute paths inside the
    # archive; a git archive of our own commit has neither, so on older
    # interpreters the unfiltered extraction is the same operation.
    _kw = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
    _tar.extractall(_tmp.name, **_kw)
    REPO = Path(_tmp.name)
    MEASURED_AT = f"commit {ARGS.ref}"
    # Source identity: the paper being checked must BE the paper at the commit.
    _rel = HERE.relative_to(HERE.parent.parent)
    for _f in SOURCE_FILES:
        _mine = (PAPER_DIR / _f).read_bytes()
        _theirs_path = REPO / _rel / _f
        _theirs = _theirs_path.read_bytes() if _theirs_path.exists() else None
        if _mine != _theirs:
            _identity_failures.append(
                f"SOURCE_IDENTITY: {_f} differs from {ARGS.ref} -- a paper edited past "
                "its deposited commit needs a new deposit candidate and its own --ref")

failures = list(_identity_failures)
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
    "monday": "OpenAI",     # "Monday" ChatGPT persona (manifest)
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
words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
         7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
         12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
         16: "sixteen"}

# Unattributed reviews: inbound documents whose filename prefix is not a known
# vendor label. They are counted in the ledger total but claim no label/vendor,
# so the census must state them explicitly rather than let the total and the
# label count silently disagree. (An unknown label must not vanish.)
inbound_docs = [p for p in docs if "response" not in p.name]
unattributed = [p for p in inbound_docs
                if not (re.match(r"20\d\d-\d\d-([a-z0-9]+)", p.name)
                        and re.match(r"20\d\d-\d\d-([a-z0-9]+)",
                                     p.name).group(1) in VENDOR)]
m = re.search(r"(\w+)\s+unattributed review", PAPER)
if not m or m.group(1) != words.get(len(unattributed)):
    failures.append(f"unattributed reviews: paper says "
                    f"{m.group(1) if m else '<missing>'!r}, "
                    f"measured {len(unattributed)} "
                    f"({sorted(p.name for p in unattributed)})")
else:
    checked.append(f"unattributed reviews: {len(unattributed)}")
m = re.search(r"(\w+)\s+reviewer\s+labels", PAPER)
if not m or m.group(1) != words.get(len(labels)):
    failures.append(f"reviewer labels: paper says "
                    f"{m.group(1) if m else '<missing>'!r}, "
                    f"measured {len(labels)} ({sorted(labels)})")
else:
    checked.append(f"reviewer labels: {len(labels)}")
vendors = {VENDOR[l] for l in labels}
m = re.search(r"(\w+) model\s+vendors", PAPER)
if not m or m.group(1) != words.get(len(vendors)):
    failures.append(f"vendors: paper says "
                    f"{m.group(1) if m else '<missing>'!r}, "
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
if ARGS.ref:
    print(f"\nsource identity: {', '.join(SOURCE_FILES)} equal their copies at {ARGS.ref}")
print(f"\n{len(checked)} countable claims verified against {MEASURED_AT}; "
      f"{len(UNCHECKED)} claim classes UNCHECKED (listed above). "
      "This is not a statement that every number in the paper was recomputed.")
