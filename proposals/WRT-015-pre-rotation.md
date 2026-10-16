# WRT-015: Pre-rotation — a retired key can no longer rotate

**Status:** ADOPTED by the owner 2026-10-16 ("pre-rotation, як у KERI —
приймаю"; there are no users besides the repository itself, so the SPEC may
change). Implemented red-first: the countervector lands failing, then the
three implementations are changed until it passes.

## 1. The defect (DeepReview R13)

`tests/r13_retired_key_denial.py`, reproduced in Python and Go: `a@x` rotates
`a_old → a_new`, then `a_old` leaks. Rotation authorization is judged at the
record's DAG position, so the attacker can sign, with `a_old` alone, a rotation
`a_old → a_fork` at the root position, where `a_old` was current. It is
authorized. Key-state conflict is store-wide, so `a@x` becomes conflicted
everywhere, and every signature `a@x` ever made, the genesis root included,
reports `unbound`. **One retired key is enough to deny an actor's whole
history.**

## 2. The rule

Following KERI's pre-rotation (Smith, *Key Event Receipt Infrastructure*, 2019):
each key state commits in advance to the digest of its successor. A rotation
must reveal a key matching that commitment.

- **Key blob.** `{"actor": <string>, "key": <hex64>, "next": <hex64>}`, where
  `next` is the lowercase-hex SHA-256 of the next public key's 32 raw bytes.
  `next` is optional. A key blob without it, including the legacy
  `{"actor","key"}` form, makes the introduced key **terminal**: no rotation
  away from it is ever authorized.
- **Genesis commitment.** The trust configuration (SPEC §12) gains an optional
  `"next": {<actor>: <hex64>}` member. An actor with genesis keys but no
  `next` entry is terminal at genesis.
- **Authorization (added to SPEC §5.1).** A rotation for actor `A` at record
  `W` is authorized only if `A`'s key state at `W`'s DAG position carries a
  commitment `c`, and `SHA-256(incoming key) = c`. This is in addition to the
  existing requirements (proof of possession by the incoming key;
  authorization under the current policy). It replaces none of them.

## 3. What it closes, and what it does not

- **Closed:** a retired key alone can no longer rotate. At any past position
  the committed successor is a key the attacker must also hold. R13's attack
  now fails, and a test checks that.
- **Not closed (residual, stated):** a holder of *both* a key and its committed
  successor can still file a second rotation at that position, introducing the
  same successor with a different `next`. The result is a key-state conflict,
  as before. Since the successor is the current or a later signing key, this
  needs a compromise of the current key, which already lets the attacker sign
  as the actor. KERI resolves such duplicity with first-seen ordering by
  witnesses. A DAG without a total order cannot. WRT-012 (external witnessing)
  is where that would come from.
- **Cost:** an actor who wants to rotate must decide its next key before it
  needs it, and keep that key unused and offline until the rotation. That is
  the point of the rule, not a side effect.

## 4. Transition

There are no deployed stores with rotations. The repository's own stores
contain none, which was checked before the change. Tests and generators that
built rotations without commitments are updated to commit. A rotation filed
under the old rule becomes unauthorized: its incoming key is never bound, and
it can no longer cause a conflict.
