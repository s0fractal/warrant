#!/usr/bin/env bash
# Scenario 2: a service, not a review. The condition is "the health endpoint
# answers ok", observed by a named observer. The holder's "done" is not enough;
# an observation says when it ran, how (the probe), and what it saw. It goes
# stale after fresh_for seconds.
source "$(dirname "$0")/lib.sh"
actor claude; actor owner; actor probe-bot

# The service: a static file served on a free local port.
mkdir -p "$WORK/www"; printf 'ok' > "$WORK/www/health"
PORT=$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1])')
python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$WORK/www" >/dev/null 2>&1 & SERVER=$!
trap 'kill $SERVER 2>/dev/null || true; rm -rf "$WORK"' EXIT
for _ in $(seq 50); do python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:$PORT/health')" 2>/dev/null && break; sleep 0.1; done

# The method of observation is itself a blob: what runs, against what, with which limit.
cat > "$WORK/probe.json" <<JSON
{"argv":["python3","-c","import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:$PORT/health',timeout=5).read().decode())"],"timeout":10}
JSON
PROBE=$(warrant blob --store "$S" --json "$WORK/probe.json" | get blob)

NOW=$(date +%s)
D=$(as claude file --type duty --at "$NOW" "{\"statement\":\"the health endpoint answers ok\",\"holder\":\"claude\",
  \"owed_to\":[\"owner\"],\"accept_by\":[],\"release_by\":[],
  \"condition\":{\"observe\":{\"observers\":[\"probe-bot\"],\"probe\":\"$PROBE\",\"expect\":\"ok\",\"fresh_for\":3600}},
  \"schedule\":null,\"requires\":[],\"serves\":[],\"answers\":null,\"subject\":null}" | get record)
view() { warrant "$1" --store "$S" --trust "$T" --as-of "$2" "${@:3}"; }

echo "1. the holder says it is done: that is not an observation"
as claude file --type transition "{\"basis\":\"ATTESTED\",\"evidence\":[],\"relied_on\":[],\"established\":[\"deployed\"],
  \"residual\":[],\"opened\":[],\"closes\":[{\"duty\":\"$D\",\"act\":\"discharge\",\"evidence\":[]}],
  \"subject\":null,\"supersedes\":[],\"triggers\":[]}" >/dev/null
expect "the word of the executor" "$(view assess "$(date +%s)" | get "duties.$D.candidates.0.verdict")" OVERCLAIMED

echo "2. the observer runs the probe; the record says when, how and what"
OBS=$(as probe-bot observe --target "http://127.0.0.1:$PORT/health" --probe "$WORK/probe.json")
O=$(echo "$OBS" | get record); echo "  observed $(echo "$OBS" | get result) during $(echo "$OBS" | get window)"

echo "3. the holder closes the condition on that observation"
as claude file --type transition "{\"basis\":\"OBSERVED\",\"evidence\":[\"$O\"],\"relied_on\":[],\"established\":[\"/health answered ok\"],
  \"residual\":[\"only /health was probed; latency was not measured\"],\"opened\":[],
  \"closes\":[{\"duty\":\"$D\",\"act\":\"discharge\",\"evidence\":[\"$O\"]}],
  \"subject\":null,\"supersedes\":[],\"triggers\":[]}" >/dev/null
AT=$(( $(date +%s) + 1 ))
expect "now" "$(view reliance "$AT" "$D" | get state)" ELIGIBLE
expect "basis" "$(view capsule "$AT" "$D" | get basis.0)" OBSERVED:probe-bot

echo "4. two hours later the same observation is stale"
expect "later" "$(view reliance $(( AT + 7200 )) "$D" | get state)" STALE

echo "5. the service goes down; a new observation does not meet the condition"
kill $SERVER; wait $SERVER 2>/dev/null || true
D2=$(as claude file --type duty "{\"statement\":\"the health endpoint answers ok (after restart)\",\"holder\":\"claude\",
  \"owed_to\":[\"owner\"],\"accept_by\":[],\"release_by\":[],
  \"condition\":{\"observe\":{\"observers\":[\"probe-bot\"],\"probe\":\"$PROBE\",\"expect\":\"ok\",\"fresh_for\":3600}},
  \"schedule\":null,\"requires\":[],\"serves\":[],\"answers\":null,\"subject\":null}" | get record)
O2=$(as probe-bot observe --target "http://127.0.0.1:$PORT/health" --probe "$WORK/probe.json" | get record)
as claude file --type transition "{\"basis\":\"OBSERVED\",\"evidence\":[\"$O2\"],\"relied_on\":[],\"established\":[],
  \"residual\":[],\"opened\":[],\"closes\":[{\"duty\":\"$D2\",\"act\":\"discharge\",\"evidence\":[\"$O2\"]}],
  \"subject\":null,\"supersedes\":[],\"triggers\":[]}" >/dev/null
expect "down" "$(view assess $(( $(date +%s) + 1 )) | get "duties.$D2.candidates.0.verdict")" UNMET_CONDITION
echo "scenario 2: ok"
