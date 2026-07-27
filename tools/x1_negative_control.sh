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
#
#   SIBLING=/path/to/sibling tools/x1_negative_control.sh
set -uo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
X1="$SELF/tools/x1_cross_repo.sh"
[ -f "$X1" ] || { echo "negative-control: $X1 not found" >&2; exit 2; }
[ -n "${SIBLING:-}" ] || { echo "negative-control: set SIBLING=/path/to/sibling" >&2; exit 2; }
[ -d "$SIBLING" ] || { echo "negative-control: SIBLING=$SIBLING does not exist" >&2; exit 2; }

RAN=0
BAD=0

# control <name> <must-fail-step> <python-tamper-script>
#   The tamper script receives the tampered-copy root as argv[1]; it must exit 0
#   after mutating something, or non-zero if it had nothing to mutate.
control() {
  local name="$1" needle="$2" script="$3"
  local tmp; tmp="$(mktemp -d)"
  local work="$tmp/sibling"
  cp -R "$SIBLING" "$work"

  if ! python3 -c "$script" "$work"; then
    echo "  FAIL  $name — nothing to tamper (a control that tampers nothing is vacuous)"
    BAD=$((BAD+1)); rm -rf "$tmp"; return
  fi

  local out rc
  out="$(SIBLING="$work" X1_SEEDS=1 bash "$X1" 2>&1)"; rc=$?
  rm -rf "$tmp"
  RAN=$((RAN+1))

  if [ $rc -eq 0 ]; then
    echo "  FAIL  $name — X1 PASSED on a tampered sibling; the gate is vacuous"
    BAD=$((BAD+1)); return
  fi
  # Non-zero exit is necessary but not sufficient: require the *predicted* step
  # to be red, so an unrelated breakage cannot masquerade as proof of coverage.
  if printf '%s' "$out" | grep -q "FAIL.*$needle"; then
    echo "  OK    $name — X1 red at the predicted step ($needle)"
  else
    echo "  FAIL  $name — X1 failed, but NOT at '$needle'. Red for the wrong reason:"
    printf '%s\n' "$out" | grep -E 'FAIL|pass=' | sed 's/^/        | /'
    BAD=$((BAD+1))
  fi
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
}

echo "X1 negative controls (sibling: $SIBLING)"

# --------------------------------------------------------------------------
# Control 1 — governance roster (D1). Works from BOTH directions: D1 compares
# warrant/trust/sigma-glyph-anchor-trust.json against sigma/trust-config.json,
# and exactly one of those two files lives in the sibling, whichever side we
# are on. This is the control that makes neither direction vacuous.
# --------------------------------------------------------------------------
control "roster key swap must break D1" "D1" '
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

# --------------------------------------------------------------------------
# Controls 2-4 — ONE PER VECTOR KIND (A1). sigma-glyph holds the vectors, so
# these apply only when the sibling is sigma. Together they are the teeth
# behind A1's per-kind coverage assertion: object, eval and deserialize must
# each be genuinely executed by warrant-go for X1 to be green.
# --------------------------------------------------------------------------
if [ -f "$SIBLING/tests/spec_conformance/vectors.json" ]; then
  control "flipped object expected.hash must break A1"        "A1" "$(vector_tamper object hash hex)"
  control "flipped eval expected.result_hash must break A1"   "A1" "$(vector_tamper eval result_hash hex)"
  control "inverted deserialize expected.valid must break A1" "A1" "$(vector_tamper deserialize valid bool)"
else
  echo "  n/a   per-kind Book I controls — the sibling holds no vectors.json"
  echo "        (we are sigma-glyph; A1 reads OUR vectors, and CI must not corrupt those)"
fi

# --------------------------------------------------------------------------
# Control 5 — reverse direction (C1). warrant's ski@v1 conformance pins the
# check blob by hash; corrupting it makes `warrant conformance` refuse. warrant
# holds examples/, so this applies only when the sibling is warrant.
# --------------------------------------------------------------------------
if [ -f "$SIBLING/examples/ski/check.json" ]; then
  control "corrupted ski check-blob must break C1" "C1" '
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
  echo "        (we are warrant; C1 reads OUR examples, and CI must not corrupt those)"
fi

# --------------------------------------------------------------------------
# Control 6 — gate REMOVAL must go red (E). Divergence was already detected;
# deletion was not, and deletion is the cheaper attack: drop X1 from one repo
# and its workflow simply stops running, while the other side used to skip and
# stay green (Codex X1 gate, P1). Runs from both directions.
# --------------------------------------------------------------------------
control "deleting a mirrored X1 file must break E" "E:" '
import sys, pathlib
root = pathlib.Path(sys.argv[1])
for rel in ("tools/x1_negative_control.sh", "tools/x1_cross_repo.sh",
            ".github/workflows/x1-cross-repo.yml"):
    p = root / rel
    if p.exists():
        p.unlink()
        sys.exit(0)
sys.exit(1)
'

# --------------------------------------------------------------------------
# Control 7 — an unbuildable sibling must NOT be green (A1). warrant-go is
# built from the warrant tree, so this control exists exactly when the sibling
# is warrant. It is the direct countervector for "required Go crossings can
# silently SKIP and the job still passes".
# --------------------------------------------------------------------------
# Note the guard: sigma-glyph ALSO has an impl-go (its federation implementation),
# so "the sibling has a Go tree" is not the question. A1 builds *warrant's*
# evaluator, so this control applies exactly when the sibling IS warrant — the
# same detection X1 itself uses.
if [ -f "$SIBLING/SPEC.md" ] && [ -f "$SIBLING/impl-go/main.go" ]; then
  control "an unbuildable sibling Go tree must break A1 (not skip)" "A1" '
import sys, pathlib
p = pathlib.Path(sys.argv[1]) / "impl-go/main.go"
p.write_text(p.read_text() + "\nthis is not valid go\n")
sys.exit(0)
'
else
  echo "  n/a   unbuildable-Go control — the sibling is not warrant"
  echo "        (we are warrant; A1 builds OUR impl-go, and CI must not corrupt that)"
fi

# --------------------------------------------------------------------------
# Control 8 — a polluted machine boundary must go red (B1). The report is
# specified as exactly one JSON object on stdout, and B1's stream assertion
# used to normalise the stream before checking it, which made the check
# vacuous (Codex X1 re-gate, P2). An assertion with no control behind it is a
# claim, so: emit one extra blank line ahead of the report and require B1 to
# reject it. warrant holds the verifier, so this runs when the sibling is
# warrant.
# --------------------------------------------------------------------------
if [ -f "$SIBLING/SPEC.md" ] && [ -f "$SIBLING/impl/warrant.py" ]; then
  control "a blank line before the JSON report must break B1" "B1" '
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

echo
if [ "$RAN" -eq 0 ]; then
  echo "X1-NEGATIVE-CONTROL: FAIL — no control ran at all. That is precisely the"
  echo "  vacuous case this script exists to prevent; treat it as a red gate."
  exit 1
fi
if [ "$BAD" -ne 0 ]; then
  echo "X1-NEGATIVE-CONTROL: FAIL ($BAD of $((RAN+BAD)) controls did not behave)"
  exit 1
fi
echo "X1-NEGATIVE-CONTROL: ALL PASS ($RAN controls; X1 goes red on demand)"
