---
name: report-analysis
description: Use when the Report Agent must choose the next evidence-producing analysis action for a Jump Test, treadmill gait/running, or overground walking/running report from AgentObservation and AnalysisState.
---

# Report Analysis

## Objective

Choose one high-value, deterministically verifiable hypothesis at a time. Use the
Observation as a source of candidate patterns, not as Evidence. Allow a normal stop
when no worthwhile hypothesis remains.

## Decide the Next Action

1. Read the current Observation, AnalysisState, latest Evidence, remaining budget,
   and enabled capabilities.
2. Remove hypotheses that are already tested, duplicate a prior semantic request,
   require unavailable data, or cannot satisfy a method's stated preconditions.
3. Compare the remaining hypotheses by:
   - plausibility in the visible data;
   - ability to explain more than one observation;
   - ability to distinguish competing explanations;
   - expected information gain relative to Tool cost.
4. Select exactly one hypothesis and one enabled deterministic analysis method, or
   stop. Do not fill the Tool budget merely because it is available.
5. After Evidence returns, update the hypothesis as `supported`, `not_supported`,
   `inconclusive`, or `tool_failed`, then reconsider the next action from the new
   state.

## Analysis Priorities

- Address data quality first only when it invalidates the report or affects the
  candidate metric. Missing values in unrelated, unpopulated catalog metrics do not
  justify a quality action.
- Prefer the clearest varying metric or side-by-segment pattern visible in the
  Observation.
- Test cross-metric co-change only when both aligned metrics visibly change. Do not
  pair a varying metric with a constant metric to prove that the change is isolated.
- Test exclusion robustness only after an earlier Tool result supports the pattern
  and excluded records exist. Observation is not Evidence, so exclusion robustness
  is never the initial action.
- Do not call a Tool merely to prove that an absent pattern is absent.
- Do not infer fatigue, mechanism, diagnosis, injury risk, causality, or training
  advice from a descriptive pattern.

## Evidence Discipline

Treat only deterministic Tool output as data Evidence. `inconclusive` means the data
cannot answer the hypothesis; it is not a negative result. Bind final derived Claims
only to exact, supported Predicate Evidence. The system loads
`references/evidence-guidelines.md` before claim synthesis; request it earlier only
when Evidence conflicts or its detail is needed for the next decision.

## Decision Output

Return exactly one typed decision per turn:

- `NextAnalysisAction`: test one hypothesis with one enabled Tool and analysis method;
- `LoadSkillResource`: load one available reference when its detail is needed;
- `StopAnalysis`: stop normally with an explicit reason.

Do not output a plan, DAG, second candidate, follow-up check, robustness check, or
quality check in the same turn. Reconsider other candidates only after Evidence
updates `SequentialAnalysisState`.

## Progressive Disclosure

Load exactly one domain reference from `report_context.test_type` before choosing the
first hypothesis:

- `Jump Test` → `references/jump.md`
- `Treadmill Gait Test` → `references/gait.md`
- `Treadmill Running Test` → `references/running.md`
- `Sprint and Gait Test` → `references/overground-walk.md`
- `Overground Running Test` → `references/overground-run.md`

Do not load unrelated domain references. The system, not the model, resolves this
mapping. Do not request a domain reference that is already present in
`loaded_skill_references`.

## Stop Normally

Stop when no untested high-value hypothesis remains, method preconditions cannot be
met, further analysis would only repeat or confirm an already settled point, or the
Tool budget is exhausted. An empty set of derived Claims is valid.
