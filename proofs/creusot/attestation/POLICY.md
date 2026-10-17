# What a proof attestation claims

A record in this store, signed by an actor that `trust.json` binds, claims this:

1. On the inputs named by its subject (a manifest: SHA-256 and path of every proved
   impl-rs file and of every file under proofs/creusot except this directory),
   `cargo creusot` reported every goal proved.
2. On the same inputs, `python3 mutants.py` reported every mutant killed.
3. The attached evidence holds the two logs and the environment: the Creusot
   commit, the platform, and the prover settings.

It does not claim that CI re-ran anything. `tools/proof_attestation.py --check`
reports such a record as CLAIMED and never as PASSED. The actor is an agent key
(claude@warrant-proofs) and it is scoped to this directory: no other check in this
repository consults this trust file, so the key can vouch for proofs and nothing
else. Using it to skip a check that CI runs would need a separate decision.
