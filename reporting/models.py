"""Versioned semantic evidence models for deterministic report analysis."""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from knowledge.models import Citation, LiteratureEvidence, RAGAudit, Recommendation


TestType = Literal[
    "Jump Test",
    "Treadmill Gait Test",
    "Treadmill Running Test",
]
DataScope = Literal["current_session", "longitudinal", "cohort"]
AnalysisToolName = Literal[
    "analyze_current_session",
    "compare_longitudinal",
    "compare_cohort",
]


_TOOL_BY_SCOPE = {
    "current_session": "analyze_current_session",
    "longitudinal": "compare_longitudinal",
    "cohort": "compare_cohort",
}
_LEGACY_TOOL_VERSION_BY_SCOPE = {
    "current_session": "legacy-tool/1.0",
    "longitudinal": "legacy-tool/1.0",
    "cohort": "legacy-tool/1.0",
}
_METHOD_VERSION_BY_NAME = {
    "verify_temporal_change": "temporal-change-method/1.0",
    "verify_side_segment_difference": "side-segment-difference-method/1.0",
    "verify_cross_metric_cochange": "cross-metric-cochange-method/1.0",
    "verify_exclusion_robustness": "exclusion-robustness-method/1.0",
    "quality_scope_check": "quality-scope-check-method/1.0",
}


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReportContextInput(FrozenModel):
    session_id: int = Field(gt=0)
    test_type: TestType
    started_at: str = ""
    finished_at: str | None = None
    subject_id: int | None = None
    team_id: int | None = None
    is_temporary: bool = False
    subject_snapshot: dict[str, Any] = Field(default_factory=dict)
    team_snapshot: dict[str, Any] = Field(default_factory=dict)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)


class ReportMetadata(FrozenModel):
    package_id: str
    schema_version: str
    builder_version: str
    session_id: int
    test_type: TestType
    started_at: str = ""
    finished_at: str | None = None
    subject_id: int | None = None
    team_id: int | None = None
    is_temporary: bool = False
    package_digest: str = ""


class MetricDefinition(FrozenModel):
    metric_code: str
    unit: str
    label: str
    record_types: tuple[str, ...]
    numeric_tolerance: float = Field(ge=0)


class MetricValue(FrozenModel):
    metric_code: str
    value: float | None = None
    state: Literal["present", "missing", "invalid"] = "present"
    reason: str | None = None

    @model_validator(mode="after")
    def validate_state(self):
        if self.state == "present":
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("present metric values must be finite")
            if self.reason is not None:
                raise ValueError("present metric values cannot have a missing reason")
        else:
            if self.value is not None:
                raise ValueError("missing or invalid metric values cannot carry a value")
            if not self.reason:
                raise ValueError("missing or invalid metric values require a reason")
        return self


class RecordStatus(FrozenModel):
    validity: Literal["valid", "invalid"]
    inclusion: Literal["included", "excluded"]
    event_status: str | None = None
    exclusion_reason: str | None = None


class SemanticRecord(FrozenModel):
    record_id: str
    ordinal: int = Field(ge=0)
    source_index: int | None = None
    timestamp_s: float | None = None
    side: Literal["left", "right", "unknown"] | None = None
    status: RecordStatus
    quality_flag_ids: tuple[str, ...] = ()
    values: dict[str, MetricValue]

    @field_validator("timestamp_s")
    @classmethod
    def finite_timestamp(cls, value: float | None):
        if value is not None and not math.isfinite(value):
            raise ValueError("timestamp must be finite")
        return value


class RecordSet(FrozenModel):
    record_set_id: str
    record_type: Literal["jump", "step", "gait_cycle"]
    metric_codes: tuple[str, ...]
    records: tuple[SemanticRecord, ...]


class RecordSetDescriptor(FrozenModel):
    record_set_id: str
    record_type: str
    record_count: int = Field(ge=0)
    metric_codes: tuple[str, ...]
    has_sequence: bool
    has_side: bool


class SeriesDescriptor(FrozenModel):
    series_id: str
    record_set_id: str
    metric_code: str
    value_count: int = Field(ge=0)


class ScalarFact(FrozenModel):
    fact_id: str
    metric_code: str
    statistic: Literal["value", "count", "mean", "min", "max", "std", "cv_percent"]
    value: float | None = None
    unit: str
    sample_count: int | None = Field(default=None, ge=0)
    state: Literal["present", "missing"] = "present"
    missing_reason: str | None = None
    source_ref: str

    @model_validator(mode="after")
    def validate_value(self):
        if self.state == "present":
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("present facts must be finite")
            if self.missing_reason is not None:
                raise ValueError("present facts cannot have a missing reason")
        else:
            if self.value is not None or not self.missing_reason:
                raise ValueError("missing facts require a reason and no value")
        return self


class QualityFlag(FrozenModel):
    quality_flag_id: str
    code: str
    severity: Literal["info", "warning", "error"]
    scope: Literal["record", "record_set", "report"]
    source_ref: str
    invalidates_metric_codes: tuple[str, ...] = ()
    invalidates_report: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class ProvenanceRecord(FrozenModel):
    provenance_id: str
    source_type: Literal["test_report", "report_snapshot", "analysis_kernel"]
    source_ref: str
    operation: str
    implementation_version: str
    input_refs: tuple[str, ...] = ()


class ToolRunRecord(FrozenModel):
    tool_run_id: str
    tool_name: AnalysisToolName
    tool_version: str
    analysis_method: str
    analysis_method_version: str
    kernel_version: str | None = None
    data_scope: DataScope
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    parameters: dict[str, Any] = Field(default_factory=dict)
    input_digest: str | None = None
    output_digest: str

    @model_validator(mode="before")
    @classmethod
    def read_legacy_audit_fields(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy_method = data.pop("operator", None)
        legacy_method_version = data.pop("operator_version", None)
        if legacy_method is not None:
            data.setdefault("analysis_method", legacy_method)
        if legacy_method_version is not None:
            data.setdefault("analysis_method_version", legacy_method_version)
        scope = data.get("data_scope")
        if scope in _TOOL_BY_SCOPE:
            data.setdefault("tool_name", _TOOL_BY_SCOPE[scope])
            data.setdefault("tool_version", _LEGACY_TOOL_VERSION_BY_SCOPE[scope])
        method = data.get("analysis_method")
        if method in _METHOD_VERSION_BY_NAME:
            data.setdefault("analysis_method_version", _METHOD_VERSION_BY_NAME[method])
        return data


class JumpPayload(FrozenModel):
    kind: Literal["jump"] = "jump"
    record_set_ids: tuple[str, ...]
    quality_notice_refs: tuple[str, ...] = ()


class TreadmillGaitPayload(FrozenModel):
    kind: Literal["treadmill_gait"] = "treadmill_gait"
    step_record_set_id: str
    gait_cycle_record_set_id: str


class TreadmillRunningPayload(FrozenModel):
    kind: Literal["treadmill_running"] = "treadmill_running"
    step_record_set_id: str
    gait_cycle_record_set_id: str


ReportPayload = JumpPayload | TreadmillGaitPayload | TreadmillRunningPayload


class ReportDataPackage(FrozenModel):
    metadata: ReportMetadata
    context: ReportContextInput
    metric_definitions: tuple[MetricDefinition, ...]
    scalar_facts: tuple[ScalarFact, ...]
    record_sets: tuple[RecordSet, ...]
    quality_flags: tuple[QualityFlag, ...]
    provenance: tuple[ProvenanceRecord, ...]
    payload: ReportPayload = Field(discriminator="kind")

    def resolve_ref(self, ref: str) -> object | None:
        if ref == self.metadata.package_id:
            return self.metadata
        for collection in (
            self.scalar_facts,
            self.record_sets,
            self.quality_flags,
            self.provenance,
        ):
            for item in collection:
                for key in (
                    "fact_id",
                    "record_set_id",
                    "quality_flag_id",
                    "provenance_id",
                ):
                    if getattr(item, key, None) == ref:
                        return item
                if isinstance(item, RecordSet):
                    for record in item.records:
                        if record.record_id == ref:
                            return record
        return None


class ReportManifest(FrozenModel):
    package_id: str
    package_digest: str
    test_type: TestType
    record_sets: tuple[RecordSetDescriptor, ...]
    series: tuple[SeriesDescriptor, ...]
    fact_refs: tuple[str, ...]
    quality_flag_refs: tuple[str, ...]
    available_dimensions: tuple[str, ...]
    manifest_version: str


class DataScopeAvailability(FrozenModel):
    current_session: bool = True
    longitudinal_candidates: int = Field(default=0, ge=0)
    cohort_candidates: int = Field(default=0, ge=0)
    longitudinal_available: bool = False
    cohort_available: bool = False
    reasons: tuple[str, ...] = ()


class DataAccessScope(FrozenModel):
    current_session: Literal[True] = True
    longitudinal: bool = False
    cohort: bool = False


class AnalysisMethodCapability(FrozenModel):
    analysis_method: str
    analysis_method_version: str
    dimensions: tuple[str, ...]
    metric_codes: tuple[str, ...] = ()
    enabled: bool
    unavailable_reason: str | None = None


class AnalysisToolCapability(FrozenModel):
    tool_name: AnalysisToolName
    tool_version: str
    required_scope: DataScope
    enabled: bool
    available_methods: tuple[AnalysisMethodCapability, ...]
    unavailable_reason: str | None = None


class SummaryValue(FrozenModel):
    metric_code: str
    count: int = Field(ge=0)
    mean: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    unit: str


class SegmentSummary(FrozenModel):
    record_set_id: str
    segment_index: int = Field(ge=0, le=3)
    start_ordinal: int = Field(ge=0)
    end_ordinal: int = Field(ge=0)
    side: Literal["left", "right"] | None = None
    metrics: tuple[SummaryValue, ...]


class CrossMetricAlignedView(FrozenModel):
    record_set_id: str
    segment_index: int = Field(ge=0, le=3)
    record_refs: tuple[str, ...]
    metric_summaries: tuple[SummaryValue, ...]


class AnalysisSketch(FrozenModel):
    overall: tuple[SummaryValue, ...]
    temporal_segments: tuple[SegmentSummary, ...]
    side_segments: tuple[SegmentSummary, ...]
    cross_metric_aligned: tuple[CrossMetricAlignedView, ...]


class CompactSeriesRow(FrozenModel):
    record_ref: str
    ordinal: int
    timestamp_s: float | None = None
    side: Literal["left", "right", "unknown"] | None = None
    inclusion: Literal["included", "excluded"]
    validity: Literal["valid", "invalid"]
    quality_flag_refs: tuple[str, ...]
    values: dict[str, float | None]


class CompactSessionSeries(FrozenModel):
    record_set_id: str
    metric_codes: tuple[str, ...]
    rows: tuple[CompactSeriesRow, ...]
    total_rows: int = Field(ge=0)
    returned_rows: int = Field(ge=0)
    sampling_policy: str


class QualitySummary(FrozenModel):
    total_flags: int = Field(ge=0)
    flags_by_code: dict[str, int]
    excluded_records: int = Field(ge=0)
    invalid_records: int = Field(ge=0)
    missing_values: int = Field(ge=0)
    invalidates_report: bool


class ScreeningCue(FrozenModel):
    cue_code: Literal[
        "quality_flag_present",
        "excluded_records_present",
        "missing_values_present",
        "segment_summary_available",
        "side_summary_available",
    ]
    source_refs: tuple[str, ...]


class AgentObservation(FrozenModel):
    report_context: ReportContextInput
    report_manifest: ReportManifest
    authoritative_facts: tuple[ScalarFact, ...]
    analysis_sketch: AnalysisSketch
    compact_session_series: tuple[CompactSessionSeries, ...]
    quality_summary: QualitySummary
    screening_cues: tuple[ScreeningCue, ...]
    data_scope_availability: DataScopeAvailability
    authorized_data_scopes: DataAccessScope
    available_analysis_capabilities: tuple[AnalysisToolCapability, ...]
    source_refs: tuple[str, ...]
    builder_version: str


class AnalysisQuestion(FrozenModel):
    question_id: str
    description: str
    dimensions: tuple[str, ...]
    metric_codes: tuple[str, ...]
    reason: str
    stop_condition: str


class AnalysisNode(FrozenModel):
    node_id: str
    tool_name: AnalysisToolName
    analysis_method: str
    inputs: dict[str, Any]
    dependencies: tuple[str, ...] = ()
    question_id: str
    purpose: str

    @model_validator(mode="before")
    @classmethod
    def read_legacy_node_fields(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy_method = data.get("operator")
        if legacy_method is not None:
            if "analysis_method" in data:
                return data
            data.pop("operator")
            data.setdefault("analysis_method", legacy_method)
        legacy_scope = data.get("data_scope")
        if legacy_scope in _TOOL_BY_SCOPE:
            if "tool_name" in data:
                return data
            data.pop("data_scope")
            data.setdefault("tool_name", _TOOL_BY_SCOPE[legacy_scope])
        return data


class SmallAnalysisPlan(FrozenModel):
    questions: tuple[AnalysisQuestion, ...] = Field(max_length=3)
    nodes: tuple[AnalysisNode, ...] = Field(max_length=3)


class ValidatedAnalysisPlan(FrozenModel):
    plan: SmallAnalysisPlan
    execution_order: tuple[str, ...]
    request_hashes: tuple[str, ...]
    total_cost: int = Field(ge=0)


MvpPredicate = Literal[
    "increase",
    "decrease",
    "persistent",
    "transient",
    "concentrated_on_side",
    "co_change",
    "remains_after_exclusion",
    "comparison_supported",
]


class HypothesisTarget(FrozenModel):
    hypothesis_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    dimensions: tuple[str, ...]
    metric_codes: tuple[str, ...]
    target_predicate: MvpPredicate
    reason: str = Field(min_length=1)
    success_condition: str = Field(min_length=1)


class NextAnalysisAction(FrozenModel):
    decision_type: Literal["analyze"] = "analyze"
    action_id: str = Field(min_length=1)
    hypothesis: HypothesisTarget
    tool_name: AnalysisToolName
    analysis_method: str = Field(min_length=1)
    inputs: dict[str, Any]
    purpose: str = Field(min_length=1)


class LoadSkillResource(FrozenModel):
    decision_type: Literal["load_skill_resource"] = "load_skill_resource"
    reference_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class StopAnalysis(FrozenModel):
    decision_type: Literal["stop"] = "stop"
    reason_code: Literal[
        "evidence_sufficient",
        "no_high_value_hypothesis",
        "method_preconditions_unmet",
        "budget_exhausted",
        "no_authorized_capability",
    ]
    reason: str = Field(min_length=1)
    unresolved_hypothesis_ids: tuple[str, ...] = ()


AnalysisDecision: TypeAlias = Annotated[
    NextAnalysisAction | LoadSkillResource | StopAnalysis,
    Field(discriminator="decision_type"),
]


class ValidatedAnalysisAction(FrozenModel):
    action: NextAnalysisAction
    question: AnalysisQuestion
    node: AnalysisNode
    required_scope: DataScope
    request_hash: str = Field(min_length=64, max_length=64)
    cost: int = Field(ge=0)


class HypothesisEvaluation(FrozenModel):
    target: HypothesisTarget
    status: Literal[
        "active",
        "supported",
        "not_supported",
        "inconclusive",
    ]
    request_hash: str = Field(min_length=64, max_length=64)
    evidence_refs: tuple[str, ...] = ()
    predicate_evidence_refs: tuple[str, ...] = ()


class PredicateEvidence(FrozenModel):
    predicate_evidence_id: str = ""
    predicate: MvpPredicate
    supported: bool
    metric_codes: tuple[str, ...]
    details: dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(FrozenModel):
    evidence_id: str
    node_id: str
    question_id: str
    tool_name: AnalysisToolName
    analysis_method: str
    analysis_status: Literal["conclusive", "inconclusive"] = "conclusive"
    record_set_id: str | None = None
    predicates: tuple[PredicateEvidence, ...]
    numeric_values: dict[str, float] = Field(default_factory=dict)
    numeric_units: dict[str, str] = Field(default_factory=dict)
    sample_counts: dict[str, int] = Field(default_factory=dict)
    record_refs: tuple[str, ...] = ()
    quality_flag_refs: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    tool_run_id: str
    provenance_id: str

    @model_validator(mode="before")
    @classmethod
    def read_legacy_method_field(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy_method = data.pop("operator", None)
        if legacy_method is not None:
            data.setdefault("analysis_method", legacy_method)
        if "tool_name" not in data:
            data["tool_name"] = "analyze_current_session"
        return data


class EvidenceBundle(FrozenModel):
    package_id: str
    package_digest: str
    items: tuple[EvidenceItem, ...]
    tool_runs: tuple[ToolRunRecord, ...]
    provenance: tuple[ProvenanceRecord, ...]


class EvidenceProduced(FrozenModel):
    outcome_type: Literal["evidence_produced"] = "evidence_produced"
    action: ValidatedAnalysisAction
    evidence: EvidenceBundle
    attempt_count: int = Field(ge=1)


class ActionRejected(FrozenModel):
    outcome_type: Literal["action_rejected"] = "action_rejected"
    action: NextAnalysisAction
    error_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    correction_allowed: bool


class ToolExecutionFailed(FrozenModel):
    outcome_type: Literal["tool_execution_failed"] = "tool_execution_failed"
    action: ValidatedAnalysisAction
    error_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    failure_kind: Literal["transient", "hard"]
    attempt_count: int = Field(ge=1)
    retry_exhausted: bool

    @model_validator(mode="after")
    def validate_retry_semantics(self):
        if self.failure_kind == "transient" and not self.retry_exhausted:
            raise ValueError("transient Tool failure must exhaust its retry budget")
        if self.failure_kind == "hard" and self.retry_exhausted:
            raise ValueError("hard Tool failure is not retryable")
        return self


ActionExecutionOutcome: TypeAlias = Annotated[
    EvidenceProduced | ActionRejected | ToolExecutionFailed,
    Field(discriminator="outcome_type"),
]


class AnalysisFailureRecord(FrozenModel):
    failure_type: Literal[
        "action_rejected",
        "skill_resource_rejected",
        "tool_execution_failed",
    ]
    action_id: str
    error_code: str
    retryable: bool
    attempt_count: int = Field(ge=0)


class AnalysisState(FrozenModel):
    cycle_count: int = Field(default=0, ge=0, le=2)
    replan_count: int = Field(default=0, ge=0, le=1)
    question_ids: tuple[str, ...] = ()
    supported_predicates: tuple[str, ...] = ()
    rejected_predicates: tuple[str, ...] = ()
    inconclusive_predicates: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class SequentialAnalysisState(FrozenModel):
    decision_count: int = Field(default=0, ge=0, le=9)
    tool_call_count: int = Field(default=0, ge=0, le=5)
    action_ids: tuple[str, ...] = ()
    question_ids: tuple[str, ...] = ()
    supported_predicates: tuple[str, ...] = ()
    rejected_predicates: tuple[str, ...] = ()
    inconclusive_predicates: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    unresolved_questions: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    loaded_skill_references: tuple[str, ...] = ()
    seen_request_hashes: tuple[str, ...] = ()
    hypotheses: tuple[HypothesisEvaluation, ...] = ()
    action_correction_count: int = Field(default=0, ge=0, le=2)
    tool_retry_count: int = Field(default=0, ge=0)
    failures: tuple[AnalysisFailureRecord, ...] = ()
    stop_reason_code: str | None = None


class InvestigationDecision(FrozenModel):
    plan: SmallAnalysisPlan
    rationale: str


class EvidenceReviewDecision(FrozenModel):
    evidence_sufficient: bool
    rationale: str
    replan: SmallAnalysisPlan | None = None
    unresolved_questions: tuple[str, ...] = ()


class NumericBinding(FrozenModel):
    binding_id: str = Field(
        min_length=1,
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Placeholder name used exactly as {binding_id} in text_template"
    )
    source_type: Literal["fact", "evidence"]
    source_ref: str
    value_key: str | None = Field(
        default=None,
        description="Exact numeric_values key for Evidence; always null for Fact",
    )


class PredicateBinding(FrozenModel):
    predicate: MvpPredicate
    predicate_evidence_ref: str = Field(
        min_length=1,
        description="Exact PredicateEvidence ID where this predicate is supported"
    )


class LegacyPredicateBinding(FrozenModel):
    """Schema v2 compatibility shape; new analyses never serialize this form."""

    predicate: MvpPredicate
    evidence_ref: str = Field(
        description="Legacy EvidenceItem ID containing the supported predicate"
    )


class DraftAnalysisClaim(FrozenModel):
    claim_id: str
    claim_type: Literal["descriptive", "derived", "synthesis"]
    text_template: str = Field(min_length=1)
    fact_refs: tuple[str, ...] = Field(
        default=(),
        description="Required for descriptive claims; exact ScalarFact IDs",
    )
    evidence_refs: tuple[str, ...] = Field(
        default=(),
        description="Required for derived claims; synthesis requires at least two distinct Evidence IDs",
    )
    tool_run_ids: tuple[str, ...] = Field(
        default=(),
        description="Tool Run IDs corresponding to every referenced Evidence",
    )
    predicate_bindings: tuple[PredicateBinding, ...] = ()
    numeric_bindings: tuple[NumericBinding, ...] = ()
    limitations: tuple[str, ...] = ()

    @field_validator("text_template")
    @classmethod
    def require_non_blank_template(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text_template must be non-blank")
        return value


class ScopeExpansionSuggestion(FrozenModel):
    data_scope: Literal["longitudinal", "cohort"]
    reason: str
    related_metric_codes: tuple[str, ...] = ()


class DraftAnalysisPackage(FrozenModel):
    summary: str
    claims: tuple[DraftAnalysisClaim, ...]
    scope_expansion_suggestions: tuple[ScopeExpansionSuggestion, ...] = ()
    overall_limitations: tuple[str, ...] = ()


class ValidatedNumericBinding(FrozenModel):
    binding_id: str
    value: float
    unit: str
    source_ref: str


class ValidatedAnalysisClaim(FrozenModel):
    claim_id: str
    claim_type: Literal["descriptive", "derived", "synthesis"]
    text_template: str
    fact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    tool_run_ids: tuple[str, ...]
    predicate_bindings: tuple[PredicateBinding, ...]
    numeric_bindings: tuple[ValidatedNumericBinding, ...]
    limitations: tuple[str, ...]


class ValidatedAnalysisPackage(FrozenModel):
    summary: str
    claims: tuple[ValidatedAnalysisClaim, ...]
    scope_expansion_suggestions: tuple[ScopeExpansionSuggestion, ...]
    overall_limitations: tuple[str, ...]


class AnalysisClaim(FrozenModel):
    claim_id: str
    claim_type: Literal["descriptive", "derived", "synthesis"]
    text: str
    fact_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    tool_run_ids: tuple[str, ...]
    predicate_bindings: tuple[PredicateBinding | LegacyPredicateBinding, ...]
    limitations: tuple[str, ...]
    citation_refs: tuple[str, ...] = ()


class AnalysisPackage(FrozenModel):
    analysis_schema_version: str
    analysis_run_id: str
    session_id: int
    package_id: str
    package_digest: str
    data_access_scope: DataAccessScope
    summary: str
    claims: tuple[AnalysisClaim, ...]
    scope_expansion_suggestions: tuple[ScopeExpansionSuggestion, ...]
    overall_limitations: tuple[str, ...]
    literature_evidence: tuple[LiteratureEvidence, ...] = ()
    recommendations: tuple[Recommendation, ...] = ()
    references: tuple[Citation, ...] = ()
    references_markdown: str = ""
    rag_audit: RAGAudit | None = None
    cycle_count: int
    replan_count: int
    model_name: str
    prompt_version: str
    prompt_content_digest: str | None = Field(
        default=None, min_length=64, max_length=64
    )

    @model_validator(mode="before")
    @classmethod
    def read_legacy_schema_version(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        data.setdefault("analysis_schema_version", "analysis-schema/1.0-legacy")
        return data


class LoopResult(FrozenModel):
    state: AnalysisState
    evidence: tuple[EvidenceBundle, ...]
    draft: DraftAnalysisPackage
    investigation_elapsed_ms: int = Field(default=0, ge=0)
    synthesis_elapsed_ms: int = Field(default=0, ge=0)


class SequentialLoopResult(FrozenModel):
    state: SequentialAnalysisState
    evidence: tuple[EvidenceBundle, ...]
    draft: DraftAnalysisPackage
    skill_version: str
    skill_content_digest: str = Field(min_length=64, max_length=64)
    investigation_elapsed_ms: int = Field(default=0, ge=0)
    synthesis_elapsed_ms: int = Field(default=0, ge=0)


class SequentialLoopCheckpoint(FrozenModel):
    checkpoint_schema_version: Literal[
        "sequential-checkpoint/1.1"
    ] = "sequential-checkpoint/1.1"
    phase: Literal[
        "skill_loaded",
        "state_updated",
        "action_accepted",
        "evidence_recorded",
        "ready_for_synthesis",
        "draft_generated",
        "claim_repair_pending",
    ]
    session_id: int = Field(gt=0)
    package_digest: str = Field(min_length=64, max_length=64)
    data_access_scope: DataAccessScope
    state: SequentialAnalysisState
    evidence: tuple[EvidenceBundle, ...] = ()
    pending_action: ValidatedAnalysisAction | None = None
    draft: DraftAnalysisPackage | None = None
    claim_validation_error_code: str | None = None
    claim_validation_error_message: str | None = None
    claim_repair_count: int = Field(default=0, ge=0, le=1)
    skill_version: str
    skill_content_digest: str = Field(min_length=64, max_length=64)
    observation_builder_version: str
    analysis_tool_registry_version: str
    analysis_method_registry_version: str
    kernel_version: str
    prompt_content_digest: str | None = Field(
        default=None, min_length=64, max_length=64
    )

    @model_validator(mode="after")
    def validate_pending_action_phase(self):
        has_pending_action = self.pending_action is not None
        if (self.phase == "action_accepted") != has_pending_action:
            raise ValueError(
                "pending_action is required only for action_accepted checkpoints"
            )
        requires_draft = self.phase in {
            "draft_generated",
            "claim_repair_pending",
        }
        if requires_draft != (self.draft is not None):
            raise ValueError(
                "draft is required only for draft and claim-repair checkpoints"
            )
        has_validation_error = (
            self.claim_validation_error_code is not None
            or self.claim_validation_error_message is not None
        )
        if self.phase == "claim_repair_pending":
            if (
                self.claim_validation_error_code is None
                or self.claim_validation_error_message is None
                or self.claim_repair_count != 0
            ):
                raise ValueError(
                    "claim_repair_pending requires one validation error before repair"
                )
        elif has_validation_error:
            raise ValueError(
                "claim validation errors belong only to claim_repair_pending"
            )
        return self


class ResumableSequentialAnalysis(FrozenModel):
    analysis_run_id: str
    checkpoint: SequentialLoopCheckpoint


class AnalysisRunMetrics(FrozenModel):
    model_name: str
    prompt_version: str
    prompt_content_digest: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    observation_builder_version: str
    analysis_tool_registry_version: str
    analysis_method_registry_version: str
    kernel_version: str
    package_digest: str
    cycle_count: int = Field(ge=0)
    replan_count: int = Field(ge=0)
    agent_level_node_count: int = Field(ge=0)
    tool_run_count: int = Field(ge=0)
    duplicate_request_count: int = Field(ge=0)
    observation_size: int = Field(ge=0)
    estimated_tokens: int = Field(ge=0)
    elapsed_ms: int = Field(ge=0)
    decision_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    skill_reference_load_count: int = Field(default=0, ge=0)
    investigation_elapsed_ms: int = Field(default=0, ge=0)
    synthesis_elapsed_ms: int = Field(default=0, ge=0)
    claim_repair_count: int = Field(default=0, ge=0, le=1)
    stop_reason_code: str | None = None
    timeout_stage: str | None = None
    resumed_from_checkpoint: bool = False

    @model_validator(mode="before")
    @classmethod
    def read_legacy_registry_version(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy = data.pop("operator_registry_version", None)
        if legacy is not None:
            data.setdefault("analysis_tool_registry_version", "legacy-tool-registry/1.0")
            data.setdefault("analysis_method_registry_version", legacy)
            data.setdefault("kernel_version", "analysis-kernel/1.0")
        return data
