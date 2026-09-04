#!/usr/bin/env bash
# Resolve which sibling ref the AGGREGATE check (tools/check.py, ci.yml) hands
# to X1 as X1_SIBLING_REF. Prints the ref on stdout, or an empty line meaning
# "sibling master". Exit 0 either way; exit 2 only when the question could not
# be answered (sibling unreachable, malformed ref), which must fail loudly
# rather than quietly pick master.
#
# RULE (the same one .github/workflows/x1-cross-repo.yml applies inline):
# candidate-against-candidate ONLY for a pull_request whose head lives in the
# same owner's repository AND whose branch name ALSO EXISTS in the sibling.
# Everything else -- push, schedule, fork PR, or a same-owner PR whose branch
# has no twin -- tests against sibling master.
#
# WHY THIS FILE EXISTS: ci.yml's first draft exported github.head_ref
# unconditionally on every same-owner PR. tools/x1_cross_repo.sh treats an
# explicit X1_SIBLING_REF as an explicit operand and fails when it does not
# exist (correct: it is mirrored byte-for-byte with sigma-glyph and must stay
# strict), so an ordinary one-sided warrant PR asked X1 to clone
# sigma-glyph/<branch> that was never created and the whole aggregate went red
# (PR #55). The existence probe belongs here, on the caller's side.
#
# INPUTS (environment; the workflow fills them from the GitHub context)
#   X1_EVENT_NAME     github.event_name
#   X1_PR_HEAD_OWNER  github.event.pull_request.head.repo.owner.login
#   X1_PR_HEAD_REF    github.head_ref
#   X1_SIBLING_URL    override for tests (default: the sibling on GitHub)
#   X1_OWNER          the owner whose PRs may be paired (default: s0fractal)
set -euo pipefail

SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$SELF/SPEC.md" ]] && [[ -d "$SELF/impl-go" ]]; then
  SIB_NAME=sigma-glyph
else
  SIB_NAME=warrant
fi
OWNER="${X1_OWNER:-s0fractal}"
URL="${X1_SIBLING_URL:-https://github.com/$OWNER/$SIB_NAME.git}"
EVENT="${X1_EVENT_NAME:-}"
HEAD_OWNER="${X1_PR_HEAD_OWNER:-}"
REF="${X1_PR_HEAD_REF:-}"

note() { echo "x1-sibling-ref: $*" >&2; }

if [[ "$EVENT" != "pull_request" ]]; then
  note "event=${EVENT:-<none>} is not a pull_request -> sibling master"
  echo ""; exit 0
fi
if [[ "$HEAD_OWNER" != "$OWNER" ]]; then
  note "PR head owner=${HEAD_OWNER:-<none>} is not $OWNER -> sibling master"
  echo ""; exit 0
fi
if [[ -z "$REF" ]]; then
  note "no PR head ref -> sibling master"
  echo ""; exit 0
fi
if ! git check-ref-format --branch "$REF" >/dev/null 2>&1; then
  note "malformed PR head ref '$REF'"; exit 2
fi

# `--heads` with the full ref name: exactly one line means the branch exists;
# zero means it does not. A failing ls-remote (no network, bad URL) is neither,
# and is reported as such instead of being read as "absent".
if ! heads="$(git ls-remote --heads "$URL" "refs/heads/$REF" 2>&1)"; then
  note "cannot reach sibling $URL: ${heads}"; exit 2
fi
if [[ "$(printf '%s' "$heads" | grep -c "refs/heads/$REF\$" || true)" -eq 1 ]]; then
  note "sibling $SIB_NAME has branch $REF -> candidate against candidate"
  echo "$REF"
else
  note "sibling $SIB_NAME has no branch $REF -> sibling master"
  echo ""
fi
