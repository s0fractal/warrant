#!/usr/bin/env python3
"""OpenRouter review backend — for reviewer models without an agentic harness.

Unlike agy/codex, an OpenRouter model cannot run the test suite itself, so the
maintainer runs the gates and ships their fresh transcripts inside a briefing
pack. Independence is preserved ARCHITECTURALLY via two passes:

  pass 1: protocol + primary sources + gate transcripts, NO prior reviews
          -> the model forms its own findings blind
  pass 2: pass-1 findings + prior reviews -> final review with an explicit
          agree/disagree/new section

Usage:
    OPENROUTER_MODEL="<vendor/model>" python3 tools/or_review.py <outfile.md> [focus...]
    python3 tools/or_review.py --list          # show available model ids

Key: $OPENROUTER_API_KEY or ~/.config/openrouter/key (single line, chmod 600).
"""
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://openrouter.ai/api/v1"

PRIMARY_SOURCES = [
    "SPEC.md",
    "proposals/GOV-001-settlement-at-scale.md",
    "README.md",
]
PRIOR_REVIEWS_GLOB = ["reviews/2026-07-codex-gov001-gate.md",
                      "reviews/2026-07-codex-gov001-gate-response.md",
                      "reviews/2026-07-gemini-gov001-gate.md",
                      "reviews/2026-07-gemini-gov001-gate-response.md"]
GATES = [
    ["python3", "impl/warrant.py", "selftest"],
    ["python3", "impl/warrant.py", "conformance"],
    ["python3", "tests/differential.py"],
    ["python3", "tests/negative.py"],
]


def key():
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k:
        p = Path.home() / ".config/openrouter/key"
        if p.exists():
            k = p.read_text().strip()
    if not k:
        sys.exit("no OpenRouter key: set OPENROUTER_API_KEY or write ~/.config/openrouter/key")
    return k


def call(model, messages, max_tokens=16000):
    req = urllib.request.Request(
        f"{API}/chat/completions",
        data=json.dumps({"model": model, "messages": messages,
                         "max_tokens": max_tokens}).encode(),
        headers={"Authorization": f"Bearer {key()}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://github.com/s0fractal/warrant",
                 "X-Title": "warrant GOV review"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        out = json.load(r)
    if "error" in out:
        sys.exit(f"openrouter error: {out['error']}")
    choice = out["choices"][0]
    msg = choice["message"]
    # some models (reasoning variants, truncated runs) return content=None
    content = msg.get("content") or msg.get("reasoning")
    if not content:
        sys.exit("openrouter returned empty content; finish_reason="
                 f"{choice.get('finish_reason')} native={choice.get('native_finish_reason')}\n"
                 f"raw choice: {json.dumps(choice)[:2000]}")
    return content


def list_models():
    req = urllib.request.Request(f"{API}/models",
                                 headers={"Authorization": f"Bearer {key()}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        models = json.load(r)["data"]
    for m in sorted(models, key=lambda m: m["id"]):
        print(m["id"])


def pack(paths):
    parts = []
    for p in paths:
        f = ROOT / p
        if f.exists():
            parts.append(f"===== FILE: {p} =====\n{f.read_text()}")
    return "\n\n".join(parts)


def run_gates():
    lines = []
    for cmd in GATES:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        lines.append(f"$ {' '.join(cmd)}  (exit {r.returncode})\n" + "\n".join(tail))
        if r.returncode != 0:
            sys.exit(f"gate failed, aborting review: {' '.join(cmd)}")
    return "\n\n".join(lines)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        list_models()
        return
    out_name = sys.argv[1] if len(sys.argv) > 1 else sys.exit(__doc__)
    focus = " ".join(sys.argv[2:]) or "Full adversarial review of the v0.5 ADR gate."
    model = os.environ.get("OPENROUTER_MODEL") or sys.exit(
        "set OPENROUTER_MODEL (see: python3 tools/or_review.py --list)")

    gates = run_gates()
    print(f"[or-review] gates green; pass 1 ({model})...", file=sys.stderr)

    pass1 = call(model, [
        {"role": "system", "content":
         "You are an independent adversarial reviewer of Warrant: signed, "
         "hash-addressed decision records for AI agents. You cannot run code; the maintainer ran the "
         "gates and supplied fresh transcripts. Attack the governance rules and the "
         "specification text. Severity ladder: P0 = two conforming verifiers can disagree on a WarrantID or verification outcome, "
         "P1 = spec silent where implementers must guess, P2 = clarity, "
         "P3 = roadmap. Give concrete text proposals for every P1/P2. "
         "Do the arithmetic yourself and show it — do not trust claims."},
        {"role": "user", "content":
         f"FOCUS: {focus}\n\nGATE TRANSCRIPTS (run by maintainer today):\n"
         f"{gates}\n\nPRIMARY SOURCES:\n\n{pack(PRIMARY_SOURCES)}\n\n"
         "Write your findings now. You have NOT been shown prior reviews - "
         "form your own judgment."}])

    pass1_path = ROOT / "reviews" / (out_name + ".pass1")
    pass1_path.write_text(pass1.strip() + "\n")
    print(f"[or-review] pass 1 saved: reviews/{out_name}.pass1; pass 2 (comparison)...",
          file=sys.stderr)
    pass2 = call(model, [
        {"role": "system", "content":
         "Same reviewer, second pass. You will now see prior reviews of the "
         "same subject. Produce the FINAL review document in markdown: your "
         "pass-1 findings (edited for clarity, arithmetic shown), then a "
         "'Relation to prior reviews' section: agree / disagree / new, with "
         "reasons. Keep verdicts your own - do not defer. The FOCUS items are "
         "the assigned scope: every numbered FOCUS item MUST get its own "
         "section with your full analysis — do not compress them out; a "
         "review that skips a FOCUS item is nonconforming. Evidence "
         "discipline: you cannot run code, so never present transcript or "
         "prior-review data as your own observation — attribute it."},
        {"role": "user", "content":
         f"FOCUS (assigned scope): {focus}\n\nYOUR PASS-1 FINDINGS:\n\n{pass1}"
         f"\n\nPRIOR REVIEWS AND MAINTAINER "
         f"RESPONSES:\n\n{pack(PRIOR_REVIEWS_GLOB)}\n\n"
         "Emit the final review document now, starting with a '# Review:' "
         "heading and a '## Verdict' section."}])

    out = ROOT / "reviews" / out_name
    header = (f"<!-- produced via tools/or_review.py | model: {model} | "
              f"two-pass blind protocol | gates run by maintainer | "
              f"pass-1 (blind) preserved at reviews/{out_name}.pass1 -->\n\n")
    out.write_text(header + pass2.strip() + "\n")
    print(f"review delivered: reviews/{out_name}")


if __name__ == "__main__":
    main()
