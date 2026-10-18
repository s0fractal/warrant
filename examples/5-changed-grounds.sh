#!/usr/bin/env bash
# Scenario 5: the grounds change. A closure declares what it depends on (a file
# manifest at a commit). When the file changes, relying on it for a present use
# is STALE; a counterexample from the creditor makes it CHALLENGED. History is
# untouched: the duty stays DISCHARGED. A revalidation, accepted again, restores
# eligibility for the new revision and resolves the challenge.
source "$(dirname "$0")/lib.sh"
actor claude; actor codex
REPO="$WORK/repo"; git init -q "$REPO"; git -C "$REPO" config user.email t@example.invalid; git -C "$REPO" config user.name t
printf 'def parse(s):\n    if not s:\n        raise ValueError\n    return s\n' > "$REPO/parse.py"
git -C "$REPO" add parse.py; git -C "$REPO" commit -qm one; C1=$(git -C "$REPO" rev-parse HEAD)
view() { warrant "$1" --store "$S" --trust "$T" --as-of 5000 --workspace "$REPO@$2" "${@:3}"; }

D=$(as claude file --type duty --at 1000 "{\"statement\":\"parse() rejects empty input\",\"holder\":\"claude\",\"owed_to\":[\"codex\"],\"accept_by\":[\"codex\"],\"release_by\":[],\"condition\":{\"attest\":{}},\"schedule\":null,\"requires\":[],\"serves\":[],\"answers\":null,\"subject\":\"$C1\"}" | get record)
BASE=$(warrant manifest --store "$S" --repo "$REPO" --rev "$C1" parse.py | get blob)
EV=$(printf 'review of parse.py at %s\n' "$C1" | warrant blob --store "$S" - | get blob)
TR=$(as claude file --type transition --at 1100 "{\"basis\":\"ATTESTED\",\"evidence\":[\"$EV\"],\"relied_on\":[],\"established\":[\"parse('') raises\"],\"residual\":[],\"opened\":[],\"closes\":[{\"duty\":\"$D\",\"act\":\"discharge\",\"evidence\":[\"$EV\"],\"triggers\":[{\"kind\":\"subject_changed\",\"baseline\":\"$BASE\"}]}],\"subject\":\"$C1\",\"supersedes\":[],\"triggers\":[]}" | get record)
as codex accept --at 1200 "$TR" --item 0 >/dev/null
expect "at the revision it was established on" "$(view reliance "$C1" "$D" | get state)" ELIGIBLE

echo "1. parse.py changes"
printf 'def parse(s):\n    return s.strip()\n' > "$REPO/parse.py"; git -C "$REPO" commit -qam two; C2=$(git -C "$REPO" rev-parse HEAD)
expect "relying on it now" "$(view reliance "$C2" "$D" | get state)" STALE
expect "history" "$(view assess "$C2" | get "duties.$D.disposition")" DISCHARGED

echo "2. codex files a counterexample"
CX=$(printf "parse('') returns '' at %s\n" "$C2" | warrant blob --store "$S" - | get blob)
CH=$(as codex file --type challenge --at 1300 "{\"target\":\"$TR\",\"item\":0,\"statement\":\"parse('') no longer raises\",\"evidence\":[\"$CX\"]}" | get record)
expect "even at the old revision" "$(view reliance "$C1" "$D" | get state)" CHALLENGED

echo "3. the code is fixed, revalidated at the new revision, and accepted"
printf 'def parse(s):\n    if not s.strip():\n        raise ValueError\n    return s.strip()\n' > "$REPO/parse.py"; git -C "$REPO" commit -qam three; C3=$(git -C "$REPO" rev-parse HEAD)
BASE3=$(warrant manifest --store "$S" --repo "$REPO" --rev "$C3" parse.py | get blob)
EV3=$(printf 'review of parse.py at %s\n' "$C3" | warrant blob --store "$S" - | get blob)
RV=$(as claude file --type transition --at 1400 "{\"basis\":\"ATTESTED\",\"evidence\":[\"$EV3\"],\"relied_on\":[\"$TR\"],\"established\":[\"parse('') and parse('  ') raise\"],\"residual\":[],\"opened\":[],\"closes\":[{\"duty\":\"$D\",\"act\":\"revalidate\",\"evidence\":[\"$EV3\"],\"revalidates\":[\"$TR\"],\"triggers\":[{\"kind\":\"subject_changed\",\"baseline\":\"$BASE3\"}]}],\"subject\":\"$C3\",\"supersedes\":[],\"triggers\":[]}" | get record)
as codex accept --at 1500 "$RV" --item 0 >/dev/null
expect "after revalidation" "$(view reliance "$C3" "$D" | get state)" ELIGIBLE
echo "  the capsule keeps the fired trigger as history:"
view assess "$C3" | python3 -c "
import json,sys
r = json.load(sys.stdin)['duties']['$D']
for t in r['triggers']:
    print('   ', t['closure'][:12], t['result'], 'current' if t['current'] else 'history')"
echo "scenario 5: ok"
