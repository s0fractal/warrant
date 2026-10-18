#!/usr/bin/env bash
# Scenario 3: a periodic obligation. Two periods have passed: one was covered, the
# other lapsed. A past discharge does not cover a later period, and a period
# cannot be discharged before it starts. Every answer names its time (--as-of).
source "$(dirname "$0")/lib.sh"
actor ops; actor owner
D=$(as ops file --type duty --at 1000 '{"statement":"restore the nightly backup into a scratch database and check row counts","holder":"ops","owed_to":["owner"],"accept_by":["owner"],"release_by":[],"condition":{"attest":{}},"schedule":{"start":1000,"every":100},"requires":[],"serves":[],"answers":null,"subject":null}' | get record)
discharge() { # PERIOD AT
  local ev; ev=$(printf 'restore log for period %s\n' "$1" | warrant blob --store "$S" - | get blob)
  as ops file --type transition --at "$2" "{\"basis\":\"ATTESTED\",\"evidence\":[\"$ev\"],\"relied_on\":[],\"established\":[\"period $1 restored\"],\"residual\":[],\"opened\":[],\"closes\":[{\"duty\":\"$D\",\"act\":\"discharge\",\"period\":$1,\"evidence\":[\"$ev\"]}],\"subject\":null,\"supersedes\":[],\"triggers\":[]}" | get record
}
T0=$(discharge 0 1050); as owner accept --at 1060 "$T0" --item 0 >/dev/null
EARLY=$(discharge 2 1150); as owner accept --at 1160 "$EARLY" --item 0 >/dev/null

A=$(warrant assess --store "$S" --trust "$T" --as-of 1250)
expect "period 0" "$(echo "$A" | get "duties.$D.periods.0.state")" COVERED
expect "period 1" "$(echo "$A" | get "duties.$D.periods.1.state")" LAPSED
expect "period 2" "$(echo "$A" | get "duties.$D.periods.2.state")" OPEN
expect "the early discharge" "$(echo "$A" | get "duties.$D.candidates.1.verdict")" OVERCLAIMED
echo "  ops's frontier at 1250:"
warrant frontier --store "$S" --trust "$T" --as-of 1250 ops | get frontier
expect "the same store at 1080" "$(warrant assess --store "$S" --trust "$T" --as-of 1080 | get "duties.$D.periods")" '{"0": {"basis": "ATTESTED:ops", "by": "'"$T0"'", "state": "COVERED"}}'
echo "scenario 3: ok"
