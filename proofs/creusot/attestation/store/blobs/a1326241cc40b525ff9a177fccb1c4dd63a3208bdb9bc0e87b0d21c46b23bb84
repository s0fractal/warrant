# What a proof attestation claims

A record in this store, signed by an actor that `trust.json` binds, claims this:

1. On the inputs named by its subject, `cargo creusot` reported every goal
   proved. The subject is a manifest: the SHA-256 and path of every proof
   input. Inputs are deny-by-default, defined in `tools/proof_attestation.py`:
   - every file of proofs/creusot except outputs, caches and prose (target/,
     this directory, .why3find/, *.coma, README.md, .gitignore);
   - every file its sources name by path (#[path], include!, include_str!,
     include_bytes!);
   - the Cargo configuration and toolchain files of its ancestor directories up
     to the repository root.
   Before signing, the attester also checks two things:
   - every repository file that rustc's dep-info says it read is in the manifest;
   - every input is tracked by git.
2. On the same inputs, `python3 mutants.py` reported every mutant killed.
3. The attached evidence holds the two logs and the environment: the Creusot
   commit, the platform, and the prover settings.

It does not cover the environment outside the repository: the toolchain, the
Creusot install, the provers, and `~/.cargo/config.toml` (where Creusot's
installer puts a `[patch]`). Those are recorded in the evidence, not checked.

It does not claim that CI re-ran anything. `tools/proof_attestation.py --check`
reports such a record as CLAIMED and never as PASSED. The actor is an agent key
(claude@warrant-proofs) and it is scoped to this directory: no other check in this
repository consults this trust file, so the key can vouch for proofs and nothing
else. Using it to skip a check that CI runs would need a separate decision.
