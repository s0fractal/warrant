# WRT-012 review repair

Based on review of 8bb3fdf. This is a bounded **byte equality** verifier,
not a replacement for check_claims.py or a claim that a PDF's propositions hold.
The expected digest and trusted checker digest are canonical policy operands,
bound by the commitment's closure field. The subject bytes must match the
commitment. No supplied Python, imported dependency or argv is executed.

`report` replays this built-in predicate from pinned stored operands. A saved
result disagreeing with replay is refused. A fabricated consistent record cannot
make incorrect bytes pass this predicate; it also cannot prove a past execution,
and the output explicitly states REPLAYED_NOW_NOT_HISTORICAL_ATTESTATION.
The caller still chooses the commitment/policy to trust. Runtime/stdlib trust
remains with the host; this is not a reproducible arbitrary execution environment.

F1: old unsigned run claims are NOT_RUN / UNVERIFIED_LEGACY_RUN_CLAIM.
F2: subject bytes are checked against the commitment before any write.
F3: arbitrary script execution is disabled with UNBOUND_EXECUTION_UNSUPPORTED.
The supported policy pins this tool's code; changed checker bytes refuse replay.
A real check_claims adapter with bound paper/source/repository/PDF relationships
remains deferred. The old experiment's recorded PASS is historical evidence of
what the old implementation printed, not current verified credit.
F4: create-exclusive reservation prevents repeated publication. Interrupted runs
stay RESERVED and report NOT_RUN / RUN_INCOMPLETE. Automatic retry recovery is
not implemented. Repeated calls may repeat pure input checks, never execute a
verifier process. File fsync is not cross-file power-loss atomicity or protection
against the host owner rewriting all files.
F5: receipt.holder must equal the configured identity even with a matching key.
F6: CLI hashes the exact configuration bytes read once, reports their digest,
the parsed holder configuration digest, tool identity and effective path limit.
Those pins document trust inputs; they do not authenticate the caller's choice.

The repair driver writes a predeclared protocol before executing four offline
endpoints. It preserves the original e2e-001 artifacts unchanged, and creates a
separate byte-check fixture. All four repair endpoints passed. It neither stamps
nor upgrades a timestamp. No independent holding or normative adoption is claimed.

Validation commands (from repository root):

```sh
python3 tests/witness.py
python3 tests/witness_bindings.py
python3 tests/witness_binding_mutations.py
python3 experiments/wrt-012-repair-001/run.py --output /tmp/new-witness-repair
```

On the recorded interpreter with OTS installed: 48 existing-profile checks pass
(the old unbound execution assertions were replaced with seven bounded-profile
checks), 10 new regression tests pass, five existing plus four new mutations are
caught. The new mutation runner requires assertion failures, not harness errors.
CI now invokes all three suites. Environments lacking OTS still explicitly skip
the existing optional OTS tests; no Bitcoin validation is claimed in either case.
