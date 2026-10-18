#!/usr/bin/env bash
# Scenario 4: a computation. Pause -> resume -> result, closed by the recipient's
# own replay with the pinned Sigma kernel; a verified cycle that makes one
# computation impossible without condemning the term elsewhere.
source "$(dirname "$0")/lib.sh"
actor claude; actor owner
P="$WORK/profile.json"
echo '{"uses":{"act":{"requires_triggers":false}},"accept_by":{"results":[]},"targets":["owner/compute"],"grant_roots":[],"challengers":[]}' > "$P"
view=(--store "$S" --trust "$T" --profile "$P" --as-of 5000)
compute_duty() { # INPUT ENV RUNTIME EXPECT
  as claude file --type duty --at 1000 "{\"statement\":\"compute $1\",\"holder\":\"claude\",\"owed_to\":[\"owner\"],\"accept_by\":[],\"release_by\":[],\"condition\":{\"compute\":{\"runtime\":\"$3\",\"input\":\"$1\",\"environment\":\"$2\",\"expect\":\"$4\"}},\"schedule\":null,\"requires\":[],\"serves\":[],\"answers\":null,\"subject\":null}" | get record
}
close() { # DUTY ACT EVIDENCE
  as claude file --type transition --at 2000 "{\"basis\":\"REPLAYED\",\"evidence\":[\"$3\"],\"relied_on\":[],\"established\":[],\"residual\":[],\"opened\":[],\"closes\":[{\"duty\":\"$1\",\"act\":\"$2\",\"evidence\":[\"$3\"]}],\"subject\":null,\"supersedes\":[],\"triggers\":[]}" >/dev/null
}

echo "1. a term, its environment, and a run with too little credit: PAUSED"
read IN EN RT <<< "$(warrant compute --store "$S" term --expr 'S K K (K I)' | fields input environment runtime)"
read C S0 <<< "$(warrant compute --store "$S" start --input "$IN" --environment "$EN" | fields checkpoint state)"
R1=$(warrant compute --store "$S" advance --input "$IN" --environment "$EN" --checkpoint "$C" --state "$S0" --credit 2)
expect "first run" "$(echo "$R1" | get outcome)" PAUSED

echo "2. resume from the checkpoint with more credit: NORMAL_FORM, and a receipt"
read C1 S1 <<< "$(echo "$R1" | fields checkpoint state)"
R2=$(warrant compute --store "$S" advance --input "$IN" --environment "$EN" --checkpoint "$C1" --state "$S1" --credit 100 --target owner/compute)
expect "resumed" "$(echo "$R2" | get outcome)" NORMAL_FORM
read RESULT RECEIPT <<< "$(echo "$R2" | fields result receipt)"

echo "3. the condition names the task and the answer; the recipient replays it"
D=$(compute_duty "$IN" "$EN" "$RT" "$RESULT")
close "$D" discharge "$RECEIPT"
expect "discharged" "$(warrant reliance "${view[@]}" "$D" | get state)" ELIGIBLE
echo "  basis: $(warrant capsule "${view[@]}" "$D" | get basis.0)"

echo "4. M M under the richer runtime cycles: a verified cycle makes that computation impossible"
read INM ENM RTM <<< "$(warrant compute --store "$S" term --runtime rich --expr 'M M' | fields input environment runtime)"
CYCLE=$(warrant compute --store "$S" cycle --runtime rich --input "$INM" --environment "$ENM" --target owner/compute | get cycle)
DM=$(compute_duty "$INM" "$ENM" "$RTM" "0000000000000000000000000000000000000000000000000000000000000000")
close "$DM" impossible "$CYCLE"
expect "M M" "$(warrant assess "${view[@]}" | get "duties.$DM.disposition")" IMPOSSIBLE

echo "5. the same term as an unused argument does not stop another computation"
read INK ENK <<< "$(warrant compute --store "$S" term --runtime rich --expr 'K I (M M)' | fields input environment)"
read CK SK <<< "$(warrant compute --store "$S" start --runtime rich --input "$INK" --environment "$ENK" | fields checkpoint state)"
read RK RECK <<< "$(warrant compute --store "$S" advance --runtime rich --input "$INK" --environment "$ENK" --checkpoint "$CK" --state "$SK" --credit 1000 --target owner/compute | fields result receipt)"
DK=$(compute_duty "$INK" "$ENK" "$RTM" "$RK")
close "$DK" discharge "$RECK"
expect "K I (M M)" "$(warrant assess "${view[@]}" | get "duties.$DK.disposition")" DISCHARGED
echo "scenario 4: ok"
