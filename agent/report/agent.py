"""PydanticAI implementation of the single logical Report Agent."""

from __future__ import annotations

import asyncio
import json

import httpx
from pydantic_ai import Agent

from agent.common.model_provider import build_chat_model, default_model_settings
from reporting.models import (
    AnalysisDecision,
    AgentObservation,
    AnalysisState,
    DraftAnalysisPackage,
    EvidenceBundle,
    EvidenceReviewDecision,
    InvestigationDecision,
    SequentialAnalysisState,
)
from reporting.observation import serialize_observation

from .prompts import (
    DECISION_STAGE_TEMPLATE,
    PLAN_STAGE_TEMPLATE,
    PROMPT_VERSION,
    REPAIR_STAGE_TEMPLATE,
    REVIEW_STAGE_TEMPLATE,
    SEQUENTIAL_PROMPT_VERSION,
    SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE,
    SYNTHESIS_STAGE_TEMPLATE,
    load_sequential_system_prompt,
    load_system_prompt,
    prompt_content_digest,
    readable_prompt_version,
)
from .skill_loader import ReportAnalysisSkillContext


class ReportAgentCallTimeout(TimeoutError):
    def __init__(self, stage: str):
        super().__init__(f"Report Agent model call timed out during {stage}")
        self.stage = stage


class ReportAgent:
    model_name = "deepseek-v4-flash"
    prompt_version = PROMPT_VERSION
    sequential_prompt_version = SEQUENTIAL_PROMPT_VERSION

    def __init__(self):
        self._system_prompt = load_system_prompt()
        self._sequential_system_prompt = load_sequential_system_prompt()
        self.prompt_content_digest = prompt_content_digest(
            self._system_prompt,
            PLAN_STAGE_TEMPLATE,
            REVIEW_STAGE_TEMPLATE,
            SYNTHESIS_STAGE_TEMPLATE,
            REPAIR_STAGE_TEMPLATE,
        )
        self.sequential_prompt_content_digest = prompt_content_digest(
            self._sequential_system_prompt,
            self._system_prompt,
            DECISION_STAGE_TEMPLATE,
            SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE,
            REPAIR_STAGE_TEMPLATE,
        )
        self.prompt_version = readable_prompt_version(
            PROMPT_VERSION, self.prompt_content_digest
        )
        self.sequential_prompt_version = readable_prompt_version(
            SEQUENTIAL_PROMPT_VERSION,
            self.sequential_prompt_content_digest,
        )

    def decide(
        self,
        observation: AgentObservation,
        state: SequentialAnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        skill_context: ReportAnalysisSkillContext,
        *,
        timeout_s: float | None = None,
    ) -> AnalysisDecision:
        prompt = (
            f"{DECISION_STAGE_TEMPLATE}\n"
            f"Report Analysis Skill:\n{skill_context.instructions}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(
            AnalysisDecision,
            prompt,
            instructions=self._sequential_system_prompt,
            timeout_s=timeout_s,
            stage="decision",
        )

    def propose_plan(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        *,
        timeout_s: float | None = None,
    ) -> InvestigationDecision:
        prompt = (
            f"{PLAN_STAGE_TEMPLATE}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}"
        )
        return self._run(
            InvestigationDecision,
            prompt,
            timeout_s=timeout_s,
            stage="legacy_plan",
        )

    def review_evidence(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        *,
        timeout_s: float | None = None,
    ) -> EvidenceReviewDecision:
        prompt = (
            f"{REVIEW_STAGE_TEMPLATE}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(
            EvidenceReviewDecision,
            prompt,
            timeout_s=timeout_s,
            stage="legacy_review",
        )

    def synthesize(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        *,
        timeout_s: float | None = None,
    ) -> DraftAnalysisPackage:
        prompt = (
            f"{SYNTHESIS_STAGE_TEMPLATE}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(
            DraftAnalysisPackage,
            prompt,
            timeout_s=timeout_s,
            stage="synthesis",
        )

    def synthesize_sequential(
        self,
        observation: AgentObservation,
        state: SequentialAnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        skill_context: ReportAnalysisSkillContext,
        *,
        timeout_s: float | None = None,
    ) -> DraftAnalysisPackage:
        prompt = (
            f"{SEQUENTIAL_SYNTHESIS_STAGE_TEMPLATE}\n"
            f"Report Analysis Skill:\n{skill_context.instructions}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}"
        )
        return self._run(
            DraftAnalysisPackage,
            prompt,
            timeout_s=timeout_s,
            stage="synthesis",
        )

    def repair_synthesis(
        self,
        observation: AgentObservation,
        state: AnalysisState,
        evidence: tuple[EvidenceBundle, ...],
        draft: DraftAnalysisPackage,
        error_code: str,
        error_message: str,
        *,
        timeout_s: float | None = None,
    ) -> DraftAnalysisPackage:
        prompt = (
            f"{REPAIR_STAGE_TEMPLATE}\n"
            f"Validation error: {error_code}: {error_message}\n"
            f"Observation:\n{serialize_observation(observation)}\n"
            f"State:\n{self._json(state)}\n"
            f"Evidence:\n{self._json(evidence)}\n"
            f"Rejected Draft:\n{self._json(draft)}"
        )
        return self._run(
            DraftAnalysisPackage,
            prompt,
            timeout_s=timeout_s,
            stage="claim_repair",
        )

    def _run(
        self,
        output_type,
        prompt,
        *,
        instructions=None,
        timeout_s: float | None = None,
        stage: str,
    ):
        async def flow():
            client = httpx.AsyncClient()
            try:
                model_settings = default_model_settings()
                if timeout_s is not None:
                    model_settings = {**model_settings, "timeout": timeout_s}
                runtime_agent = Agent(
                    model=build_chat_model(client),
                    output_type=output_type,
                    instructions=instructions or self._system_prompt,
                    retries=1,
                    model_settings=model_settings,
                )
                if timeout_s is None:
                    result = await runtime_agent.run(prompt)
                else:
                    async with asyncio.timeout(timeout_s):
                        result = await runtime_agent.run(prompt)
                return result.output
            finally:
                await client.aclose()

        try:
            return asyncio.run(flow())
        except TimeoutError as exc:
            raise ReportAgentCallTimeout(stage) from exc

    def _json(self, value) -> str:
        if isinstance(value, tuple):
            value = [item.model_dump(mode="json") for item in value]
        else:
            value = value.model_dump(mode="json")
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
