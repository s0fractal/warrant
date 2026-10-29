"""Static meanings of the words warrant-agent/3 answers with (`explain`): what each means here and what
it does not establish. Nothing in this table comes from a record, a request or the configuration; a
test holds it to the engine's and the interface's tuples (every word they can answer with has an entry)."""

NOT_TRUTH = "It does not establish that the record's text or evidence is true."
NOTHING_WRITTEN = "Nothing was written."
TERMS = {
    # reliance of a lineage (docs/V3.md §10)
    "ELIGIBLE": ("Under this receiver's trust and profile the lineage is not forked, its effective version exists and "
                 "no counted challenge stands against it.",
                 "It does not establish that the source is complete (completeness stays UNATTESTED). " + NOT_TRUTH),
    "CHALLENGED": ("A challenge this receiver counts stands against the lineage's effective version.",
                   "It does not establish that the challenge is right; it holds reliance until a successor is effective."),
    "FORK": ("Two admitted versions succeed the same version: the lineage has no leaf and no state (§3). As a lineage "
             "verdict, every branch is listed and nothing is excluded.", "Neither branch is preferred."),
    # guard verdicts (§6)
    "PENDING": ("The version's guard waits: `waiting` names the attests by roles, or the required lineages not yet "
                "closed. As reliance: no version of the lineage is effective yet.", "Nothing is credited while it waits."),
    "MET": ("Enough distinct actors holding the guard's roles, none the version's own actor, attested it with the "
            "match, and every lineage it requires is closed.", "It rests on those actors' signatures. " + NOT_TRUTH),
    "NONE": ("The version has no guard and enters no closed state: it is effective as filed.", NOT_TRUTH),
    "OK": ("The lineage does not fork.", "It says nothing about its state."),
    # bases (§9)
    "SIGNED": ("A signature over the record's id verifies under a key this receiver's trust binds to its actor.",
               "The trust binds keys to actors; it authorizes nothing. " + NOT_TRUTH),
    "MIGRATED": ("The record has no signature; a migration@1 attest by an actor this receiver's profile names as "
                 "migrator lists it in its map.", "It is never a signature by the record's actor."),
    "UNSIGNED": ("A record with no signature that no accepted migration lists: rejected.", "Not credited."),
    "BAD_SIGNATURE": ("No signature of the record verifies under a key the trust binds to its actor: rejected.",
                      "It does not establish intent; another receiver's trust may bind another key."),
    "UNATTESTED": ("Completeness of the source: nothing shows that the view holds every record that exists.",
                   "A result never says nothing else was filed."),
    # problems (§§3-4, 9)
    "LINEAGE_BROKEN": ("A version names a predecessor that is not an admitted version of its kind and schema: it is "
                       "in no lineage.", "The record is still listed."),
    "LINEAGE_NOT_AUTHOR": ("A successor filed by an actor the schema does not allow for its state (the root's actor, "
                           "or the roles `successors` names): excluded.", "The record is still listed."),
    "LINEAGE_BACKDATED": ("A successor dated before what it succeeds. It still counts: the id witnesses the order.",
                          "Claimed time orders nothing."),
    "SCHEMA_NOT_COUNTED": ("A schema record whose body is not a schema body: no record is read under it. A valid "
                           "schema short of its quorum is not this problem; it waits in schemas_pending.",
                           "It may count for another receiver."),
    "SCHEMA_CONFLICT": ("A schema lineage forks, or two counted schema lineages name one name: every record of that "
                        "name is invalid until one is retired.", "Neither schema is preferred."),
    "INVALID": ("A record's body does not fit the schema this receiver counts, or its guard is weaker than the "
                "schema's minimal guard: listed, counted nowhere.", "It may be valid for another receiver."),
    "MIGRATION_MAP": ("A migration attest whose target is not a map blob in the view: it vouches for nothing.",
                      "Not credited."),
    "line": ("A line that is not a canonical {record, sig}, not a record, or too long: rejected.", "Not read."),
    # refusals of the interface (warrant_agent/errors.py)
    "BAD_REQUEST": ("The request is not one this interface reads.", "Nothing was read or written."),
    "UNSUPPORTED_VERSION": ("The configuration declares another agent_api.", "Nothing was read."),
    "NOT_PERMITTED": ("The operator did not permit this operation for the workspace.", "Nothing was read or written."),
    "UNKNOWN_WORKSPACE": ("No workspace of that handle is configured.", "Nothing was read."),
    "NOT_FOUND": ("No record or blob of that id (or prefix) is in the store, or a prefix names several.",
                  "It does not say it exists nowhere."),
    "CHAIN_MOVED": ("The signer's head moved since prepare: another record of the same actor was filed. Prepare again.",
                    NOTHING_WRITTEN),
    "RESOURCE_LIMIT": ("The store or a result exceeds a limit of the workspace or the engine.", "Nothing was assessed."),
    "NO_SIGNER": ("The workspace has no signer: prepare and commit need one.", NOTHING_WRITTEN),
    "SIGNER_NOT_TRUSTED": ("The signer's key is not a key the workspace's trust binds to its actor: its records would "
                           "be rejected.", NOTHING_WRITTEN),
    "INVALID_RECORD": ("The record is malformed, does not fit its schema, or its lineage rule refuses it.",
                       NOTHING_WRITTEN),
    "REFUSED": ("The store refused the write (for example a record dated before the signer's head).",
                NOTHING_WRITTEN),
}


def explain(word):
    means, not_ = TERMS[word]
    return {"word": word, "means": means, "does_not_establish": not_}
