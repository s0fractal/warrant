#!/usr/bin/env bash
# X1 negative control — prove the coupling gate is CAPABLE of going red.
#
# WHY THIS IS A SEPARATE SCRIPT
# -----------------------------
# A gate that cannot fail is not a gate. X1 asserts agreement between two repos;
# if an assertion were mis-wired, X1 would report ALL PASS forever and nobody
# would find out. So on every CI run we hand X1 a deliberately corrupted sibling
# and require it to reject it — at the step we predicted.
#
# Every rule below was written because a draft of this file broke it:
#
#   * The first draft lived inline in the workflow and tampered
#     `tests/spec_conformance/vectors.json`, which exists only in sigma-glyph.
#     From sigma's side (sibling = warrant) it found nothing to tamper, exited 0
#     and went green having tested NOTHING — the vacuous green it was written to
#     prevent.
#   * The second corrupted "the first 64-hex string" in that file. That is
#     `book1_anchor`, which A1 does not read: X1 went red at D2 while the Book I
#     consensus check sailed through.
#   * The third targeted `vectors[0].expected` — correct in form, but vector 0 is
#     `OBJ-I`, kind=`object`. So it proved only that ONE object vector is read,
#     while `eval` and `deserialize` — 41 of the 49 — had no control at all
#     (Codex X1 gate, P1). A regression that silently dropped every deserialize
#     vector would have left this file green.
#
# RULES
#   1. Every control names the X1 step it must turn red, and passes only if THAT
#      step is among the failures. "X1 exited non-zero" is not enough — a missing
#      interpreter would satisfy it.
#   2. A control that finds nothing to tamper is a HARD ERROR, never a skip.
#   3. Controls corrupt a field that is *semantically load-bearing for the named
#      step*, not merely a byte inside a file the step happens to hash.
#   4. Each vector KIND gets its own control. Per-kind coverage is a claim, and a
#      claim with no control behind it is the thing X1 exists to catch.
#   5. Both directions run, and each direction is told out loud which controls do
#      not apply to it.
#   6. A tampering control runs X1 with `--only=<step>` for the step it must
#      turn red. Measured 2026-09-04, every control was paying ~15 s for an A2
#      fuzzer seed it never read; the step it does read takes under a second.
#      The must-fail predicate is unchanged: the selected run must exit non-zero
#      AND be red at the named step. The hostile-environment control (10) keeps
#      running the FULL matrix, because "ambient state does not alter X1" is a
#      claim about every step. Selection is itself a surface, so it gets its own
#      controls: invalid selectors must refuse before any work, a selected step
#      that executes nothing must fail, and a selected pass must never carry the
#      full-matrix ALL PASS label.
#   7. Nonexecution is not a negative. X1 prints a FAIL line for a step that
#      recorded no outcome ("<step> did not execute") and, strict, for a
#      crossing it skipped ("required crossing did not run"). Neither line says
#      the step's predicate rejected its mutated operand: the predicate never
#      met the operand. The first --only draft credited them -- with the C1
#      guard disabled for selected runs only, the C1 control stayed green on a
#      C1 that never ran (Codex review, P1). A tampering control now requires a
#      real outcome at the named step; only the unbuildable-Go control, whose
#      intended predicate IS "an unrun crossing is fatal", accepts the skip
#      line, and nothing accepts the no-outcome guard. The oracle itself has a
#      control (below) that replays that exact mutation.
#
#   SIBLING=/path/to/sibling tools/x1_negative_control.sh
set -uo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
X1="$SELF/tools/x1_cross_repo.sh"
[[ -f "$X1" ]] || { echo "negative-control: $X1 not found" >&2; exit 2; }
[[ -n "${SIBLING:-}" ]] || { echo "negative-control: set SIBLING=/path/to/sibling" >&2; exit 2; }
[[ -d "$SIBLING" ]] || { echo "negative-control: SIBLING=$SIBLING does not exist" >&2; exit 2; }

RAN=0
BAD=0

# control <name> <must-fail-step> <selected-step> <python-tamper-script> [expect]
#   The tamper script receives the tampered-copy root as argv[1]; it must exit 0
#   after mutating something, or non-zero if it had nothing to mutate.
#   <selected-step> is handed to X1 as --only=, so the run executes that step
#   and its preparation only. <must-fail-step> is the predicate as before: the
#   grep needle that must appear on a FAIL line (E's labels are "E:<file>").
#   [expect] is `outcome` (default): the red line at the named step must be an
#   outcome of the step's own predicate; or `unrun`: the red line must be the
#   strict-mode "required crossing did not run" skip -- for the one control
#   whose predicate is that skips are fatal. Neither accepts the end-of-run
#   "<step> did not execute" guard (rule 7).
#   Runs whatever $X1 names: the oracle control below points it at a mutated
#   copy of this very gate and requires the verdict to be FAIL.
control() {
  local name="$1" needle="$2" only="$3" script="$4" expect="${5:-outcome}"
  local tmp; tmp="$(mktemp -d)"
  local work="$tmp/sibling"
  cp -R "$SIBLING" "$work"

  if ! python3 -c "$script" "$work"; then
    echo "  FAIL  $name — nothing to tamper (a control that tampers nothing is vacuous)"
    # Counted as attempted: it is already counted in BAD, and leaving it out of
    # RAN made the summary denominator disagree with itself (see below).
    RAN=$((RAN+1)); BAD=$((BAD+1)); rm -rf "$tmp"; return
  fi

  local out rc
  out="$(SIBLING="$work" X1_SEEDS=1 bash "$X1" --only="$only" 2>&1)"; rc=$?
  rm -rf "$tmp"
  RAN=$((RAN+1))

  if [[ $rc -eq 0 ]]; then
    echo "  FAIL  $name — X1 PASSED on a tampered sibling; the gate is vacuous"
    BAD=$((BAD+1)); return
  fi
  # Non-zero exit is necessary but not sufficient: require the *predicted* step
  # to be red, so an unrelated breakage cannot masquerade as proof of coverage.
  # A refused selector exits 2 with no FAIL line at all and lands here too.
  #
  # And red at the step is still not sufficient. The step's predicate must have
  # MET the tampered operand: a step that recorded no outcome is red by the
  # end-of-run guard, and a skipped crossing is red by strict mode, and neither
  # says anything about the predicate. The first draft accepted `FAIL.*C1` from
  # the guard as proof that C1 rejected its operand (Codex review, P1).
  if printf '%s' "$out" | grep -q "FAIL.*$only did not execute"; then
    echo "  FAIL  $name — X1 never executed $only (no outcome recorded); a predicate that did not run rejected nothing:"
    printf '%s\n' "$out" | grep -E 'FAIL|pass=|refused' | sed 's/^/        | /'
    BAD=$((BAD+1)); return
  fi
  local red; red="$(printf '%s' "$out" | grep "FAIL.*$needle")"
  case "$expect" in
    outcome) red="$(printf '%s' "$red" | grep -v 'required crossing did not run')";;
    unrun)   red="$(printf '%s' "$red" | grep    'required crossing did not run')";;
    *) echo "negative-control: bad expect '$expect' for '$name'" >&2; exit 2;;
  esac
  if [[ -n "$red" ]]; then
    echo "  OK    $name — X1 red at the predicted step ($needle; --only=$only; $expect)"
  else
    echo "  FAIL  $name — X1 failed, but NOT with a $expect at '$needle'. Red for the wrong reason:"
    printf '%s\n' "$out" | grep -E 'FAIL|pass=|refused' | sed 's/^/        | /'
    BAD=$((BAD+1))
  fi
  return 0
}

# selector_refusal <name> <x1-args...> — X1 must refuse the selector with exit 2
# and its refusal marker BEFORE touching anything. SIBLING points at a path that
# does not exist, so a run that got as far as locating the sibling would fail
# later and differently ("does not exist"), and that is a FAIL here.
selector_refusal() {
  local name="$1"; shift
  local out rc
  out="$(SIBLING="$SELF/x1-sibling-that-does-not-exist" bash "$X1" "$@" 2>&1)"; rc=$?
  RAN=$((RAN+1))
  if [[ $rc -eq 2 ]] && grep -q '^X1: refused:' <<<"$out" \
       && ! grep -qE 'does not exist|X1 RESULT|X1-CROSS-REPO' <<<"$out"; then
    echo "  OK    $name — refused (exit 2) before any work"
  else
    echo "  FAIL  $name — expected exit 2 and an 'X1: refused:' line before any work; got exit $rc:"
    printf '%s\n' "$out" | tail -5 | sed 's/^/        | /'
    BAD=$((BAD+1))
  fi
  return 0
}

# vector_tamper <kind> <field> <hex|bool> — flip one expected field of the first
# vector of that kind, so each control names the class it is responsible for.
vector_tamper() {
  cat <<PYEOF
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "tests/spec_conformance/vectors.json"
d = json.loads(p.read_text())
for v in d.get("vectors", []):
    if v.get("kind") != "$1":
        continue
    exp = v.get("expected")
    if not isinstance(exp, dict) or "$2" not in exp:
        continue
    val = exp["$2"]
    if "$3" == "hex":
        if not (isinstance(val, str) and len(val) == 64):
            continue
        exp["$2"] = val[:-1] + ("0" if val[-1] != "0" else "1")
    else:
        if not isinstance(val, bool):
            continue
        exp["$2"] = not val
    p.write_text(json.dumps(d))
    sys.exit(0)
sys.exit(1)
PYEOF
  return 0
}

echo "X1 negative controls (sibling: $SIBLING)"

# --------------------------------------------------------------------------
# Control 1 — governance roster (D1). Works from BOTH directions: D1 compares
# warrant/trust/sigma-glyph-anchor-trust.json against sigma/trust-config.json,
# and exactly one of those two files lives in the sibling, whichever side we
# are on. This is the control that makes neither direction vacuous.
# The tamper is named so the oracle control (last) can replay it unchanged.
# --------------------------------------------------------------------------
ROSTER_TAMPER='
import json, sys, pathlib
root = pathlib.Path(sys.argv[1])

def bend(x):
    if isinstance(x, str) and len(x) > 8:
        return x[:-1] + ("A" if x[-1] != "A" else "B")
    if isinstance(x, list) and x:
        return [bend(x[0])] + list(x[1:])
    if isinstance(x, dict):
        for k in x:
            b = bend(x[k])
            if b is not None and b != x[k]:
                x[k] = b
                return x
    return None

for rel in ("trust/sigma-glyph-anchor-trust.json", "trust-config.json"):
    p = root / rel
    if not p.exists():
        continue
    d = json.loads(p.read_text())
    actors = d.get("actors") or {}
    if not actors:
        continue
    a = sorted(actors)[0]
    nv = bend(actors[a])
    if nv is None or nv == actors[a]:
        continue
    actors[a] = nv
    p.write_text(json.dumps(d, indent=2))
    sys.exit(0)
sys.exit(1)
'
control "roster key swap must break D1" "D1" D1 "$ROSTER_TAMPER"

# --------------------------------------------------------------------------
# Controls 2-4 — ONE PER VECTOR KIND (A1). sigma-glyph holds the vectors, so
# these apply only when the sibling is sigma. Together they are the teeth
# behind A1's per-kind coverage assertion: object, eval and deserialize must
# each be genuinely executed by warrant-go for X1 to be green.
# --------------------------------------------------------------------------
if [[ -f "$SIBLING/tests/spec_conformance/vectors.json" ]]; then
  control "flipped object expected.hash must break A1"        "A1" A1 "$(vector_tamper object hash hex)"
  control "flipped eval expected.result_hash must break A1"   "A1" A1 "$(vector_tamper eval result_hash hex)"
  control "inverted deserialize expected.valid must break A1" "A1" A1 "$(vector_tamper deserialize valid bool)"

  # The positional rule needs teeth of its own. This forges the expected summary
  # as a standalone line via a newline inside a vector id, AND makes that vector
  # fail, so the producer's real last line is FAILURES PRESENT. A line-anchored
  # matcher accepts this; a position-anchored one cannot.
  control "a forged summary line above a FAILING run must break A1" "A1" A1 '
import collections, copy, json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "tests/spec_conformance/vectors.json"
d = json.loads(p.read_text())
vs = d.get("vectors") or []
ev = next((v for v in vs if v.get("kind") == "eval"), None)
if ev is None:
    sys.exit(1)
clone = copy.deepcopy(ev)
vs.append(clone)
kinds = collections.Counter(v.get("kind") for v in vs)
detail = ", ".join(f"{kinds[k]} {k}" for k in sorted(kinds))
n = len(vs)
forged = f"SIGMA CONFORMANCE: ALL PASS ({n}/{n} — {detail})"
clone["id"] = "\\n" + forged + "\\nFORGED-END"
h = clone["expected"]["result_hash"]
clone["expected"]["result_hash"] = h[:-1] + ("0" if h[-1] != "0" else "1")
p.write_text(json.dumps(d))
sys.exit(0)
'

  # A suite that grows a class the evaluator has never heard of must not pass.
  # This is the forward-looking half of per-kind coverage: the three controls
  # above pin the kinds that exist today, this one pins what happens when a new
  # one appears.
  control "a vector of an UNKNOWN kind must break A1" "A1" A1 '
import copy, json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "tests/spec_conformance/vectors.json"
d = json.loads(p.read_text())
vs = d.get("vectors") or []
if not vs:
    sys.exit(1)
clone = copy.deepcopy(vs[0])
clone["id"] = "NEW-CLASS-1"
clone["kind"] = "quantum"
vs.append(clone)
p.write_text(json.dumps(d))
sys.exit(0)
'
else
  echo "  n/a   per-kind Book I controls — the sibling holds no vectors.json"
  echo "        (we are sigma-glyph; A1 reads OUR vectors, and CI must not corrupt those)"
fi

# --------------------------------------------------------------------------
# Controls 5-6 — reverse direction.  C1 proves sigma HEAD cannot silently be
# substituted for pinned ski@v1; C2 is the explicit, non-crediting differential
# that actually runs warrant's vectors against sigma HEAD.  warrant holds the
# implementation and examples/, so these apply only when the sibling is warrant.
# --------------------------------------------------------------------------
if [[ -f "$SIBLING/examples/ski/check.json" ]]; then
  control "removing the unpinned boundary must break C1" "C1" C1 '
import sys, pathlib
p = pathlib.Path(sys.argv[1]) / "impl/warrant.py"
s = p.read_text()
old = "os.environ.get(\"WARRANT_SIGMA_DIFFERENTIAL\") != \"1\":"
new = "os.environ.get(\"WARRANT_SIGMA_DIFFERENTIAL\") == \"1\":"
if s.count(old) != 1:
    sys.exit(1)
p.write_text(s.replace(old, new))
sys.exit(0)
'

  control "corrupted ski check-blob must break C2" "C2" C2 '
import json, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "examples/ski/check.json"
d = json.loads(p.read_text())
if "atp" not in d:
    sys.exit(1)
d["atp"] = int(d["atp"]) + 1          # changes the blob hash AND the budget
p.write_text(json.dumps(d, separators=(",", ":"), sort_keys=True))
sys.exit(0)
'
else
  echo "  n/a   ski check-blob corruption — the sibling holds no examples/ski"
  echo "        (we are warrant; C2 reads OUR examples, and CI must not corrupt those)"
fi

# --------------------------------------------------------------------------
# Control 7 — gate REMOVAL must go red (E). Divergence was already detected;
# deletion was not, and deletion is the cheaper attack: drop X1 from one repo
# and its workflow simply stops running, while the other side used to skip and
# stay green (Codex X1 gate, P1). Runs from both directions.
# --------------------------------------------------------------------------
control "deleting a mirrored X1 file must break E" "E:" E '
import sys, pathlib
root = pathlib.Path(sys.argv[1])
for rel in ("tools/x1_negative_control.sh", "tools/x1_cross_repo.sh",
            "tools/book1_coverage.py", ".github/workflows/x1-cross-repo.yml"):
    p = root / rel
    if p.exists():
        p.unlink()
        sys.exit(0)
sys.exit(1)
'

# --------------------------------------------------------------------------
# Control 8 — an unbuildable sibling must NOT be green (A1). warrant-go is
# built from the warrant tree, so this control exists exactly when the sibling
# is warrant. It is the direct countervector for "required Go crossings can
# silently SKIP and the job still passes".
# --------------------------------------------------------------------------
# Note the guard: sigma-glyph ALSO has an impl-go (its federation implementation),
# so "the sibling has a Go tree" is not the question. A1 builds *warrant's*
# evaluator, so this control applies exactly when the sibling IS warrant — the
# same detection X1 itself uses.
# `unrun` is deliberate and unique to this control: its predicate is that the
# strict gate turns an unrun crossing red, so the skip line IS the outcome it
# predicts. Every other control must see the step's own predicate reject.
if [[ -f "$SIBLING/SPEC.md" ]] && [[ -f "$SIBLING/impl-go/main.go" ]]; then
  control "an unbuildable sibling Go tree must break A1 (not skip)" "A1" A1 '
import sys, pathlib
p = pathlib.Path(sys.argv[1]) / "impl-go/main.go"
p.write_text(p.read_text() + "\nthis is not valid go\n")
sys.exit(0)
' unrun
else
  echo "  n/a   unbuildable-Go control — the sibling is not warrant"
  echo "        (we are warrant; A1 builds OUR impl-go, and CI must not corrupt that)"
fi

# --------------------------------------------------------------------------
# Control 9 — a polluted machine boundary must go red (B1). The report is
# specified as exactly one JSON object on stdout, and B1's stream assertion
# used to normalise the stream before checking it, which made the check
# vacuous (Codex X1 re-gate, P2). An assertion with no control behind it is a
# claim, so: emit one extra blank line ahead of the report and require B1 to
# reject it. warrant holds the verifier, so this runs when the sibling is
# warrant.
# --------------------------------------------------------------------------
if [[ -f "$SIBLING/SPEC.md" ]] && [[ -f "$SIBLING/impl/warrant.py" ]]; then
  control "a blank line before the JSON report must break B1" "B1" B1 '
import re, sys, pathlib
p = pathlib.Path(sys.argv[1]) / "impl/warrant.py"
src = p.read_text()
needle = "            print(json.dumps(report, separators="
i = src.find(needle)
if i < 0:
    sys.exit(1)
indent = " " * 12
p.write_text(src[:i] + indent + "print()\n" + src[i:])
sys.exit(0)
'
else
  echo "  n/a   polluted-boundary control — the sibling is not warrant"
  echo "        (we are warrant; B1 runs OUR verifier, and CI must not corrupt that)"
fi

# --------------------------------------------------------------------------
# Control 10 — caller development overrides are not X1 operands. Before this
# control, exporting SIGMA_GLYPH=sigma-HEAD made B2 reject settlement while the
# same two repository HEADs passed in a clean shell. X1 must erase ambient mode
# knobs and then opt into each differential explicitly.
# FULL MATRIX ON PURPOSE (no --only): the claim is that ambient state alters
# no step, so every step must run under the hostile environment.
# --------------------------------------------------------------------------
RAN=$((RAN+1))
_ambient_out="$({
  SIGMA_GLYPH="$SELF/definitely-not-the-pinned-evaluator" \
  WARRANT_SIGMA_DIFFERENTIAL=1 \
  WARRANT_POSITIONAL=1 \
  WARRANT_SKI_MAX_ATP=0 \
  SIBLING="$SIBLING" X1_SEEDS=1 bash "$X1"
} 2>&1)"
_ambient_rc=$?
if [[ $_ambient_rc -eq 0 ]] && grep -q "X1-CROSS-REPO: ALL PASS" <<<"$_ambient_out"; then
  echo "  OK    hostile ambient evaluator/mode overrides do not alter X1"
else
  echo "  FAIL  hostile ambient evaluator/mode overrides changed X1"
  printf '%s\n' "$_ambient_out" | grep -E 'FAIL|pass=|X1-CROSS-REPO' | sed 's/^/        | /'
  BAD=$((BAD+1))
fi

# --------------------------------------------------------------------------
# Controls 11-20 — the selector is closed and refuses before any work. Each of
# these is a shape a caller could plausibly type; each must exit 2 with the
# refusal marker and never reach the sibling (see selector_refusal). Runs from
# both directions; costs milliseconds.
# The three whitespace shapes are the substring finding (Codex review, P2): a
# space-separated list and the entire step line are both substrings of the
# padded set and used to pass membership, matching no step, and then reach
# the sibling. Membership is now one exact token, so they refuse up front, and
# a padded single step refuses too rather than being trimmed into acceptance.
# --------------------------------------------------------------------------
selector_refusal "an empty selector must refuse"            --only=
selector_refusal "a bare --only must refuse"                --only
selector_refusal "an unknown selector must refuse"          --only=Z9
selector_refusal "a selector list must refuse"              --only=A1,D1
selector_refusal "a repeated selector must refuse"          --only=A1 --only=D1
selector_refusal "a stray positional argument must refuse"  D1
selector_refusal "the informational pin report is not selectable" --only=F
selector_refusal "a whitespace-separated selector list must refuse" '--only=A1 A2'
selector_refusal "the entire step set as one selector must refuse" '--only=A1 A2 B1 B2 C1 C2 C3 D1 D2 E'
selector_refusal "a padded selector is not trimmed into acceptance" '--only= D1'

# --------------------------------------------------------------------------
# Control 21 — a selected step that executes nothing must FAIL. Selecting A2
# with X1_SEEDS made of whitespace leaves the fuzzer loop with zero iterations:
# the step is selected, prepared (Go is built) and reached, and still nothing
# runs. X1 must report A2 as not executed and exit non-zero -- never a
# SELECTED PASS with pass=0. The untampered sibling is used as-is (no copy).
# --------------------------------------------------------------------------
RAN=$((RAN+1))
_noexec_out="$(SIBLING="$SIBLING" X1_SEEDS=" " bash "$X1" --only=A2 2>&1)"
_noexec_rc=$?
if [[ $_noexec_rc -ne 0 ]] \
   && grep -q "FAIL.*A2 did not execute" <<<"$_noexec_out" \
   && ! grep -q "X1-CROSS-REPO: .*PASS" <<<"$_noexec_out"; then
  echo "  OK    a selected step that executes nothing fails (A2, zero seeds)"
else
  echo "  FAIL  a selected step that executed nothing did not fail (A2, zero seeds); exit $_noexec_rc:"
  printf '%s\n' "$_noexec_out" | grep -E 'OK|FAIL|pass=|X1-CROSS-REPO' | sed 's/^/        | /'
  BAD=$((BAD+1))
fi

# --------------------------------------------------------------------------
# Control 22 — a selected pass must never carry the full-matrix label. D1 is
# the cheapest step and reads no Go: the run must exit 0, print SELECTED PASS
# naming --only=D1, count exactly one outcome and that outcome D1, say it did
# not build Go, and never print the ALL PASS line the workflow and the hostile
# control (below) read as whole-matrix coverage.
# --------------------------------------------------------------------------
RAN=$((RAN+1))
_sel_out="$(SIBLING="$SIBLING" bash "$X1" --only=D1 2>&1)"
_sel_rc=$?
_esc="$(printf '\033')"
_sel_plain="$(printf '%s\n' "$_sel_out" | sed "s/${_esc}\[[0-9;]*m//g")"
_sel_outcomes="$(grep -cE '^  (OK|FAIL|SKIP) +' <<<"$_sel_plain")"
if [[ $_sel_rc -eq 0 ]] \
   && grep -q 'X1-CROSS-REPO: SELECTED PASS  --only=D1 ' <<<"$_sel_plain" \
   && ! grep -q 'X1-CROSS-REPO: ALL PASS' <<<"$_sel_plain" \
   && grep -q '^  pass=1 fail=0 skip=0 ' <<<"$_sel_plain" \
   && [[ "$_sel_outcomes" -eq 1 ]] \
   && grep -qE '^  OK +D1 ' <<<"$_sel_plain" \
   && grep -q '^  go       : not built' <<<"$_sel_plain"; then
  echo "  OK    a selected pass is labelled SELECTED PASS, runs one step, never ALL PASS"
else
  echo "  FAIL  a selected pass mislabelled or over-ran (exit $_sel_rc, $_sel_outcomes outcome line(s)):"
  printf '%s\n' "$_sel_plain" | grep -E 'go   |OK|FAIL|SKIP|pass=|X1-CROSS-REPO' | sed 's/^/        | /'
  BAD=$((BAD+1))
fi

# --------------------------------------------------------------------------
# Control 23 — the oracle must not credit a nonexecuted predicate. This is the
# review's mutation replayed on a COPY of our own tree (Codex review, P1): the
# D1 guard `if want D1; then` becomes `if [[ -z "$ONLY" ]]; then`, so D1 still
# runs in the full matrix but never under --only=D1. Pointed at that X1, the
# roster control (1) sees exit 1 and a `FAIL D1 did not execute` line, and the
# first draft of control() called that OK. The inner verdict must be FAIL, and
# for that reason. The inner control runs in a subshell so its counters are its
# own; the outer counts one control. D1 applies from both directions, so this
# runs from both. Costs one copy of our tree and one of the sibling.
# --------------------------------------------------------------------------
RAN=$((RAN+1))
_oracle_tmp="$(mktemp -d)"
_oracle_own="$_oracle_tmp/own"
cp -R "$SELF" "$_oracle_own"
if python3 - "$_oracle_own" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]) / "tools/x1_cross_repo.sh"
s = p.read_text()
old = "if want D1; then\n"
new = "if [[ -z \"$ONLY\" ]]; then\n"
if s.count(old) != 1:
    sys.exit(1)
p.write_text(s.replace(old, new))
PY
then
  _oracle_out="$(
    X1="$_oracle_own/tools/x1_cross_repo.sh"
    RAN=0; BAD=0   # the inner verdict alone, not ours so far
    control "roster key swap must break D1" "D1" D1 "$ROSTER_TAMPER"
    exit "$BAD"
  )"
  _oracle_bad=$?
  if [[ $_oracle_bad -eq 1 ]] && grep -q "never executed D1" <<<"$_oracle_out"; then
    echo "  OK    the oracle rejects a nonexecuted predicate (selected-only D1 disabled; inner verdict FAIL)"
  else
    echo "  FAIL  the oracle credited a control whose step never executed (inner verdict: $_oracle_bad bad):"
    printf '%s\n' "$_oracle_out" | sed 's/^/        | /'
    BAD=$((BAD+1))
  fi
else
  echo "  FAIL  the oracle control found no single D1 guard to disable in tools/x1_cross_repo.sh"
  BAD=$((BAD+1))
fi
rm -rf "$_oracle_tmp"

echo
if [[ "$RAN" -eq 0 ]]; then
  echo "X1-NEGATIVE-CONTROL: FAIL — no control ran at all. That is precisely the"
  echo "  vacuous case this script exists to prevent; treat it as a red gate."
  exit 1
fi
if [[ "$BAD" -ne 0 ]]; then
  # RAN counts controls ATTEMPTED and BAD is a subset of it. The old
  # denominator, RAN+BAD, counted every failure twice: one control failing out
  # of seven reported "1 of 8".
  echo "X1-NEGATIVE-CONTROL: FAIL ($BAD of $RAN controls did not behave)"
  exit 1
fi
echo "X1-NEGATIVE-CONTROL: ALL PASS ($RAN controls; X1 goes red on demand)"
