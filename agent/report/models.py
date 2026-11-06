"""Report Agent schemas; deterministic plan contracts live in reporting."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from reporting.models import (
    ActionRejected,
    AnalysisNode,
    AnalysisQuestion,
    DraftAnalysisPackage,
    EvidenceReviewDecision,
    EvidenceProduced,
    HypothesisTarget,
    InvestigationDecision,
    HypothesisEvaluation,
    LoadSkillResource,
    NextAnalysisAction,
    AnalysisState,
    AnalysisDecision,
    DataAccessScope,
    SmallAnalysisPlan,
    SequentialAnalysisState,
    StopAnalysis,
    ToolExecutionFailed,
)


class ReportAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: int = Field(gt=0)
    data_access_scope: DataAccessScope


class ReportFollowupRequest(ReportAnalysisRequest):
    question: str = Field(min_length=1, max_length=2000)
    parent_analysis_run_id: str | None = Field(default=None, min_length=1)
    selected_claim_id: str | None = Field(default=None, min_length=1)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Question cannot be blank")
        return value

    @model_validator(mode="after")
    def validate_parent(self):
        if self.selected_claim_id and not self.parent_analysis_run_id:
            raise ValueError("Selected claim requires its analysis run")
        return self


__all__ = [
    "ActionRejected",
    "AnalysisNode",
    "AnalysisQuestion",
    "AnalysisState",
    "AnalysisDecision",
    "DraftAnalysisPackage",
    "EvidenceReviewDecision",
    "EvidenceProduced",
    "HypothesisTarget",
    "InvestigationDecision",
    "HypothesisEvaluation",
    "LoadSkillResource",
    "NextAnalysisAction",
    "ReportAnalysisRequest",
    "ReportFollowupRequest",
    "SmallAnalysisPlan",
    "SequentialAnalysisState",
    "StopAnalysis",
    "ToolExecutionFailed",
]
