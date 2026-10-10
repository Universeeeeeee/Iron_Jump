"""Read-only progressive loader for the embedded Report Analysis Skill."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from reporting.models import TestType


REPORT_ANALYSIS_SKILL_VERSION = "report-analysis-skill/0.6"
_DEFAULT_SKILL_PATH = Path(__file__).resolve().parent / "skills" / "report-analysis"
_DOMAIN_REFERENCE_BY_TEST_TYPE: dict[TestType, str] = {
    "Jump Test": "references/jump.md",
    "Treadmill Gait Test": "references/gait.md",
    "Treadmill Running Test": "references/running.md",
    "Sprint and Gait Test": "references/overground-walk.md",
    "Overground Running Test": "references/overground-run.md",
}
_ON_DEMAND_REFERENCES = frozenset(("references/evidence-guidelines.md",))


class SkillLoadError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class LoadedSkillResource:
    resource_id: str
    content: str
    content_digest: str


@dataclass(frozen=True)
class ReportAnalysisSkillContext:
    skill_name: str
    skill_version: str
    resources: tuple[LoadedSkillResource, ...]

    @property
    def loaded_reference_ids(self) -> tuple[str, ...]:
        return tuple(
            resource.resource_id
            for resource in self.resources
            if resource.resource_id.startswith("references/")
        )

    @property
    def instructions(self) -> str:
        return "\n\n".join(
            f"# Skill Resource: {resource.resource_id}\n\n{resource.content}"
            for resource in self.resources
        )

    @property
    def content_digest(self) -> str:
        encoded = "\n".join(
            f"{resource.resource_id}:{resource.content_digest}"
            for resource in self.resources
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ReportAnalysisSkillLoader:
    def __init__(self, skill_path: Path | None = None):
        self._skill_path = (skill_path or _DEFAULT_SKILL_PATH).resolve()

    def load_initial(self, test_type: TestType) -> ReportAnalysisSkillContext:
        try:
            domain_reference = _DOMAIN_REFERENCE_BY_TEST_TYPE[test_type]
        except KeyError as exc:
            raise SkillLoadError(
                "unsupported_skill_domain",
                f"no Report Analysis Skill domain for {test_type}",
            ) from exc
        return ReportAnalysisSkillContext(
            skill_name="report-analysis",
            skill_version=REPORT_ANALYSIS_SKILL_VERSION,
            resources=(
                self._read_resource("SKILL.md"),
                self._read_resource(domain_reference),
            ),
        )

    def load_reference(
        self,
        context: ReportAnalysisSkillContext,
        reference_id: str,
    ) -> ReportAnalysisSkillContext:
        if reference_id not in _ON_DEMAND_REFERENCES:
            raise SkillLoadError(
                "unknown_skill_reference",
                f"Skill reference is not available: {reference_id}",
            )
        if reference_id in context.loaded_reference_ids:
            raise SkillLoadError(
                "duplicate_skill_reference",
                f"Skill reference is already loaded: {reference_id}",
            )
        return ReportAnalysisSkillContext(
            skill_name=context.skill_name,
            skill_version=context.skill_version,
            resources=(*context.resources, self._read_resource(reference_id)),
        )

    def available_on_demand_references(self) -> tuple[str, ...]:
        return tuple(sorted(_ON_DEMAND_REFERENCES))

    def _read_resource(self, resource_id: str) -> LoadedSkillResource:
        path = (self._skill_path / resource_id).resolve()
        if self._skill_path not in path.parents:
            raise SkillLoadError(
                "skill_path_escape",
                f"Skill resource escapes its root: {resource_id}",
            )
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise SkillLoadError(
                "skill_resource_unavailable",
                f"cannot read Skill resource: {resource_id}",
            ) from exc
        if not content:
            raise SkillLoadError(
                "empty_skill_resource",
                f"Skill resource is empty: {resource_id}",
            )
        return LoadedSkillResource(
            resource_id=resource_id,
            content=content,
            content_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )


__all__ = [
    "LoadedSkillResource",
    "REPORT_ANALYSIS_SKILL_VERSION",
    "ReportAnalysisSkillContext",
    "ReportAnalysisSkillLoader",
    "SkillLoadError",
]
