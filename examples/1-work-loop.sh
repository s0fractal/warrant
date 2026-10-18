#!/usr/bin/env bash
# Scenario 1: a real loop of work. A condition, a transition with evidence and a
# residual, the exact acceptance, then the capsule and frontier the next session
# reads. Opening a new question does not undo what was established.
source "$(dirname "$0")/lib.sh"
actor claude; actor codex
P="$WORK/profile.json"
echo '{"uses":{"act":{"requires_triggers":false}},"accept_by":{"results":["codex"]},"targets":[],"grant_roots":[],"challengers":[],"providers":[]}' > "$P"
view=(--store "$S" --trust "$T" --profile "$P" --as-of 2000)

echo "1. claude takes on a condition that codex must accept"
D=$(as claude file --type duty --at 1000 '{"statement":"parse() rejects empty input","holder":"claude","owed_to":["codex"],"accept_by":["codex"],"release_by":[],"condition":{"attest":{}},"schedule":null,"requires":[],"serves":[],"answers":null,"subject":null}' | get record)

echo "2. claude records the work: evidence, what it establishes, what it does not, a new question"
LOG=$(printf 'test_parse_empty ... ok\n' | warrant blob --store "$S" - | get blob)
TR=$(as claude file --type transition --at 1100 "{\"basis\":\"ATTESTED\",\"evidence\":[\"$LOG\"],\"relied_on\":[],
  \"established\":[\"parse('') raises ValueError\"],\"residual\":[\"non-ASCII input was not examined\"],
  \"opened\":[{\"text\":\"should whitespace-only input be rejected too?\",\"scope\":null}],
  \"closes\":[{\"duty\":\"$D\",\"act\":\"discharge\",\"evidence\":[\"$LOG\"]}],
  \"subject\":null,\"supersedes\":[],\"triggers\":[]}" | get record)
expect "before acceptance" "$(warrant reliance "${view[@]}" "$D" | get state)" NOT_CLOSED
expect "codex's frontier asks for the acceptance" "$(warrant frontier "${view[@]}" codex | get frontier.0.need)" accept

echo "3. codex accepts exactly that item"
as codex accept --at 1200 "$TR" --item 0 >/dev/null
as codex accept --at 1201 "$TR" >/dev/null           # and the transition's results
expect "duty" "$(warrant reliance "${view[@]}" "$D" | get state)" ELIGIBLE

echo "4. the next session reads the capsule, not the conversation"
warrant capsule "${view[@]}" "$D" | tee "$WORK/capsule.json" | get disposition basis limits evidence
expect "capsule disposition" "$(get disposition < "$WORK/capsule.json")" DISCHARGED
expect "the residual travels with it" "$(get limits.0 < "$WORK/capsule.json")" "non-ASCII input was not examined"

echo "5. the open question is nobody's duty until someone takes it"
expect "unowned question" "$(warrant questions "${view[@]}" | get questions.0.text)" "should whitespace-only input be rejected too?"
expect "claude's frontier" "$(warrant frontier "${view[@]}" claude | get frontier)" "[]"

echo "6. a later transition opens another question; the result stands"
as claude file --type transition --at 1300 '{"basis":"ATTESTED","evidence":[],"relied_on":[],"established":[],"residual":[],"opened":[{"text":"is ValueError the right type?","scope":null}],"closes":[],"subject":null,"supersedes":[],"triggers":[]}' >/dev/null
expect "still eligible" "$(warrant reliance "${view[@]}" "$D" | get state)" ELIGIBLE
expect "two unowned questions" "$(warrant questions "${view[@]}" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)["questions"]))')" 2
echo "scenario 1: ok"
