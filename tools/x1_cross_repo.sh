#!/usr/bin/env bash
# X1 — cross-repo coupling gate (warrant <-> sigma-glyph), HEAD against HEAD.
#
# WHY THIS EXISTS
# ---------------
# Both repos already pin the sibling BY COMMIT, deliberately, for reproducible
# conformance. That is correct and this script does not replace it.
#
# But a pin is a *snapshot*: a change on either HEAD is invisible until a human
# bumps the pin by hand. Measured on 2026-07-27, the pins had drifted 19 days
# apart -- sigma-glyph's CI pinned three DIFFERENT warrant commits at once
# (2026-07-08 / 07-17 / 07-27) and warrant's CI pinned a sigma commit older than
# its last 50. So each repo was testing against a fractured historical composite
# of the other, and no job anywhere ran HEAD against HEAD.
#
# X1 is the canary for exactly that gap: pinned jobs stay the reproducibility
# gate; this one is the early warning. A red X1 with green pinned jobs means the
# seam moved.
#
# WHAT THIS IS NOT
# ----------------
# This is a REGRESSION gate, not an independent adversarial gate (AGENTS.md §3).
# It runs suites. It hunts no counter-vectors. Green here is necessary, never
# sufficient, and must never be reported as "independently gated".
#
# STRICT BY DEFAULT
# A crossing that cannot run is not a crossing that passed. X1 used to `c_skip`
# A1/A2/C2 when the Go toolchain or build was unavailable and still print
# ALL PASS -- so a sibling whose Go code did not compile produced a green gate
# with no Go implementation tested at all (Codex X1 gate, P1). Now every skip of
# a required crossing is a FAILURE unless X1_DEGRADED=1 is set explicitly, which
# is for local exploration only and must never be set in CI.
#
# THE LANDING SEAM (read before merging this to either master)
# A cross-repo merge is not atomic, so the FIRST of the two master merges
# necessarily sees the sibling's master without X1 — a real mirror-absence, and
# under the rules above a red gate. That window is expected and must be crossed
# deliberately, not papered over by leaving absence permanently skippable:
#
#   1. merge on one master (explicitly authorised; X1 there will be red on E
#      until step 2, and that redness is CORRECT);
#   2. merge on the other master immediately — this is not a step to postpone;
#   3. re-run X1 strict on BOTH masters and require ALL PASS;
#   4. only then update the reproducible sibling pins, in their own commit.
#
# X1_BOOTSTRAP=1 exists for step 1 alone and CI never sets it.
#
# USAGE
#   tools/x1_cross_repo.sh                 # clone sibling at HEAD, strict
#   SIBLING=/path/to/sibling tools/x1_cross_repo.sh   # use a local checkout
#   X1_SEEDS="1 2 3" tools/x1_cross_repo.sh           # more fuzzer seeds
#   X1_DEGRADED=1 tools/x1_cross_repo.sh              # allow skips (NOT for CI)
#   X1_BOOTSTRAP=1 tools/x1_cross_repo.sh             # sibling has no X1 yet
set -uo pipefail

FAIL=0
PASS=0
SKIP=0
DEGRADED="${X1_DEGRADED:-0}"
declare -a FAILED_STEPS=()

c_ok()   { printf '  \033[32mOK\033[0m    %s\n' "$1"; PASS=$((PASS+1)); }
c_bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; FAIL=$((FAIL+1)); FAILED_STEPS+=("$1"); }
# A required crossing that did not run. Fatal unless explicitly degraded.
c_skip() {
  if [ "$DEGRADED" = "1" ]; then
    printf '  \033[33mSKIP\033[0m  %s  (X1_DEGRADED=1)\n' "$1"; SKIP=$((SKIP+1))
  else
    printf '  \033[31mFAIL\033[0m  %s  <- required crossing did not run\n' "$1"
    FAIL=$((FAIL+1)); FAILED_STEPS+=("$1 (did not run)")
  fi
}
hdr()    { printf '\n\033[1m%s\033[0m\n' "$1"; }

# run <label> <command...> : pass iff exit 0
run() { local label="$1"; shift; local out
        if out=$("$@" 2>&1); then c_ok "$label"
        else c_bad "$label"; printf '%s\n' "$out" | tail -15 | sed 's/^/        | /'; fi; }

# run_grep <label> <needle> <command...> : pass iff exit 0 AND stdout matches.
# `needle` is matched literally (-F): callers pass computed coverage strings that
# contain regex metacharacters.
run_grep() { local label="$1" needle="$2"; shift 2; local out
        if out=$("$@" 2>&1) && printf '%s' "$out" | grep -qF -- "$needle"; then c_ok "$label"
        else c_bad "$label (expected: $needle)"; printf '%s\n' "$out" | tail -15 | sed 's/^/        | /'; fi; }

# ---------------------------------------------------------------- locate repos
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if   [ -f "$SELF/SPEC.md" ] && [ -d "$SELF/impl-go" ] && grep -qi '^# Warrant' "$SELF/README.md" 2>/dev/null; then
  OWN=warrant
elif [ -d "$SELF/spec" ] && [ -f "$SELF/spec/book-1-truth.md" ]; then
  OWN=sigma-glyph
else
  echo "X1: cannot tell which repo this is (looked in $SELF)" >&2; exit 2
fi
SIB_NAME=$([ "$OWN" = warrant ] && echo sigma-glyph || echo warrant)

if [ -n "${SIBLING:-}" ]; then
  SIB="$SIBLING"
  [ -d "$SIB" ] || { echo "X1: SIBLING=$SIB does not exist" >&2; exit 2; }
else
  SIB="$(mktemp -d)/$SIB_NAME"
  echo "X1: cloning $SIB_NAME at HEAD (no pin) ..."
  git clone -q --depth 50 "https://github.com/s0fractal/$SIB_NAME.git" "$SIB" \
    || { echo "X1: clone failed" >&2; exit 2; }
fi

WARRANT=$([ "$OWN" = warrant ] && echo "$SELF" || echo "$SIB")
SIGMA=$(  [ "$OWN" = warrant ] && echo "$SIB"  || echo "$SELF")

hdr "X1 cross-repo coupling gate — HEAD vs HEAD"
echo "  own      : $OWN      $(git -C "$SELF" log -1 --format='%h %ad' --date=short 2>/dev/null)"
echo "  sibling  : $SIB_NAME $(git -C "$SIB"  log -1 --format='%h %ad' --date=short 2>/dev/null)"

# ------------------------------------------------------------------- toolchain
have() { command -v "$1" >/dev/null 2>&1; }
have python3 || { echo "X1: python3 required" >&2; exit 2; }
python3 -c 'import cryptography' 2>/dev/null || echo "  note: python 'cryptography' missing -> signature steps may skip"

WGO=""
if have go; then
  if (cd "$WARRANT/impl-go" && go build -o warrant-go . >/dev/null 2>&1); then
    WGO="$WARRANT/impl-go/warrant-go"
  fi
fi

# ================================================================= the crossings
hdr "A. Book I consensus — warrant's Go evaluator vs sigma's vectors"

if [ -n "$WGO" ]; then
  # Bind ALL PASS to the ACTUAL coverage, derived from the vector file itself.
  # Matching the bare substring "ALL PASS" is what let warrant-go report success
  # over 33 of 49 vectors for weeks (Codex X1 gate, P1): a summary line is only
  # evidence if the number in it is checked against the suite it claims to cover.
  # The expected string is computed here, so adding a vector or a whole new kind
  # tightens the assertion automatically instead of loosening it.
  COVERAGE="$(python3 - "$SIGMA/tests/spec_conformance/vectors.json" <<'PY'
import collections, json, sys
d = json.load(open(sys.argv[1]))
vs = d["vectors"]
c = collections.Counter(v.get("kind") for v in vs)
kinds = ", ".join(f"{c[k]} {k}" for k in sorted(c))
print(f"ALL PASS ({len(vs)}/{len(vs)} — {kinds})")
PY
)"
  if [ -z "$COVERAGE" ]; then
    c_bad "A1 could not derive expected coverage from sigma's vectors.json"
  else
    run_grep "A1 warrant-go sigma-conformance, exact coverage ${COVERAGE#ALL PASS }" \
      "$COVERAGE" "$WGO" sigma-conformance "$SIGMA/tests/spec_conformance/vectors.json"
  fi
else
  c_skip "A1 warrant-go sigma-conformance (go toolchain or build unavailable)"
fi

if [ -n "$WGO" ] && [ -f "$SIGMA/tests/book1_fuzz.py" ]; then
  for seed in ${X1_SEEDS:-1 2}; do
    run_grep "A2 three-way book1 differential fuzzer (seed=$seed)" "ALL AGREE" \
      env WARRANT_GO="$WGO" python3 "$SIGMA/tests/book1_fuzz.py" --seed "$seed"
  done
else
  c_skip "A2 book1 differential fuzzer"
fi

hdr "B. Machine boundary — sigma's store through warrant's verifier"

# ok:true AND grade/counts must be internally consistent: errors==0 <=> ok
run_grep "B1 warrant HEAD verifies sigma HEAD .warrants (verify-report@v0)" '"ok": true' \
  env SIGMA_GLYPH="$SIGMA/impl" python3 - "$WARRANT/impl/warrant.py" "$SIGMA/.warrants" <<'PY'
import json, subprocess, sys
wp, store = sys.argv[1], sys.argv[2]
p = subprocess.run([sys.executable, wp, "--store", store, "verify", "--store-mode", "--json"],
                   capture_output=True, text=True)
# The report is only half the boundary. Discarding the exit status accepts a
# verifier that prints ok:true and exits non-zero, and discarding stderr accepts
# one that pollutes a stream documented as carrying exactly one JSON object
# (Codex X1 gate, P2). Bind all three to each other.
#
# Check RAW stdout, before any normalisation. The first version of this assertion
# ran `.strip()` and then counted newlines, which is vacuous: strip removes the
# very characters the check is about, so a leading blank line, two trailing
# newlines, and a whitespace-only suffix line all passed as "exactly one physical
# line" (Codex X1 re-gate, P2). The contract is that stdout is the JSON object
# and at most one terminating newline -- nothing else.
raw = p.stdout
assert p.stderr == "", f"verifier wrote to stderr: {p.stderr[:300]!r}"
out = raw[:-1] if raw.endswith("\n") else raw
assert out, "verifier produced no report on stdout"
assert "\n" not in out, (
    "stdout must be the report and at most ONE terminating newline; got "
    f"{raw[:120]!r}")
assert out == out.strip(), f"stdout carries stray whitespace around the report: {raw[:120]!r}"
r = json.loads(out)
assert p.returncode == (0 if r["ok"] else 1), \
    f"exit {p.returncode} disagrees with ok={r['ok']} (expected 0 iff ok)"
assert r["report"] == "warrant.verify-report@v0", r["report"]
assert r["ok"] == (r["errors"] == 0), "ok/errors disagree"
assert r["errors"] == sum(1 for f in r["findings"] if f["level"] == "ERR"), "errors != ERR findings"
assert r["warnings"] == sum(1 for f in r["findings"] if f["level"] == "WARN"), "warnings != WARN findings"
assert set(r) == {"report","grade","ok","records","errors","warnings","findings"}, "schema not closed"
print(json.dumps({k: r[k] for k in ("grade","ok","records","errors","warnings")}, indent=None))
print("ok: true" if r["ok"] else "ok: false")
PY

if [ -f "$SIGMA/tools/warrant_gate.py" ]; then
  run_grep "B2 sigma's warrant_gate.py connector against warrant HEAD" "VERIFIED" \
    env SIGMA_GLYPH="$SIGMA/impl" WARRANT="python3 $WARRANT/impl/warrant.py" \
        WARRANT_PY="$WARRANT/impl/warrant.py" \
    python3 "$SIGMA/tools/warrant_gate.py" "$SIGMA/.warrants" --settlement \
        --trust-config "$SIGMA/trust-config.json"
else
  c_skip "B2 warrant_gate.py connector"
fi

hdr "C. Reverse direction — warrant's ski@v1 against sigma's HEAD oracle"

run_grep "C1 warrant conformance with SIGMA_GLYPH=sigma HEAD" "ALL PASS" \
  env SIGMA_GLYPH="$SIGMA/impl" python3 "$WARRANT/impl/warrant.py" conformance "$WARRANT/examples"

if [ -n "$WGO" ]; then
  run_grep "C2 warrant-go conformance (own vectors, sibling-built binary)" "ALL PASS" \
    "$WGO" conformance "$WARRANT/examples"
else
  c_skip "C2 warrant-go conformance"
fi

hdr "D. Governance coupling — the out-of-band anchor trust"

run "D1 warrant's sigma anchor-trust parses and names sigma's roster" \
  python3 - "$WARRANT/trust/sigma-glyph-anchor-trust.json" "$SIGMA/trust-config.json" <<'PY'
import json, sys
trust = json.load(open(sys.argv[1]))
sigma = json.load(open(sys.argv[2]))
ta = set(trust.get("actors", {}))
sa = set(sigma.get("actors", {}))
assert ta, "anchor-trust names no actors"
missing = ta - sa
extra   = sa - ta
if missing or extra:
    raise SystemExit(f"roster drift: only-in-warrant-trust={sorted(missing)} only-in-sigma={sorted(extra)}")
for a, keys in trust["actors"].items():
    assert trust["actors"][a] == sigma["actors"][a], f"key drift for {a}"
print(f"roster agrees: {sorted(ta)}")
PY

if [ -f "$SIGMA/tools/verify_anchors.py" ]; then
  run_grep "D2 sigma anchors verify at HEAD" "anchors verified" \
    bash -c "cd '$SIGMA' && python3 tools/verify_anchors.py"
else
  c_skip "D2 anchor verification"
fi

hdr "E. Mirror integrity — the gate itself is the same gate on both sides"

# X1 only means anything if both repos run the SAME X1. Nothing else checks
# that, so a well-meaning fix on one side would silently turn one coupling gate
# into two different ones.
#
# ABSENCE IS FATAL, NOT A SKIP. Treating a missing mirror as "landing in
# progress" is a permanent bypass once landing is done (Codex X1 gate, P1):
# delete X1 from one repo and its workflow stops running, while the surviving
# repo sees the file absent, skips, and stays green — so the gate can be removed
# from the coupling without either side going red. The bootstrap window is now
# explicit and opt-in: X1_BOOTSTRAP=1 for the single landing where one side has
# X1 and the other does not. CI never sets it.
BOOTSTRAP="${X1_BOOTSTRAP:-0}"
for f in tools/x1_cross_repo.sh tools/x1_negative_control.sh .github/workflows/x1-cross-repo.yml; do
  if [ ! -f "$SIB/$f" ]; then
    if [ "$BOOTSTRAP" = "1" ]; then
      printf '  \033[33mSKIP\033[0m  E:%s absent in %s (X1_BOOTSTRAP=1)\n' "$f" "$SIB_NAME"
      SKIP=$((SKIP+1))
    else
      c_bad "E:$f is MISSING from $SIB_NAME — the gate was removed from one side"
    fi
  elif [ "$(shasum -a 256 "$SELF/$f" | awk '{print $1}')" = "$(shasum -a 256 "$SIB/$f" | awk '{print $1}')" ]; then
    c_ok "E:$f byte-identical in both repos"
  else
    c_bad "E:$f DIFFERS between the repos — the two sides are not running the same gate"
    diff -u "$SIB/$f" "$SELF/$f" | head -20 | sed 's/^/        | /'
  fi
done

# ================================================================== pin drift
hdr "F. Pin drift report (informational — never fails the gate)"

python3 - "$WARRANT" "$SIGMA" <<'PY'
import re, subprocess, sys, pathlib
warrant, sigma = sys.argv[1], sys.argv[2]

def pins(repo, sibling_name):
    found = []
    for wf in pathlib.Path(repo, ".github/workflows").glob("*.yml"):
        txt = wf.read_text(errors="replace")
        if wf.name.startswith("x1"):
            continue
        for m in re.finditer(r"\b([0-9a-f]{40})\b", txt):
            found.append(m.group(1))
    return sorted(set(found))

def describe(repo, sha):
    r = subprocess.run(["git", "-C", repo, "log", "-1", "--format=%h %ad %s", "--date=short", sha],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None

for own, sib, sib_name in ((warrant, sigma, "sigma-glyph"), (sigma, warrant, "warrant")):
    name = pathlib.Path(own).name
    ps = pins(own, sib_name)
    if not ps:
        continue
    print(f"  {name}'s CI pins of {sib_name}:")
    dates = []
    for sha in ps:
        d = describe(sib, sha)
        if d:
            print(f"    {d}")
            dates.append(d.split()[1])
        else:
            print(f"    {sha[:8]}  (not in the sibling's fetched history — stale beyond --depth)")
    if len(set(dates)) > 1:
        print(f"    ^ {len(set(dates))} DIFFERENT sibling commits pinned at once: {min(dates)} .. {max(dates)}")
PY

# ===================================================================== verdict
hdr "X1 RESULT"
MODE="$([ "$DEGRADED" = 1 ] && echo DEGRADED || echo strict)"
[ "${X1_BOOTSTRAP:-0}" = 1 ] && MODE="$MODE+bootstrap"
printf '  pass=%d fail=%d skip=%d  (mode: %s)\n' "$PASS" "$FAIL" "$SKIP" "$MODE"
if [ "$FAIL" -eq 0 ] && [ "$SKIP" -eq 0 ]; then
  echo "  X1-CROSS-REPO: ALL PASS  (regression gate only — NOT an independent gate)"
  exit 0
elif [ "$FAIL" -eq 0 ]; then
  # Only reachable under X1_DEGRADED / X1_BOOTSTRAP. Never call this a pass: the
  # finding was precisely that a green summary printed over crossings that never
  # ran reads to a human as coverage.
  printf '  X1-CROSS-REPO: INCOMPLETE — %d required crossing(s) did not run.\n' "$SKIP"
  echo "  Not a pass. CI runs strict, with zero skips."
  exit 1
else
  printf '  X1-CROSS-REPO: FAIL\n'
  for s in "${FAILED_STEPS[@]}"; do printf '    - %s\n' "$s"; done
  exit 1
fi
