#!/bin/sh
# ai-review.sh — run an external AI reviewer over a DISPOSABLE clone of this repo.
# Ported from sigma-glyph tools/ai-review.sh (same isolation discipline).
#
#   tools/ai-review.sh codex 2026-07-codex-gov001.md "focus text..."
#
# The reviewer works in a throwaway clone (never the live checkout); the ONLY
# artifact copied back is reviews/<outfile>. The maintainer then verifies the
# review's claims independently and adjudicates (response doc + warrant in
# .warrants/).
set -eu
CLI=${1:?usage: ai-review.sh <codex|agy> <outfile.md> [focus...]}
OUT=${2:?missing output review filename}
shift 2
FOCUS=${*:-"Full adversarial review of the Warrant spec and implementations."}

REPO=$(git rev-parse --show-toplevel)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
git clone -q "$REPO" "$T/repo"
cd "$T/repo"
# Isolation: remove the breadcrumb back to the live checkout (a skip-permissions
# agent WILL follow it — observed in sigma-glyph run 1).
git remote remove origin
LIVE_STATE=$(git -C "$REPO" status --porcelain)

PROMPT="You are an independent adversarial reviewer of this repository
(Warrant: signed, hash-addressed decision records for AI agents).

PROTOCOL (binding). Run first, read second:
  python3 impl/warrant.py selftest       # must print ALL PASS
  python3 impl/warrant.py conformance    # must print ALL PASS (20/20)
  (cd impl-go && go build -o warrant-go . 2>/dev/null || go build -o warrant-go main.go) || true
  ./impl-go/warrant-go selftest          # must print ALL PASS (7/7)
  python3 tests/differential.py          # must print ALL AGREE
  python3 tests/negative.py              # must print ALL AGREE
Include a verified-state statement with the actual outputs you saw.

FOCUS: $FOCUS

RULES:
- Severity ladder: P0 = two conforming verifiers can disagree on a WarrantID
  or a verification outcome; P1 = spec silent where implementers must guess;
  P2 = clarity; P3 = roadmap.
- Form your own findings from SPEC.md and the implementations BEFORE reading
  reviews/; then add an agree/disagree/new section relative to them.
- Every claim checkable by running code: check it by running code, and show
  the command.
- Give concrete text proposals for every P1/P2.
- Write the COMPLETE review to reviews/$OUT and nothing else: do not modify
  any other file, do not commit, do not push.
- Work ONLY inside the current working directory ($T/repo). Never touch any
  other checkout of this project, even if you know one exists.
"

case "$CLI" in
  agy)
    agy --add-dir . --dangerously-skip-permissions \
        --model "${AGY_MODEL:-Gemini 3.1 Pro (High)}" \
        --print-timeout 45m -p "$PROMPT"
    ;;
  codex)
    # </dev/null: codex exec reads extra prompt text from stdin when it is not
    # a TTY and blocks until EOF — fatal for background runs that keep stdin open
    codex exec --sandbox workspace-write "$PROMPT" </dev/null
    ;;
  *)
    echo "unknown reviewer CLI: $CLI" >&2; exit 2
    ;;
esac

if [ "$(git -C "$REPO" status --porcelain)" != "$LIVE_STATE" ]; then
    echo "WARNING: live checkout changed during review — inspect git status before trusting it" >&2
fi
test -s "reviews/$OUT" || { echo "reviewer did not write reviews/$OUT" >&2; exit 1; }
cp "reviews/$OUT" "$REPO/reviews/$OUT"
echo "review delivered: reviews/$OUT"
