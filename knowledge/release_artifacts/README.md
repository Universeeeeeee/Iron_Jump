# Frozen RAG release artifacts

This directory contains reviewed, canonical JSON artifacts promoted from
`data/knowledge/groundedness_review.json`. Production release gates must only
reference files in this tracked directory. Generated or pending local reviews
must never be used directly by the release gate.

Promotion requires every case from the frozen live benchmark exactly once and
binds the review to canonical catalog, manifest, recommendation prompt, and
benchmark-case content digests. Any content drift requires a new benchmark run
and human review before promotion.

Data-driven follow-ups carry `basis=data` and `data_evidence_refs` from validated
session evidence. They carry no literature citations and are produced independently
of the literature release gate. Text-only scenarios do not qualify as validated
session evidence, even if their prose or origin label says a change was verified.

Literature actions carry `basis=literature`. A paragraph's metric tags, measurement
agreement, ICC, or method keywords establish relevance only. Direct action support
must be explicitly reviewed in the indexed paragraph metadata under
`reviewed_action_support`, binding `action_id`, `metric_codes`, `quote`, and
`content_digest`, with `relation=direct_action_support` and
`review_status=approved`. The quote must occur in that exact paragraph and the
protocol and population checks still apply. No such annotations are created by
the model. Existing general source approvals do not imply action-level approval.

The 30 original text-only cases are scenario exercises. Their data traceability
and citation results remain unevaluated. Production acceptance additionally uses
numeric reports through the normal service, database, tools, validators, and
renderer. All generated review artifacts remain pending until human review.

Measurement-limitation actions use snapshot-bound failed comparison assessments
and their sample counts or referenced invalidating quality flags. They do not
require a supported change predicate. Absolute left/right level differences and
changes in variability are explicitly unsupported until matching deterministic
operators are connected.

The final renderer arbitrates all actions together by `(claim_id, metric_code)`
and displays at most three. It prioritizes a concrete verified limitation, then
an action with reviewed direct literature support, then a data follow-up. Ties
retain source order. Only citations referenced by selected actions are displayed.
