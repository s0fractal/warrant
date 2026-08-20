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
import secrets
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
        "baseline": ["python3", "tests/settlement_gate.py"],
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
  * A violation is declared ONLY by calling `harness.violation(expected, got)`.
    The module is injected beside your block; a `VIOLATION` line you print
    yourself is ignored and the finding is recorded NOT reproduced.

    This is not ceremony. Twice now a reviewer here has written the shape

        assert result["state"] == "UNRESOLVED"       # the CORRECT behaviour
        print("VIOLATION: expected=UNRESOLVED got=SETTLED")

    where the assert passes, the printed `got` is a word the reviewer typed, and
    the violation therefore fires precisely when the machine is RIGHT. Both times
    it was recorded as a reproduced P0 until a human read the source. Requiring a
    stated disagreement did not stop the second one, because typing two different
    words is not a disagreement -- it is a sentence about one.

    `harness.violation` compares the two values at runtime and exits non-zero when
    they match, so the inverted shape cannot pass through it. Pass `got` as an
    EXPRESSION READ FROM THE RUN -- `result["state"]`, `len(claims)` -- never a
    literal. Passing two different literals still technically counts and is
    visible in the source as exactly what it is; if the transcripts show you did
    that, the finding will be treated accordingly.
  * If the attack RUNS and the property HOLDS, say so: call `harness.refuted("what
    you tried")`. Do not just let the block exit. A block that ran, printed a
    finding, and called neither is recorded `inconclusive` and closes nothing --
    it cannot be read as evidence either way, because printing a result and
    demonstrating one are different acts and only the second is checkable.
  * Write the block so it fails loudly when the machine behaves correctly.
  * `id` must be unique. `severity` is one of P0/P1/P2.
  * `clause` names the normative clause your block breaks, exactly as it is
    numbered in the section quoted to you (e.g. `D.3`, `7.2`). This is how
    settlement tells a genuinely new defect from the same defect re-derived with
    different code: a claim against a clause already broken in an earlier round
    is recorded as a restatement, not as a new blocker. If your attack breaks
    something the section never states, write `clause=unstated` and say in the
    finding which property you believe is implied but unwritten -- an unwritten
    property that can be violated IS a finding, and often the most valuable one.
    `unstated` findings are never merged with each other: they name no clause, so
    settlement keys them individually rather than letting a refutation of one
    close the rest. The other side of that: to show a PREVIOUS unstated finding
    is fixed, add `closes=<its claim key>` to a block that re-runs the old attack
    and no longer reproduces. Without the citation the old claim stays open
    forever, because a re-test is new code and nothing can match it up.
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
    if model and Path(cli).name == "kimi" and not model.startswith("/"):
        argv[1:1] = ["-m", model]
    tmp = tempfile.mkdtemp(prefix="advgate-cli-")
    try:
        p = subprocess.run(argv, cwd=tmp, capture_output=True, text=True, timeout=3600)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if p.returncode != 0 and not p.stdout.strip():
        sys.exit(f"{cli} failed (exit {p.returncode}):\n{p.stderr[-3000:]}")
    return p.stdout


def call_local(model, messages, ctx=32768):
    """Drive a model running on this machine through ollama's local HTTP API.

    WHY THIS MATTERS MORE THAN IT LOOKS
    A reviewer family used to cost money, so diversity had a per-round price and
    the cheap path was another round of the family already paid for -- which is
    exactly how one item collected eight same-family gates and no P0. A local
    model makes a fourth family cost electricity.

    The quality gap is real and does not need hiding, because this harness makes
    it harmless: only a reproduction that EXECUTES can block. A weaker reviewer
    that emits twenty confident wrong counter-vectors costs twenty local
    subprocess runs and blocks nothing. It cannot rubber-stamp either -- it has
    no authority to grant. Its worst case is wasted free compute; its best case
    is a defect the paid families did not look for. That asymmetry is what makes
    a cheap reviewer worth running at all.

    `num_ctx` is set explicitly: ollama's default window silently truncates, and
    a reviewer that never saw half the source would file findings against code
    that is not there -- a failure indistinguishable, from the outside, from a
    bad model.
    """
    prompt = "\n\n".join(f"===== {m['role'].upper()} =====\n{m['content']}"
                          for m in messages)
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"num_ctx": ctx}}).encode()
    req = urllib.request.Request("http://localhost:11434/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3600) as r:
            out = json.load(r)
    except urllib.error.URLError as e:
        sys.exit(f"local model unreachable ({e}); is `ollama serve` running?")
    text = out.get("response", "")
    if not text.strip():
        sys.exit(f"local model {model} returned nothing")
    return text


def subject_hash(t, ref="HEAD"):
    """Hash of everything the reviewer is shown that governs the verdict.

    The subject was the normative prose slice alone, which is wrong whenever the
    reviewed artifact is code: two different revisions of `settle.py` hashed
    identically because AGENTS.md had not moved, so findings against superseded
    code would have counted as findings against what is on the branch now. That
    is the same defect Codex reported in settle.py itself -- deciding what the
    artifact is from something other than the artifact -- reproduced one layer up
    in the target definition that feeds it.

    Sources are folded in by path and content, sorted, so the hash is stable
    across machines and changes exactly when the reviewed bytes change. A gate in
    flight when the code moves is therefore a gate on the old subject, and
    settlement will say so instead of crediting it to the new one.
    """
    h = hashlib.sha256()
    h.update(slice_section(*t["normative"], ref=ref).encode("utf-8"))
    for rel in sorted(t.get("sources", [])):
        try:
            blob = read_at(ref, rel)
        except subprocess.CalledProcessError:
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        h.update(blob)
        h.update(b"\x00")
    return h.hexdigest()


HARNESS_MODULE = """\
import sys

_NONCE = "{nonce}"


def refuted(note=""):
    # Declare that the attack RAN and the property HELD. Say it explicitly:
    # exiting quietly cannot be told apart from a block that printed a finding
    # and forgot to call violation(), and reading that as a refutation lets a
    # demonstration close the very claim it demonstrates.
    print("REFUTED[%s]: %s" % (_NONCE, note or "attack ran, property held"))


def violation(expected, got, note=""):
    # Declare a demonstrated disagreement. The HARNESS decides whether it is one.
    #
    # `got` must be an expression evaluated from the run -- result["state"], not
    # a literal you typed. The comparison happens here, at runtime, so a block
    # that asserts the CORRECT behaviour and then announces a violation cannot
    # pass: it hands identical values in and exits non-zero.
    e, o = str(expected).strip(), str(got).strip()
    if e == o:
        print("NO VIOLATION: expected and got are both %r -- the machine agreed "
              "with the rule" % (e,), file=sys.stderr)
        raise SystemExit(1)
    if e in o or o in e:
        # One value decorating the other is how a violation survives agreement:
        # expected="X not admitted (because the quorum lost)" against
        # got="X not admitted" compares unequal while meaning the same thing.
        # Caught here after the author of this check wrote exactly that and read
        # the resulting VIOLATION as a live defect. Prose belongs in `note`.
        print("NO VIOLATION: %r and %r differ only by decoration -- put the "
              "reasoning in note= and compare bare values" % (e, o), file=sys.stderr)
        raise SystemExit(1)
    print("VIOLATION[%s]: expected=%s got=%s%s"
          % (_NONCE, expected, got, (" -- " + note) if note else ""))
"""


def read_at(ref, rel):
    """Bytes of one path at a git ref. Never from the working tree."""
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:{rel}"],
                          capture_output=True, check=True).stdout


def stage_workdir(t, ref="HEAD"):
    """Copy the reviewed files into a self-contained tree, KEEPING their paths.

    Read at a git REF, never from the working tree. Reading the disk meant a
    branch switch during a run silently changed what was under review: one gate
    died when its files vanished mid-flight, and another computed its subject
    hash from whatever happened to be checked out, filing a ledger against a
    state matching no branch at all. `disclosure_manifest.py` already carried
    this rule in writing -- a manifest depending on an uncommitted checkout
    describes a state no one else can reach -- and this file was built ignoring
    it.

    Flattening these was a harness defect that silently destroyed reviews. The
    reviewer is shown each source under its repository path (`pack()` writes
    `===== FILE: policies/gate-settlement.json =====`), so it reasonably writes
    counter-vectors that open those paths -- and every one of them died with
    FileNotFoundError against a flat directory. Two different families lost
    entire rounds to it before anyone read a transcript, and their silence looked
    exactly like "the design held".

    A gate whose environment breaks the reviewer's code is worse than no gate: it
    manufactures the appearance of a clean review out of an unrunnable one.
    """
    d = Path(tempfile.mkdtemp(prefix="advgate-stage-"))
    for rel in t["stage"]:
        dest = d / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(read_at(ref, rel))
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
#
# This is deliberately a line parser rather than a regex over the entire model
# response. The response is untrusted and can be large; bounded line scans make
# both the accepted grammar and the runtime obvious.
def _repro_header(lines, index):
    label = lines[index].strip()[3:].strip()
    body_start = index + 1
    if label == "repro" or label.startswith(("repro ", "repro\t")):
        return label[5:].strip(), body_start
    if label not in ("", "python", "py") or body_start >= len(lines):
        return None
    first = lines[body_start].strip()
    if first == "repro" or first.startswith(("repro ", "repro\t")):
        return first[5:].strip(), body_start + 1
    return None


def _closing_fence(lines, start):
    for index in range(start, len(lines)):
        if lines[index].strip() == "```":
            return index
    return None


def _fenced_repros(text):
    lines = text.splitlines(keepends=True)
    found = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped.startswith("```"):
            i += 1
            continue
        header = _repro_header(lines, i)
        if header is None:
            i += 1
            continue
        meta_line, body_start = header
        end = _closing_fence(lines, body_start)
        if end is None:
            break
        found.append((meta_line, "".join(lines[body_start:end])))
        i = end + 1
    return found


def _assignment(text, key):
    start = 0
    while True:
        at = text.find(key, start)
        if at < 0:
            return None
        before = text[at - 1] if at else " "
        after_key = at + len(key)
        after = text[after_key] if after_key < len(text) else " "
        if (before.isalnum() or before == "_" or
                not (after.isspace() or after == "=")):
            start = at + len(key)
            continue
        pos = after_key
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos < len(text) and text[pos] == "=":
            return at, pos + 1
        start = at + len(key)


def _quoted_attr(text, pos, rest_of_line):
    quote = text[pos]
    value_start = pos + 1
    end = text.find(quote, value_start)
    if end < 0:
        return text[value_start:], len(text)
    remove_end = end + 1
    # `title="prefix" remaining words` is an unquoted title that happens
    # to begin with quotes, not a quoted attribute followed by garbage.
    # Preserve the established parser contract for existing reviews.
    if rest_of_line and text[remove_end:].strip():
        return text[pos:].strip(), len(text)
    return text[value_start:end], remove_end


def _plain_attr(text, pos, rest_of_line):
    if rest_of_line:
        return text[pos:].strip(), len(text)
    end = pos
    while end < len(text) and not text[end].isspace():
        end += 1
    return text[pos:end], end


def _pop_meta_attr(text, key, rest_of_line=False):
    """Return (value, text-with-attribute-removed), without regex backtracking."""
    assignment = _assignment(text, key)
    if assignment is None:
        return None, text
    at, pos = assignment
    while pos < len(text) and text[pos].isspace():
        pos += 1
    if pos >= len(text):
        return "", text[:at]
    if text[pos] in ("\"", "'"):
        value, remove_end = _quoted_attr(text, pos, rest_of_line)
    else:
        value, remove_end = _plain_attr(text, pos, rest_of_line)
    return value, text[:at] + text[remove_end:]


def parse_repros(text):
    """Extract (meta, code) pairs. Tolerant of attribute order and quoting.

    `title=` is deliberately greedy to end-of-line: reviewers write
    `title=quorum can vanish a record`, unquoted and full of spaces, and losing
    everything after the first word would mislabel the finding in the review.
    """
    out = []
    for meta_line, code in _fenced_repros(text):
        if not code.strip() or "..." == code.strip():
            continue                       # a sketch of a block, not a block
        meta = {}
        rest = meta_line
        for k in ("id", "severity", "clause", "closes"):
            value, rest = _pop_meta_attr(rest, k)
            if value is not None:
                meta[k] = value
        title, rest = _pop_meta_attr(rest, "title", rest_of_line=True)
        meta["title"] = (title if title is not None else rest).strip()
        out.append((meta, code))
    # de-duplicate by id, keeping the last (a repaired block supersedes its
    # earlier draft when a reviewer re-emits the same id in one message)
    dedup = {}
    for meta, code in out:
        dedup[meta.get("id") or f"anon{len(dedup)}"] = (meta, code)
    return list(dedup.values())


def run_repro(workdir, code, nonce):
    """Run one reproduction in a throwaway copy of the model directory."""
    tmp = tempfile.mkdtemp(prefix="advgate-")
    try:
        sandbox = Path(tmp) / "model"
        shutil.copytree(workdir, sandbox, ignore=shutil.ignore_patterns("__pycache__"))
        (sandbox / "harness.py").write_text(HARNESS_MODULE.format(nonce=nonce))
        script = sandbox / "_repro.py"
        script.write_text(code)
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        # Every directory holding a module is importable, so `import settle`
        # works while `policies/gate-settlement.json` still resolves. Preserving
        # the layout without this would trade one broken environment for another.
        pkg_dirs = sorted({str(f.parent) for f in sandbox.rglob("*.py")})
        env["PYTHONPATH"] = os.pathsep.join([str(sandbox), *pkg_dirs])
        try:
            p = subprocess.run([sys.executable, "_repro.py"], cwd=sandbox, env=env,
                               capture_output=True, text=True, timeout=EXEC_TIMEOUT)
            stdout, stderr, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            stdout, stderr, rc = "", f"TIMEOUT after {EXEC_TIMEOUT}s", 124
        demonstrated, why = _demonstrates(stdout, nonce)
        if rc == 0 and demonstrated:
            outcome = "violation"
        elif f"REFUTED[{nonce}]:" in stdout or "NO VIOLATION:" in stderr:
            outcome = "refuted"
        elif rc != 0:
            outcome = "unrunnable"
        else:
            outcome = "inconclusive"
        return {
            "exit": rc,
            "stdout": stdout[-MAX_OUTPUT:],
            "stderr": stderr[-MAX_OUTPUT:],
            "violation": rc == 0 and demonstrated,
            "why": why,
            # Three outcomes, not two. A block that CRASHED refutes nothing, and
            # calling it "did not reproduce" is how a claim closes because the
            # interface moved under it rather than because the defect went away.
            # Observed re-running seven stored counter-vectors after a policy
            # schema change: every one died on a KeyError, and read as two
            # outcomes they would all have looked like clean refutations.
            # Four outcomes. `refuted` requires the reviewer to SAY the property
            # held -- via harness.refuted(), or via violation() finding the two
            # values equal. Kimi's paid gate emitted seven blocks that ran, printed
            # a demonstrated defect, and never called violation(); read as
            # "exit 0, therefore refuted" they were recorded as evidence AGAINST
            # the defects they had just shown, and could have closed those very
            # claims. Anything that ran without saying which is `inconclusive`,
            # and inconclusive closes nothing.
            "outcome": outcome,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _demonstrates(stdout, nonce):
    """Did this run demonstrate a DISAGREEMENT, or merely announce one?

    A counter-vector claims the machine produced the wrong outcome, so it must
    name both outcomes and they must differ. Checking that mechanically closes
    the way a repro fools its own author: assert the CORRECT behaviour, watch the
    assert pass, print VIOLATION unconditionally -- a violation that fires exactly
    when the machine is right. Observed here on 2026-07-28 from a local reviewer,
    which had already been recorded as a reproduced P0 before anyone read the code.

    Returns (demonstrated, reason). The reason goes back to the reviewer, because
    a silent demotion teaches nothing and the protocol has a repair round for
    exactly this.
    """
    if any(l.startswith(f"VIOLATION[{nonce}]:") for l in stdout.splitlines()):
        return True, "harness-issued: expected and got differed at runtime"
    if any(l.startswith("VIOLATION") for l in stdout.splitlines()):
        return False, ("a VIOLATION line was printed by hand. Only "
                       "harness.violation(expected, got) counts: it compares the "
                       "values AT RUNTIME, so a block that asserts the correct "
                       "behaviour and then announces a violation cannot pass. A "
                       "hand-written line is no evidence that `got` came from the "
                       "run at all -- it is a string you typed")
    return False, "no harness-issued violation"


def transcript_block(meta, res):
    if res["violation"]:
        verdict = "REPRODUCED — exited 0 and demonstrated a disagreement"
    elif res["exit"]:
        verdict = f"NOT REPRODUCED — exit {res['exit']}"
    else:
        verdict = "NOT REPRODUCED — " + res.get("why", "no VIOLATION line")
    return (f"### repro {meta.get('id', '?')} "
            f"[{meta.get('severity', '?')}] {meta.get('title', '')}\n"
            f"HARNESS VERDICT: {verdict}\n"
            f"--- stdout ---\n{res['stdout'] or '(empty)'}\n"
            f"--- stderr ---\n{res['stderr'] or '(empty)'}\n"
            f"--- exit: {res['exit']} ---\n")


def slice_section(path, start, end, ref="HEAD"):
    txt = read_at(ref, path).decode("utf-8", "replace")
    i = txt.find(start)
    if i < 0:
        return txt
    j = txt.find(end, i + 1)
    return txt[i:] if j < 0 else txt[i:j]


def pack(paths, ref="HEAD"):
    out = []
    for p in paths:
        try:
            out.append(f"===== FILE: {p} =====\n"
                       f"{read_at(ref, p).decode('utf-8', 'replace')}")
        except subprocess.CalledProcessError:
            continue
    return "\n\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="wrt-002", choices=sorted(TARGETS))
    ap.add_argument("--out", required=True, help="reviews/<file>.md")
    ap.add_argument("--model", default=os.environ.get("OPENROUTER_MODEL"))
    ap.add_argument("--ref", default="HEAD",
                    help="git ref to review; resolved to a commit and pinned for "
                         "the run, so a branch moving cannot change the subject")
    ap.add_argument("--local", help="ollama model name; runs on this machine, no key, no bill")
    ap.add_argument("--cli", help="path to a local agent CLI (kimi, codex); "
                                   "when set, OpenRouter is not used")
    ap.add_argument("--family", help="reviewer family id for settlement, e.g. "
                                     "kimi@moonshot; defaults to the model's vendor prefix")
    args = ap.parse_args()
    if not (args.model or args.cli or args.local):
        sys.exit("set --model, OPENROUTER_MODEL, --cli, or --local")
    args.model = args.model or args.local or args.cli
    _api = call
    if args.local:
        def _api(model, messages, **kw):                    # noqa: ARG001
            return call_local(args.local, messages)
    elif args.cli:
        def _api(model, messages, **kw):                    # noqa: ARG001
            return call_cli(args.cli, model, messages)

    t = TARGETS[args.target]
    # Pin to a commit NOW: a symbolic ref would still follow a branch that moves
    # under a run taking an hour.
    args.ref = subprocess.run(["git", "-C", str(ROOT), "rev-parse", args.ref],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    nonce = secrets.token_hex(8)   # unguessable, so a hand-written line cannot forge it
    print(f"[gate] reviewing commit {args.ref[:12]}", file=sys.stderr)
    workdir = stage_workdir(t, args.ref) if t.get("stage") else ROOT / t["workdir"]

    # The baseline must already pass, or a 'finding' could just be a broken tree.
    base = subprocess.run(t["baseline"], cwd=workdir, capture_output=True, text=True)
    if t["baseline_expect"] not in base.stdout:
        sys.exit(f"baseline did not pass; refusing to review a broken tree:\n{base.stdout[-2000:]}")
    print(f"[gate] baseline: {t['baseline_expect']}", file=sys.stderr)

    repro_rules = REPRO_RULES.replace("MODULE", t.get("module", "model"))
    brief = (ROOT / t["brief"]).read_text()
    normative = slice_section(*t["normative"], ref=args.ref)
    sources = pack(t["sources"], args.ref)

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
            res = run_repro(workdir, code, nonce)
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
    subject_sha256 = subject_hash(t, args.ref)
    family = args.family or (args.model.split("/")[0] if "/" in args.model else args.model)
    ledger = {
        "item": args.target,
        "family": family,
        "model": args.model,
        "host": socket.gethostname(),
        "produced_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "subject_sha256": subject_sha256,
        "subject_label": t["subject"],
        # The document a clause number refers to. `D.3` identifies nothing on its
        # own, and two targets numbering their own D.3 collided into one claim.
        "document": t["normative"][0],
        "reviewed_ref": args.ref,
        "review": args.out,
        "complete": complete,
        "findings": [{
            "id": meta.get("id"),
            "severity": (meta.get("severity") or "P?").upper(),
            "clause": meta.get("clause", ""),
            "closes": meta.get("closes", ""),
            "title": meta.get("title", ""),
            "repro_sha256": hashlib.sha256(code.encode("utf-8")).hexdigest(),
            "transcript_sha256": hashlib.sha256(
                (res["stdout"] + res["stderr"] + str(res["exit"])).encode("utf-8")
            ).hexdigest(),
            # The preimages travel WITH their hashes. A first version stored only
            # the digests, which survived a crashed run in the sense that the
            # fact survived and the evidence did not -- leaving a finding nobody
            # could read, judge, or re-run. A hash shipped without its preimage
            # is an assertion, and this file exists to hold the opposite.
            "repro": code,
            "transcript": {"stdout": res["stdout"], "stderr": res["stderr"],
                           "exit": res["exit"]},
            "exit": res["exit"],
            "reproduced": res["violation"],
            "outcome": res.get("outcome", "refuted" if not res["violation"] else "violation"),
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
