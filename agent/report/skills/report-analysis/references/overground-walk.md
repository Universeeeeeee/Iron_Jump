# Overground Walking Analysis Prior

Analyze one single-person, one-direction passage. This is not a treadmill test.
Lengths are measured from optical contact centers in metres; timing uses device
samples in seconds. Read units from the package, never infer them from legacy UI
field names. Passage speed describes progression of contact positions, not a
centre-of-mass measurement or a standard-distance sprint result.

Keep ground_contact, ground_step and ground_cycle records separate. Do not align
them by ordinal to create cross-metric pairs. Walking stride length is supplied as
a summary fact; do not invent a per-cycle stride from the separate length array.
Excluded contacts remain visible; steps and cycles contain only the producer's
accepted associations. Their absence does not prove there were no invalid events.

Inspect missing values, stops, excluded contacts and acquisition issues before
choosing a candidate metric. Unknown A/B identity is not anatomical left/right.
Even named sides depend on manual first-foot input and alternation; they are not
independent visual truth. Never compare unknown sides as if they were left/right.

Use the frozen device/config snapshot for actual segment geometry, omitted
segments and optical quality. Do not infer measurement accuracy from segment
count. Do not interpolate across missing observations, infer unobserved steps,
or treat excluded stationary contact time as walking support time.

Single passages often contain too few observations for temporal or side
comparisons. Respect the deterministic method's sample requirements and accept
inconclusive evidence or a normal stop. Describe only supported within-session
patterns; do not infer fatigue, diagnosis, injury risk or training benefit.

## Primary displayed measurements

The report overview, PDF and identified-footprint Excel sheet use the shared
`payload.recognized_measurements` policy. Use `recognized_step_length_m`,
`recognized_speed_m_s`, `recognized_cadence_per_min` and
`recognized_contact_time_s` for questions about those displayed values. Their
scalar facts and sample sets are authoritative; do not replace them with older
`ground_step` or `ground_cycle` averages, which use different reference points
or inclusion rules. Name the reference and sample count when comparing them.

`recognized_footprint` keeps every accepted landing, but each metric is valid
independently. An interval with an unresolved intermediate candidate is retained
as an interval observation, not a single step. `observed_span_s` is an optical
occupancy span and must never be described as a measured single-foot contact or
included in contact-time averages. Stops remain visible and are excluded from
moving-contact means. New onset references are independent of the confirmation
threshold; older snapshots may instead retain validated stance/toe references.
Do not mix different position-reference types within one spatial comparison.
