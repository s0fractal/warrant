#!/usr/bin/env python3
"""Adversarial design gate with MACHINE-VERIFIED reproductions.

WHY THIS EXISTS
---------------
AGENTS.md §3: "an independent gate means adversarial counter-vector hunting by a
fresh reviewer -- NOT running the green test suites." A reviewer that cannot run
code can only *assert* a counter-vector, and an asserted counter-vector is a
claim, not a finding. Every prior WRT-002 gate was Codex, i.e. one family with
one blind spot, iterated -- the Decision Process asks for >=3 independent
families.

This harness fixes both halves at once. The reviewer supplies a reproduction as
executable Python; the HARNESS runs it against a pristine copy of the model and
feeds the reviewer the real transcript. So:

  * independence comes from the reviewer (a different model family, no access to
    prior reviews in round 1);
  * "it reproduces" is decided by execution here, never by the reviewer's
    confidence -- a finding whose reproduction does not run is demoted to a
    question, in the reviewer's own final document;
  * every transcript is appended verbatim to the review, so a human can re-run
    each block and check the harness itself.

The harness is NOT a reviewer. It grades nothing. It runs code and records what
happened.

PROTOCOL
    round 1  brief + normative section + model source  -> findings + REPRO blocks
    (exec)   each REPRO runs in a throwaway copy of the model dir, 60s cap
    round 2  verbatim transcripts fed back             -> revise / withdraw / add
    (exec)   any new or repaired REPRO runs the same way
    round 3  everything above                          -> final review document

USAGE
    OPENROUTER_MODEL=moonshotai/kimi-k3 \
    python3 tools/adversarial_gate.py --target wrt-002 \
        --out reviews/2026-07-kimi-k3-wrt-002-rev7-adversarial-gate.md

Key: $OPENROUTER_API_KEY or ~/.config/openrouter/key.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://openrouter.ai/api/v1"
EXEC_TIMEOUT = 60          # seconds per reproduction
MAX_OUTPUT = 6000          # chars of transcript fed back per reproduction

# A target names: the brief, the normative text, the runnable model, and the
# command that must already pass before any review starts.
TARGETS = {
    "settle": {
        "brief": "briefs/SETTLE-GATE-brief.md",
        "normative": ("AGENTS.md", "## Hard rules", "## Precedent"),
        # Staged, not a checked-in duplicate: the reviewed bytes are the live
        # ones, so a gate can never pass against a stale copy of the tool.
        "stage": ["tools/settle.py", "policies/gate-settlement.json",
                  "tests/settlement_gate.py"],
        "workdir": None,                      # filled by stage_workdir()
        "sources": ["tools/settle.py", "policies/gate-settlement.json",
                    "tests/settlement_gate.py"],
        "baseline": ["python3", "settlement_gate.py"],
        "baseline_expect": "SETTLE-GATE: ALL PASS",
        "module": "settle",
        "subject": "settle.py gate-settlement rule (executed-repro blocking, per-clause novelty)",
    },
    "wrt-002": {
        "brief": "briefs/WRT-002-rev7-adversarial-gate.md",
        "normative": ("proposals/WRT-002-keystate-effective-lifecycle-r1.md",
                      "## D. Formal definitions", "## 7. Countervectors"),
        "workdir": "proposals/wrt-002-model",
        "sources": ["proposals/wrt-002-model/model.py",
                    "proposals/wrt-002-model/vectors.py"],
        "baseline": ["python3", "vectors.py"],
        "baseline_expect": "WRT-002-MODEL: ALL PASS",
        "subject": "WRT-002 rev 7 (key-state, authorized effective-lifecycle, R1 checkpoint)",
    },
}

REPRO_RULES = """
HOW TO SUBMIT A REPRODUCTION (read carefully -- this is the whole protocol)

You cannot run code. I can, and I will run whatever you write, unmodified,
against a pristine copy of the model directory. Emit each reproduction as its
own fenced block using EXACTLY this form:

```repro id=F1 severity=P0 clause=D.3 title=short title here
import MODULE
# ... build the store, drive the machine, and DEMONSTRATE the violation ...
assert something_that_must_not_happen, "explain what D says must not happen"
print("VIOLATION: <one line naming the property of D that just broke>")
```

Rules that decide whether your finding survives:

  * The block runs with the model directory as CWD, so `import MODULE` works.
    Nothing else is available: no network, no repo, no pip installs.
  * A reproduction that DEMONSTRATES the violation must exit 0 and print a line
    starting with `VIOLATION:`. Write it so it FAILS LOUDLY (raises, or exits
    non-zero) if the machine actually behaves correctly -- an unconditional
    print proves nothing and I will show you the transcript either way.
  * `id` must be unique. `severity` is one of P0/P1/P2.
  * `clause` names the normative clause your block breaks, exactly as it is
    numbered in the section quoted to you (e.g. `D.3`, `7.2`). This is how
    settlement tells a genuinely new defect from the same defect re-derived with
    different code: a claim against a clause already broken in an earlier round
    is recorded as a restatement, not as a new blocker. If your attack breaks
    something the section never states, write `clause=unstated` and say in the
    finding which property you believe is implied but unwritten -- an unwritten
    property that can be violated IS a finding, and often the most valuable one.
  * Runtime cap: 60 seconds. No sleeps, no unbounded loops.
  * If you cannot write a runnable reproduction for something you suspect, do
    NOT dress it up as a finding: file it under 'Questions' and say what you
    would need to settle it.

I will hand you the verbatim stdout/stderr/exit status of every block. Then you
revise: keep, repair, or withdraw. A finding whose reproduction does not run is
not a finding, and you will be asked to say so in your own words.
"""


def key():
    k = os.environ.get("OPENROUTER_API_KEY")
    if not k:
        p = Path.home() / ".config/openrouter/key"
        if p.exists():
            k = p.read_text().strip()
    if not k:
        sys.exit("no OpenRouter key: set OPENROUTER_API_KEY or write ~/.config/openrouter/key")
    return k


def call_cli(cli, model, messages):
    """Drive a locally installed agent CLI instead of OpenRouter.

    Run in an EMPTY temp directory, never the checkout. `tools/ai-review.sh`
    learned this the hard way: a skip-permissions agent WILL follow any path it
    can reach, and round 1 must be blind. Everything the reviewer is allowed to
    see is inlined in the prompt.
    """
    prompt = "\n\n".join(f"===== {m['role'].upper()} =====\n{m['content']}"
                          for m in messages)
    argv = {"kimi": [cli, "-p", prompt],
            "codex": [cli, "exec", "--skip-git-repo-check", prompt]}.get(
                Path(cli).name, [cli, "-p", prompt])
    if model and Path(cli).name == "kimi":
        argv[1:1] = ["-m", model]
    tmp = tempfile.mkdtemp(prefix="advgate-cli-")
    try:
        p = subprocess.run(argv, cwd=tmp, capture_output=True, text=True, timeout=3600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if p.returncode != 0 and not p.stdout.strip():
        sys.exit(f"{cli} failed (exit {p.returncode}):\n{p.stderr[-3000:]}")
    return p.stdout


def stage_workdir(t):
    """Copy the reviewed files into a self-contained directory for the harness."""
    d = Path(tempfile.mkdtemp(prefix="advgate-stage-"))
    for rel in t["stage"]:
        shutil.copy2(ROOT / rel, d / Path(rel).name)
    return d


def call(model, messages, max_tokens=32000, retries=3):
    body = json.dumps({"model": model, "messages": messages,
                       "max_tokens": max_tokens}).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                f"{API}/chat/completions", data=body,
                headers={"Authorization": f"Bearer {key()}",
                         "Content-Type": "application/json",
                         "HTTP-Referer": "https://github.com/s0fractal/warrant",
                         "X-Title": "warrant adversarial design gate"})
            with urllib.request.urlopen(req, timeout=3600) as r:
                out = json.load(r)
            if "error" in out:
                raise RuntimeError(out["error"])
            choice = out["choices"][0]
            content = choice["message"].get("content") or choice["message"].get("reasoning")
            if not content:
                raise RuntimeError(f"empty content; finish_reason={choice.get('finish_reason')}")
            return content
        except Exception as e:                       # noqa: BLE001 - report and retry
            last = e
            print(f"  [gate] API attempt {attempt + 1}/{retries} failed: {e}", file=sys.stderr)
            time.sleep(5 * (attempt + 1))
    sys.exit(f"openrouter failed after {retries} attempts: {last}")


# Two accepted shapes, because reviewers reliably produce both and rejecting the
# second would silently discard real counter-vectors:
#   ```repro id=F1 severity=P0 title=...        <- meta on the fence line
#   ```python\nrepro id=F1 severity=P0 ...      <- meta on the first body line
REPRO_RE = re.compile(r"```repro[ \t]*([^\n]*)\n(.*?)```", re.S)
REPRO_INLINE_RE = re.compile(
    r"```(?:python|py)?[ \t]*\n[ \t]*repro[ \t]+([^\n]*)\n(.*?)```", re.S)


def parse_repros(text):
    """Extract (meta, code) pairs. Tolerant of attribute order and quoting.

    `title=` is deliberately greedy to end-of-line: reviewers write
    `title=quorum can vanish a record`, unquoted and full of spaces, and losing
    everything after the first word would mislabel the finding in the review.
    """
    out = []
    found = REPRO_RE.findall(text) + REPRO_INLINE_RE.findall(text)
    for meta_line, code in found:
        if not code.strip() or "..." == code.strip():
            continue                       # a sketch of a block, not a block
        meta = {}
        rest = meta_line
        for k in ("id", "severity", "clause"):
            m = re.search(rf"\b{k}\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))", rest)
            if m:
                meta[k] = m.group(1) or m.group(2) or m.group(3) or ""
                rest = rest[:m.start()] + rest[m.end():]
        m = re.search(r"\btitle\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(.*))$", rest.strip())
        if m:
            meta["title"] = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        else:
            meta["title"] = rest.strip()
        out.append((meta, code))
    # de-duplicate by id, keeping the last (a repaired block supersedes its
    # earlier draft when a reviewer re-emits the same id in one message)
    dedup = {}
    for meta, code in out:
        dedup[meta.get("id") or f"anon{len(dedup)}"] = (meta, code)
    return list(dedup.values())


def run_repro(workdir, code):
    """Run one reproduction in a throwaway copy of the model directory."""
    tmp = tempfile.mkdtemp(prefix="advgate-")
    try:
        sandbox = Path(tmp) / "model"
        shutil.copytree(workdir, sandbox, ignore=shutil.ignore_patterns("__pycache__"))
        script = sandbox / "_repro.py"
        script.write_text(code)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            p = subprocess.run([sys.executable, "_repro.py"], cwd=sandbox, env=env,
                               capture_output=True, text=True, timeout=EXEC_TIMEOUT)
            stdout, stderr, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            stdout, stderr, rc = "", f"TIMEOUT after {EXEC_TIMEOUT}s", 124
        return {
            "exit": rc,
            "stdout": stdout[-MAX_OUTPUT:],
            "stderr": stderr[-MAX_OUTPUT:],
            "violation": rc == 0 and any(
                l.startswith("VIOLATION:") for l in stdout.splitlines()),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def transcript_block(meta, res):
    verdict = ("REPRODUCED — exited 0 and printed VIOLATION"
               if res["violation"] else
               "NOT REPRODUCED — " + (
                   f"exit {res['exit']}" if res["exit"] else
                   "exit 0 but no VIOLATION line was printed"))
    return (f"### repro {meta.get('id', '?')} "
            f"[{meta.get('severity', '?')}] {meta.get('title', '')}\n"
            f"HARNESS VERDICT: {verdict}\n"
            f"--- stdout ---\n{res['stdout'] or '(empty)'}\n"
            f"--- stderr ---\n{res['stderr'] or '(empty)'}\n"
            f"--- exit: {res['exit']} ---\n")


def slice_section(path, start, end):
    txt = (ROOT / path).read_text()
    i = txt.find(start)
    if i < 0:
        return txt
    j = txt.find(end, i + 1)
    return txt[i:] if j < 0 else txt[i:j]


def pack(paths):
    return "\n\n".join(
        f"===== FILE: {p} =====\n{(ROOT / p).read_text()}"
        for p in paths if (ROOT / p).exists())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="wrt-002", choices=sorted(TARGETS))
    ap.add_argument("--out", required=True, help="reviews/<file>.md")
    ap.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL"))
    ap.add_argument("--cli", help="path to a local agent CLI (kimi, codex); "
                                   "when set, OpenRouter is not used")
    ap.add_argument("--family", help="reviewer family id for settlement, e.g. "
                                     "kimi@moonshot; defaults to the model's vendor prefix")
    args = ap.parse_args()
    if not args.model and not args.cli:
        sys.exit("set --model, OPENROUTER_MODEL, or --cli")
    _api = call
    if args.cli:
        def _api(model, messages, **kw):                    # noqa: ARG001
            return call_cli(args.cli, model, messages)

    t = TARGETS[args.target]
    workdir = stage_workdir(t) if t.get("stage") else ROOT / t["workdir"]

    # The baseline must already pass, or a 'finding' could just be a broken tree.
    base = subprocess.run(t["baseline"], cwd=workdir, capture_output=True, text=True)
    if t["baseline_expect"] not in base.stdout:
        sys.exit(f"baseline did not pass; refusing to review a broken tree:\n{base.stdout[-2000:]}")
    print(f"[gate] baseline: {t['baseline_expect']}", file=sys.stderr)

    repro_rules = REPRO_RULES.replace("MODULE", t.get("module", "model"))
    brief = (ROOT / t["brief"]).read_text()
    normative = slice_section(*t["normative"])
    sources = pack(t["sources"])

    system = (
        "You are an independent adversarial reviewer. Your job is to BREAK a "
        "design by producing executable counter-vectors, not to summarise it and "
        "not to confirm that its test suite passes -- the suite already passes, "
        "and reporting that is a rubber stamp that will be rejected. A refuted "
        "attack, shown as a walk, is a valuable result and you should report "
        "those too. State plainly what you did not examine.")

    print(f"[gate] round 1 ({args.model}) ...", file=sys.stderr)
    r1 = _api(args.model, [
        {"role": "system", "content": system},
        {"role": "user", "content":
            f"SUBJECT: {t['subject']}\n\n{brief}\n\n{repro_rules}\n\n"
            f"===== NORMATIVE SECTION (this governs) =====\n{normative}\n\n"
            f"{sources}\n\n"
            "Hunt now. Emit your findings, each with a ```repro block. You have "
            "NOT been shown any prior review: form your own judgment."}])

    rounds = [("round 1 — blind attack", r1)]
    all_results = []
    last = r1                    # last NON-EMPTY reviewer message

    for rnd in (2, 3):
        repros = parse_repros(last)
        blocks = []
        for meta, code in repros:
            res = run_repro(workdir, code)
            all_results.append((rnd - 1, meta, code, res))
            mark = "REPRODUCED" if res["violation"] else "not reproduced"
            print(f"  [{meta.get('id', '?')}] {mark} (exit {res['exit']})", file=sys.stderr)
            blocks.append(transcript_block(meta, res))
        if repros:
            print(f"[gate] executed {len(repros)} reproduction(s) from round {rnd - 1}",
                  file=sys.stderr)
            # Persist NOW. The reviewer may not survive the next round.
            emit_ledger(args, t, normative, all_results, complete=False)
        else:
            print(f"[gate] no parseable repro block in round {rnd - 1}", file=sys.stderr)
        feedback = "\n".join(blocks) if blocks else (
            "(NOTHING TO RUN. Your previous message contained no block I could "
            "execute. A reproduction must be a fenced block whose opening line is "
            "```repro id=... severity=... title=... followed by real Python — not "
            "an outline, not prose, not `...`.)")

        if not repros and rnd == 2:
            ask = ("I could not execute anything you wrote, so no finding of yours "
                   "is yet supported by evidence. Re-emit every attack you actually "
                   "believe in as a runnable ```repro block, in the exact format "
                   "above. If an attack cannot be made runnable, drop it to "
                   "'Questions' and say why. Do not restate the design.")
        elif rnd == 2:
            ask = ("Here is exactly what happened when I ran your reproductions "
                   "against a pristine model. Now revise, honestly:\n"
                   "  * for each REPRODUCED block, confirm the violation is the one "
                   "you predicted (read the output -- it may have failed for an "
                   "unrelated reason, which is not your finding);\n"
                   "  * for each NOT REPRODUCED block, either repair it (emit a new "
                   "```repro block with the same id) or withdraw the finding and say "
                   "so in one sentence;\n"
                   "  * you may add new ```repro blocks for attacks the transcripts "
                   "suggested.\n"
                   "Do not restate the design. Only the delta.")
        else:
            ask = ("Final round. Here are the transcripts from your revised "
                   "reproductions. Now write the FINAL REVIEW DOCUMENT in markdown, "
                   "starting with '# Review:' and containing, in this order:\n"
                   "  ## Verdict  (APPROVE | AMEND | REJECT, one line of reasoning)\n"
                   "  ## Examined  (what you actually read)\n"
                   "  ## NOT examined  (what you skipped, and why)\n"
                   "  ## Findings  (only reproductions that ACTUALLY RAN here; each "
                   "with its id, severity, the property of D it breaks, and the "
                   "transcript's key line)\n"
                   "  ## Questions  (suspicions you could not reproduce -- say so "
                   "plainly; do not launder these into findings)\n"
                   "  ## Refuted  (attacks you tried that held, with the walk)\n"
                   "Be exact about which of your own claims the machine confirmed "
                   "and which it did not. I will append the raw transcripts to your "
                   "document, so any mismatch will be visible.")

        print(f"[gate] round {rnd} ({args.model}) ...", file=sys.stderr)
        resp = _api(args.model, [
            {"role": "system", "content": system},
            {"role": "user", "content":
                f"SUBJECT: {t['subject']}\n\n{brief}\n\n{repro_rules}\n\n"
                f"===== NORMATIVE SECTION =====\n{normative}\n\n{sources}"},
            {"role": "assistant", "content": last},
            {"role": "user", "content":
                f"===== EXECUTION TRANSCRIPTS (produced by running your code) =====\n"
                f"{feedback}\n\n{ask}"}])
        rounds.append((f"round {rnd}", resp))
        # An empty or whitespace reply must never become the review body — that
        # is how the first run of this harness produced a document consisting of
        # a header and two appendices with nothing in between.
        if resp.strip():
            last = resp

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    ran = sum(1 for *_, r in all_results if r["violation"])
    header = (
        f"<!-- produced via tools/adversarial_gate.py | model: {args.model} | "
        f"target: {args.target} | reproductions executed by the harness, not "
        f"claimed by the reviewer -->\n\n"
        f"> **How this review was produced.** The reviewer ({args.model}) cannot "
        f"run code. It emitted counter-vectors as executable Python; "
        f"`tools/adversarial_gate.py` ran each one against a pristine copy of "
        f"`{t['workdir']}` and fed back the verbatim transcript, twice. "
        f"{len(all_results)} reproduction(s) were executed; {ran} exited 0 and "
        f"printed a `VIOLATION:` line. The raw transcripts are appended below the "
        f"review, unedited, so every claim here can be re-run by hand.\n"
        f">\n"
        f"> The harness grades nothing and is not a reviewer. Adjudication is a "
        f"separate, human-authorised step (AGENTS.md §4).\n\n")

    body = last.strip()
    appendix = ["\n\n---\n\n## Appendix A — machine-executed reproductions (verbatim)\n"]
    for rnd, meta, code, res in all_results:
        appendix.append(
            f"\n### [{rnd}] {meta.get('id', '?')} — {meta.get('title', '')} "
            f"({meta.get('severity', '?')})\n\n"
            f"```python\n{code.strip()}\n```\n\n"
            f"```\n{transcript_block(meta, res)}```\n")
    intermediate = ["\n\n---\n\n## Appendix B — earlier rounds (unedited)\n"]
    for name, text in rounds[:-1]:
        intermediate.append(f"\n### {name}\n\n{text.strip()}\n")

    out.write_text(header + body + "".join(appendix) + "".join(intermediate) + "\n")
    print(f"\nreview delivered: {args.out}  "
          f"({len(all_results)} reproductions executed, {ran} reproduced)")

    emit_ledger(args, t, normative, all_results, complete=True)


def emit_ledger(args, t, normative, all_results, complete):
    """Write the machine record `tools/settle.py` reads.

    Called after EVERY execution batch, not only at the end. On this tool's first
    real run the reviewer's quota ran out in round 3 and twelve already-executed
    reproductions died with the process -- transcripts gone, nothing to re-read,
    no way to tell a refuted attack from an attack that never ran. Executed
    evidence is the expensive part and the only part that decides anything; it is
    written the moment it exists.

    `complete` records whether the reviewer finished. A partial ledger is real
    evidence and must be readable, but it must never be mistaken for a finished
    gate, so it says which it is.

    Reviewer prose has no slot here, deliberately: an assertion must not be able
    to reach the settlement rule. Only the LAST result per repro id is kept -- a
    reviewer who repairs a block re-emits the same id, and keeping the broken
    draft too would let one finding count twice.
    """
    final = {}
    for rnd, meta, code, res in all_results:
        final[meta.get("id") or f"anon{len(final)}"] = (rnd, meta, code, res)
    subject_sha256 = hashlib.sha256(normative.encode("utf-8")).hexdigest()
    family = args.family or (args.model.split("/")[0] if "/" in args.model else args.model)
    ledger = {
        "item": args.target,
        "family": family,
        "model": args.model,
        "host": socket.gethostname(),
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "subject_sha256": subject_sha256,
        "subject_label": t["subject"],
        "review": args.out,
        "complete": complete,
        "findings": [{
            "id": meta.get("id"),
            "severity": (meta.get("severity") or "P?").upper(),
            "clause": meta.get("clause", ""),
            "title": meta.get("title", ""),
            "repro_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "transcript_sha256": hashlib.sha256(
                (res["stdout"] + res["stderr"] + str(res["exit"])).encode("utf-8")
            ).hexdigest(),
            "exit": res["exit"],
            "reproduced": res["violation"],
        } for _, meta, code, res in final.values()],
    }
    ledger_dir = ROOT / "reviews" / "ledgers"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = ledger_dir / (Path(args.out).stem + ".json")
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    print(f"settlement ledger{'' if complete else ' (PARTIAL)'}: "
          f"{ledger_path.relative_to(ROOT)}  "
          f"(family {family}, subject {subject_sha256[:12]}, "
          f"{len(ledger['findings'])} executed)", file=sys.stderr)


if __name__ == "__main__":
    main()
