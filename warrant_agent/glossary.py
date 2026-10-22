"""Static meanings of the words warrant-agent/1 answers with (`explain`). Each entry
says what the word means here and what it does not establish. Nothing in this
table comes from a record, a request or the configuration."""

NOT_CREDITED, HOLDS = "Not credited.", "Holds every use."
TERMS = {
    # reliance of a capsule (SPEC §4.4)
    "ELIGIBLE": ("The receiver's own assessment of this frozen view lets the named use rely on this duty or "
                 "transition: its closure was admitted under the receiver's trust and profile (accepted by the "
                 "required actors, or replayed by the receiver for a computation) and nothing counted holds it.",
                 "It does not establish that the source is complete (completeness stays UNATTESTED), that "
                 "evidence text is true, or anything about records outside this view."),
    "NOT_CLOSED": ("The duty is not closed in this view: no closure of it was admitted. `closures` lists every "
                   "attempt with its verdict and why.",
                   "It does not say the claim is false; only that this receiver has not established it."),
    "CHALLENGED": ("A challenge by an actor this receiver's profile counts stands against the closure.",
                   "It does not establish that the challenge is right; it holds reliance until it is answered."),
    "UNASSESSED": ("The receiver's profile has no rule that would assess this (for a transition: the profile names "
                   "nobody whose acceptance closes results). Look at the duties the transition closes "
                   "(`closes` in its capsule) instead.",
                   "It is neither a pass nor a failure of the transition."),
    "STALE": ("A revalidation trigger fired, or the last observation is older than the duty allows; the closure "
              "must be revalidated.", "It does not say the closure was wrong when it was made."),
    "SUPERSEDED": ("A later transition supersedes this one.", "Rely on the superseding transition instead."),
    "CONTESTED": ("The duty has admitted closures of different kinds (e.g. discharged and declared impossible).",
                  "Neither closure is preferred by this layer."),
    "MISSING": ("The target is not in this view.", "It does not say the record does not exist elsewhere."),
    # candidate verdicts (closure attempts)
    "ADMITTED": ("This closure item meets the duty's condition in this view.",
                 "For an attested basis it rests on the named acceptors' signatures, not on a check of the work."),
    "PENDING": ("The closure item waits for acceptances (`waiting_for`).", "Nothing is credited while it waits."),
    "UNVERIFIED": ("A replayed (computation) closure that this receiver could not verify: no accepted provider, "
                   "bytes missing, or its own replay disagreed with the receipt (`why` says which).",
                   NOT_CREDITED + " A disagreeing replay is this receiver's result, not proof of intent."),
    "OVERCLAIMED": ("The item's basis is not one the duty's condition admits (e.g. attested where a replay or an "
                    "observation is required).", NOT_CREDITED),
    "MISSING_EVIDENCE": ("The item does not cite the evidence its basis needs (e.g. exactly one receipt).",
                         NOT_CREDITED),
    "UNMET_CONDITION": ("The cited evidence does not meet the duty's condition.", NOT_CREDITED),
    # use decision
    "WITHIN_POLICY": ("Every target and the delivery meet the receiver's local use policy now.",
                      "A local policy decision over the assessment; not a new fact about the work."),
    "HOLD": ("At least one reason in `use.reasons` keeps the use from relying on the targets now.",
             "It does not say which claim is false; read each capsule's reliance."),
    # delivery relations
    "MATCH_EXPECTED_SET": ("The delivered bytes are exactly the set the receiver's configured expectation names.",
                           "The selected set arrived, nothing more: the sender's global completeness stays "
                           "UNATTESTED."),
    "UNPINNED": ("No receiver expectation was named, so the delivery is checked only for internal consistency.",
                 "A manifest digest inside the package is never an expectation. warrant_workspace lists the "
                 "configured expectation handles."),
    "LOCAL_CAPTURE": ("A view of the receiver's own store, with no transfer.", ""),
    "MISSING_DECLARED_BYTES": ("Objects the manifest declares are not in the payload.", HOLDS),
    "CONTENT_MISMATCH": ("Delivered bytes do not hash to their ids, or differ from the manifest.", HOLDS),
    "WRONG_SET": ("The manifest is not the one the receiver's expectation names.", HOLDS),
    "WRONG_SOURCE": ("The manifest names another source than the expectation.", HOLDS),
    "UNVERIFIED_EXPORTER": ("No declaration by the expected exporter verifies under the receiver's trust.",
                            HOLDS),
    "UNATTESTED": ("Completeness of the source is never attested by this layer.", ""),
    "invalid": ("Records in the view that do not authenticate under the receiver's trust (wrong key for the "
                "named actor, not canonical, wrong id). They take part in nothing.",
                "An invalid acceptance closes nothing, whatever actor it names."),
    # refusal codes
    "BAD_REQUEST": ("The request's shape is wrong; the message says which member and, for a record body, "
                    "`details.template` shows the smallest valid body.", ""),
    "UNKNOWN_WORKSPACE": ("The workspace is not configured; warrant_workspace lists the configured ones.", ""),
    "UNKNOWN_EXPECTATION": ("The expectation is not a configured handle of this workspace; warrant_workspace "
                            "lists them.", ""),
    "NOT_PERMITTED": ("The operator did not permit this operation for this workspace.", ""),
    "VIEW_UNKNOWN": ("No such view token in this workspace; a view token comes from warrant_context, an inspect, "
                     "or a read/export/prepare without one.", ""),
    "VIEW_EXPIRED": ("The view is older than the workspace's view_ttl; open a new one.", ""),
    "NOT_FOUND": ("The id is not in this view or store; nothing is fetched from elsewhere.", ""),
    "CONFLICT": ("The request id was used with other inputs, or the store holds other bytes under the id.", ""),
    "NO_SIGNER": ("The operator configured no signer for this workspace; nothing can be committed.", ""),
    "SIGNER_CHANGED": ("The configured signer is not the one the draft was prepared for.", ""),
    "IMPORT_BLOCKED": ("The staged package may not be promoted (its delivery relation, a changed expectation, or "
                       "records that do not authenticate).", "Inspecting it is still possible."),
    "PROVIDER": ("The computation provider is missing or was stopped; nothing was stored.", ""),
    "REFUSED": ("The provider refused the input.", ""),
    "RESOURCE_LIMIT": ("A configured limit was exceeded; nothing was assessed or exported.", ""),
}


def explain(term):
    if term in TERMS:
        means, not_ = TERMS[term]
        return {"term": term, "means": means, "does_not_establish": not_}
    return {"term": term, "unknown": True, "terms": sorted(TERMS)}
