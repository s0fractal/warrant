# Sigma #68 review and amendment handoff

This is an actual signed review/task package for a new external Claude host.
The task, review, counterexamples and frozen input kit are Warrant blobs carried
by a declared handoff, not an unsigned GitHub issue comment. Git carries public
bytes; the operator's separate packet pin binds the intended delivery.

`run.py` uses installed Warrant 2 APIs/CLI. It makes no network calls and executes
no attachment code. Inspect the runner before use. This application wrapper adds
no Warrant record type, kernel capability or release authority.

## Bootstrap on the new receiver

Use Python >=3.11 and a new private directory outside any checkout. Clone
`s0fractal/warrant`, check out the **exact runner commit supplied by the operator**,
create a venv, and install `.[compute]` from that checkout plus `packaging==26.3`.
The optional compute dependency selects `sigma-glyph==0.8.0` from PyPI. Installation
needs network access; handoff receive/submit/verify itself is local.

The operator must supply the packet hash outside the downloaded packet:

```
e8d611c57793b1e246e36f6c49dd8074433190a438770ce66b5a5f7b32abd3d9
```

Producer public key:
`913ad8f247c25bec6708472febb37097a335315eee20552f551c617c9026d848`.
This is an experiment-specific key binding, not independently established
real-world identity. New receiver key/trust/profile/store are private to this
experiment; the runner does not modify an existing Warrant workspace.

With the venv active, set `KIT` to the absolute `examples/review-handoff` path:

```sh
python "$KIT/run.py" receive \
  --packet "$KIT/packet.json" \
  --pin e8d611c57793b1e246e36f6c49dd8074433190a438770ce66b5a5f7b32abd3d9 \
  --work "$PWD/receiver-private" --output "$PWD/ack.json"
```

The work directory must not exist. Receive checks the operator pin, imports via
Warrant's signed declaration/manifest/delivery checks, acknowledges the producer's
exact delivery, and creates a receiver-owned duty owed to `codex-review`.
Acknowledgment accepts delivery only; it does not approve the review's conclusions
or claim the amendment is complete. Fresh-process acceptance retry is checked.
Send `ack.json` and its printed SHA-256 through the operator. No old-host private
key is required. Keep the new private work directory for the rest of this task.

## Inspect task and do the work

Receive prints the task and attachment-name -> content-hash map. Files in
`receiver-private/inbox/<hash>` are the exact verified public bytes. The attachments
are the independent AMEND review, executable counterexample source (inspect before
running), raw capped results, and a ZIP of the full #150 input kit. No attachment
is automatically executed or extracted. The ZIP contains source, manifest,
METADATA, native observations and bundled wheels; four third-party wheels still
need the kit's explicit pinned fetch. Run its verifier and controls before adapting
any encoder. Its manifest pin and source revision are part of the signed task.

The requested fixes include per-instance resource admission, full policy/input
binding and the complete forbidden/required predicate on the three frozen graphs.
Return public source/patch, raw tests, workload identities and measurements.
Do not change kernel/SPEC/provider, merge or publish under this task.

## Return candidate or a blocked/inconclusive report

```sh
python "$KIT/run.py" submit --work "$PWD/receiver-private" \
  --report "$PWD/report.json" --artifact "$PWD/amendment.patch" \
  --artifact "$PWD/measurements.jsonl" --status candidate \
  --output "$PWD/reply.json"
```

Artifact flags may be repeated or omitted. For a resource limit/prerequisite
failure use `--status inconclusive` or `--status blocked`, with the raw report.
Those responses do not propose a discharge. A candidate files an **ATTESTED**
closure tied to the task, incoming packet and exact public artifacts; it stays
unaccepted until Codex independently checks and explicitly accepts that item.
Neither submitted logs nor a signature establish remote execution.

Send `reply.json` and its printed SHA-256 through the operator. Never send
`receiver-private/`, `private.key`, tokens or unrelated files. If the host/key is
lost after acknowledgment, ask the operator for a new explicit handoff; do not
impersonate the previous receiver key.

## Producer readback

Codex retains its own private workspace locally. After obtaining a receiver packet
and its digest through the operator:

```sh
python "$KIT/run.py" verify --work /private/producer-workspace \
  --packet /public/reply.json --pin <operator-relayed-reply-sha256>
```

This checks signatures, delivery, exact acknowledgment, receiver duty, task and
submission bindings, and confirms that the work has **not** been silently accepted.
The first pinned reply binds the new receiver key for this experiment; subsequent
key changes refuse. Reviewer acceptance is a later, separately evidenced act.

## Local validation

`python examples/review-handoff/selftest.py` runs both roles on one host. It checks
fresh-process acknowledgment retry, open work after candidate/blocked/inconclusive
responses, wrong operator pin, changed task/submission metadata, damaged delivery,
and absence of private seeds/producer-local task paths from decoded wire payloads.
These are local controls, not a claim that Claude received or executed anything.

## Completed review exchange

[Round 2](round-2/README.md) carries a signed AMEND update, imported into the
existing receiver workspace. [Round 3](round-3/README.md) carries the original
reviewer's exact candidate acceptance and a `conclude` command for receiver-side
readback. The local control includes explicit acceptance, refusal when another
candidate tries to inherit it, and repeated import. No candidate is accepted by
`verify` or `submit`; only a separately signed reviewer acceptance closes work.
