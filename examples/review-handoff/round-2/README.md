# Signed AMEND update for candidate 7fc7407

`update.json` is a Warrant handoff exported by the original `codex-review` key.
It carries an ATTESTED review transition, independent reproduction evidence and
an AMEND request. It closes no receiver duty and supplies no acceptance.

Operator pin (obtain separately from the message):
`9587b0ac85097a1f07171a71a7f77ee2016b8477a780ae154e1f30f1ccfa40e1`.

Use the updated runner from the exact operator-supplied commit, installed Warrant
venv, and the **existing** `claude-68` private workspace:

```sh
python "$KIT/run.py" update --work /absolute/receiver-private \
  --packet "$KIT/round-2/update.json" \
  --pin 9587b0ac85097a1f07171a71a7f77ee2016b8477a780ae154e1f30f1ccfa40e1
```

This checks the original task/packet binding, established reviewer key, signed
review transition and exact attachments. It imports the update, prints the
attachment hashes, and preserves the receiver key and open work duty. Attachment
files are written by hash to the existing inbox; none is executed automatically.

The inner signed review requests a fix for stale `workload_doc` reuse in
`resume_run`, with a same-term/different-application-binding regression. It also
requests publishing the exact existing public ACK/candidate packet files on the
ordinary work branch: Codex has their operator-relayed digests but lacks their
bytes. No private directory/key/token is requested or authorized for publication.
After amendment, submit using the existing workspace/key and preserve old and new
public responses separately. Relay the new reply digest via the operator.

Local evidence: all 34 amended encoder checks passed; independently regenerated
base/compute/transitive workload IDs and ATP matched the submitted logs. A fresh
checked resume reproduced the stale-binding defect. No remote signature/readback
or receiver acceptance is claimed before the public packets are obtained.
