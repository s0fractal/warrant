# Review manifests

One JSON file per review document, recording the provenance a census cannot:
which vendor and model, run against which commit, shown what, blind to what,
stopped by whom. Introduced 2026-08-27 on a finding from the chatgpt-web
paper review: the ledger's "N reviews from M vendors" verifies our filename
ontology, not reviewer independence — these manifests carry the fields an
independence claim would actually need.

**Rules.**

- A manifest states only what is *known*; every unknowable field carries the
  literal string `"unrecorded"` rather than a guess. A backfilled manifest
  says `"backfilled": true` and is evidence of process, not of provenance.
- From 2026-08-27 on, a new review lands **with** its manifest in the same
  commit; a review without one is counted in the census and in nothing
  stronger.
- The planned *audit experience report* paper may count a review toward any
  independence-shaped metric **only if** its manifest records
  `prior_reviews_visible`, `prompt_sha256` and `stopping_criterion` as known
  values — which no backfilled manifest does. That is the point.

**Fields** (`review-manifest@v0`; closed set, unknown members invalid):

| field | meaning |
| --- | --- |
| `manifest` | exactly `"review-manifest@v0"` |
| `review_file` | the ledger filename this manifest describes |
| `artifact_commit` | commit the reviewer's input was taken from, or `"unrecorded"` |
| `reviewer_vendor` / `reviewer_model` | vendor; model or surface as precisely as known |
| `session` | operator's session identifier, or `"unrecorded"` |
| `prompt_sha256` | SHA-256 of the exact prompt, or `"unrecorded"` |
| `context_sha256` | SHA-256 of the packet the reviewer saw, or `"unrecorded"` |
| `prior_reviews_visible` | `true` / `false` / `"unrecorded"` |
| `web_access` | `true` / `false` / `"unrecorded"` |
| `stopping_criterion` | who/what ended the review, or `"unrecorded"` |
| `orchestrator` / `adjudicator` | who ran it; who judged the findings |
| `backfilled` | `true` if written after the fact |
| `notes` | free text, honesty over brevity |
