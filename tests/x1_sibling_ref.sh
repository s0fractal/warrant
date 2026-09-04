#!/usr/bin/env bash
# Behaviour of tools/x1_sibling_ref.sh, the resolver that decides whether the
# aggregate check hands X1 a paired sibling branch or lets it use sibling
# master. The defect it guards: an ordinary one-sided PR (branch exists here,
# not in the sibling) must resolve to master, not to a clone that cannot exist
# (PR #55 went red exactly that way). Uses a local bare repo as the sibling so
# the test needs no network and cannot be green by accident of what GitHub
# holds today. Also holds ci.yml to the resolver: the workflow must obtain
# X1_SIBLING_REF from this script and must not export github.head_ref
# unconditionally again.
set -euo pipefail
cd "$(dirname "$0")/.."
RESOLVER=tools/x1_sibling_ref.sh
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# A fake sibling with master and exactly one candidate branch.
git init -q --bare "$T/sib.git"
git init -q "$T/work"
git -C "$T/work" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
git -C "$T/work" branch -M master
git -C "$T/work" branch paired/candidate
git -C "$T/work" push -q "$T/sib.git" master paired/candidate
export X1_SIBLING_URL="$T/sib.git"

fail=0
# expect <label> <expected-stdout> <expected-exit> then env assignments
expect() {
  local label="$1" want="$2" want_rc="$3"; shift 3
  local got rc=0
  got="$(env "$@" bash "$RESOLVER" 2>"$T/err")" || rc=$?
  if [[ "$got" == "$want" && "$rc" == "$want_rc" ]]; then
    echo "  ok    $label -> '${got}' (exit $rc)"
  else
    echo "  FAIL  $label -> '${got}' (exit $rc); wanted '${want}' (exit $want_rc)"
    sed 's/^/          /' "$T/err"; fail=1
  fi
}

echo "x1 sibling-ref resolver"
# paired same-owner PR: the sibling has the branch -> candidate vs candidate
expect "paired PR, branch exists in sibling" "paired/candidate" 0 \
  X1_EVENT_NAME=pull_request X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF=paired/candidate
# THE PR #55 CASE: same owner, ordinary one-sided branch -> sibling master
expect "one-sided PR, branch absent in sibling" "" 0 \
  X1_EVENT_NAME=pull_request X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF=truth/warrant-public-status
# non-PR events never pair, even when the sibling holds a branch of that name
expect "push event never pairs" "" 0 \
  X1_EVENT_NAME=push X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF=paired/candidate
expect "schedule event never pairs" "" 0 \
  X1_EVENT_NAME=schedule X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF=paired/candidate
expect "fork PR never pairs, even if the name exists" "" 0 \
  X1_EVENT_NAME=pull_request X1_PR_HEAD_OWNER=someone-else X1_PR_HEAD_REF=paired/candidate
expect "PR with no head ref" "" 0 \
  X1_EVENT_NAME=pull_request X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF=
# a prefix of an existing branch must not count as existing
expect "prefix of an existing branch is not that branch" "" 0 \
  X1_EVENT_NAME=pull_request X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF=paired
# unanswerable questions fail loudly (exit 2), never silently choose master
expect "malformed ref fails loudly" "" 2 \
  X1_EVENT_NAME=pull_request X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF='bad..ref'
expect "unreachable sibling fails loudly" "" 2 \
  X1_EVENT_NAME=pull_request X1_PR_HEAD_OWNER=s0fractal X1_PR_HEAD_REF=paired/candidate \
  X1_SIBLING_URL="$T/does-not-exist.git"

# The resolver is only a repair if ci.yml actually uses it.
CI=.github/workflows/ci.yml
if grep -q 'tools/x1_sibling_ref.sh' "$CI"; then
  echo "  ok    ci.yml resolves X1_SIBLING_REF through $RESOLVER"
else
  echo "  FAIL  ci.yml does not call $RESOLVER"; fail=1
fi
if grep -Eq 'X1_SIBLING_REF:[[:space:]]*\$\{\{' "$CI"; then
  echo "  FAIL  ci.yml exports X1_SIBLING_REF straight from the GitHub context (the PR #55 defect)"; fail=1
else
  echo "  ok    ci.yml does not export X1_SIBLING_REF unconditionally"
fi

if [[ $fail -ne 0 ]]; then echo "X1 SIBLING-REF: FAILURES PRESENT"; exit 1; fi
echo "X1 SIBLING-REF: ALL PASS"
