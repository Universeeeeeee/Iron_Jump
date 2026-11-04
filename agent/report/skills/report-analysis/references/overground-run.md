# Overground Running Analysis Prior

Analyze one single-person, one-direction ground passage, not a treadmill run or
a standard-distance sprint. Spatial metrics use a stable optical toe proxy in
metres. This differs from the contact-center reference used for ground walking.
Read SI units from the package and do not add belt displacement.

Each contact, step and cycle metric has independent validity. A missing flight
estimate does not invalidate an otherwise measured step length; missing values
are never zero. Valid zero flight and double support remain real zero values.
Do not classify a passage as walking solely because one cycle has no flight.

Keep ground_contact, ground_step and ground_cycle records separate. Cross-metric
analysis requires aligned valid values in the same record set. Summary group
means and distance/time aggregate speed have different denominators; do not merge
them or recompute a formal report number from a different subset.

Check source quality, stops, incomplete contacts and gaps. A/B labels are not
anatomical left/right. Named sides depend on manual first-foot selection and
alternation, not independently verified visual identification. Do not pair
independent left and right cycles or force a side comparison with unknown labels.

Use actual device/config snapshots and exclusion evidence; never assume that
all nominal segments were usable. Do not create steps or cycles across rejected
associations. Small samples must yield inconclusive evidence or a normal stop.
Describe only verified within-session patterns, without causal, diagnostic or
training-effect claims. Ground running has no approved matching literature
source at present; do not borrow treadmill training evidence.

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
