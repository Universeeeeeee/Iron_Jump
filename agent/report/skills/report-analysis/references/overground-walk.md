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
