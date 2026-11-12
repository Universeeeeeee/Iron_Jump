"""User-authored finding notes and versioned retest targets."""

import json
import math
from datetime import datetime
from html import escape
from typing import Literal

from pydantic import Field, field_validator, model_validator

from .comparison import protocol_description
from .metric_catalog import METRIC_CATALOG
from .models import DataAccessScope, FrozenModel


class AnnotationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class AnnotationReadRequest(FrozenModel):
    session_id: int = Field(gt=0)
    data_access_scope: DataAccessScope
    analysis_run_id: str | None = None


class AnnotationSaveRequest(AnnotationReadRequest):
    analysis_run_id: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    note: str = Field(default="", max_length=2000)
    fact_id: str | None = None
    target_value: float | None = Field(default=None, allow_inf_nan=False)
    target_direction: Literal["at_most", "at_least"] = "at_most"
    status: Literal["active", "completed", "archived"] = "active"

    @field_validator("note")
    @classmethod
    def trim_note(cls, value):
        return value.strip()

    @model_validator(mode="after")
    def validate_target(self):
        if (self.fact_id is None) != (self.target_value is None):
            raise ValueError("Target metric and value must be provided together")
        if not self.note and self.fact_id is None and not (self.expected_revision > 0 and self.status in {"completed", "archived"}):
            raise ValueError("A note or target is required")
        return self


def _analysis(repository, session_id, scope, run_id):
    package = repository.get_package(session_id)
    saved = repository.get_validated_analysis(
        run_id, session_id, scope, package.metadata.package_digest,
        include_current_scope=scope.longitudinal,
    )
    if saved is None:
        raise AnnotationError("stale_annotation_source", "原分析已失效，请重新分析后填写备注。")
    return package, saved


def _claim_facts(package, analysis, claim):
    items = {item["evidence_id"]: item for bundle in analysis.get("evidence", []) for item in bundle["items"]}
    metrics = {package.resolve_ref(ref).metric_code for ref in claim.get("fact_refs", [])}
    metrics.update(metric for ref in claim.get("evidence_refs", [])
                   for predicate in items.get(ref, {}).get("predicates", []) for metric in predicate["metric_codes"])
    return [fact for fact in package.scalar_facts
            if fact.metric_code in metrics and fact.statistic == "mean" and fact.state == "present"
            and fact.sample_count != 0
            and not any(flag.invalidates_report or fact.metric_code in flag.invalidates_metric_codes
                        for flag in package.quality_flags)]


def save_annotation(repository, request):
    with repository._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        latest = conn.execute(
            """SELECT a.revision,a.payload_json FROM report_annotations a JOIN report_analyses r
               ON r.analysis_run_id=a.analysis_run_id WHERE a.analysis_run_id=? AND a.claim_id=?
               AND a.session_id=? AND r.data_access_scope_json IN (?, ?) ORDER BY a.revision DESC LIMIT 1""",
            (request.analysis_run_id, request.claim_id, request.session_id,
             repository._scope_json(request.data_access_scope), repository._scope_json(DataAccessScope())),
        ).fetchone()
        revision = latest["revision"] if latest else 0
        if revision != request.expected_revision:
            raise AnnotationError("annotation_conflict", "备注已被更新，请重新打开后编辑。")
        if latest and request.status in {"archived", "completed"}:
            payload = json.loads(latest["payload_json"])
            payload.update(status=request.status, revision=revision + 1,
                           updated_at=datetime.now().isoformat(timespec="seconds"))
            if "note" in request.model_fields_set:
                payload["note"] = request.note
            conn.execute(
                "INSERT INTO report_annotations(session_id,analysis_run_id,claim_id,revision,payload_json) VALUES(?,?,?,?,?)",
                (request.session_id, request.analysis_run_id, request.claim_id, revision + 1,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
            return payload
        package, analysis = _analysis(repository, request.session_id, request.data_access_scope, request.analysis_run_id)
        protocol = protocol_description(repository._get_session(request.session_id))
        old_target = json.loads(latest["payload_json"])["target"] if latest else None
        if old_target and old_target["protocol"] != protocol:
            raise AnnotationError("stale_annotation_source", "原目标的测试协议已更新，请重新分析并设定目标。")
        claim = next((item for item in analysis["claims"] if item["claim_id"] == request.claim_id), None)
        if claim is None:
            raise AnnotationError("unknown_claim", "所选发现已不存在。")
        target = None
        if request.fact_id:
            if package.context.is_temporary or package.context.subject_id is None:
                raise AnnotationError("guest_target_unavailable", "复测目标需要关联正式用户。")
            fact = next((item for item in _claim_facts(package, analysis, claim) if item.fact_id == request.fact_id), None)
            if fact is None:
                raise AnnotationError("invalid_target_metric", "请选择该发现关联的有效指标均值。")
            target = {
                "fact_id": fact.fact_id, "source_ref": fact.source_ref, "metric_code": fact.metric_code,
                "unit": fact.unit, "baseline_value": fact.value, "target_value": request.target_value,
                "direction": request.target_direction,
                "protocol": protocol,
            }
        payload = {
            "session_id": request.session_id, "analysis_run_id": request.analysis_run_id,
            "claim_id": request.claim_id, "claim_text": claim["text"],
            "package_digest": package.metadata.package_digest,
            "subject_id": package.context.subject_id, "team_id": package.context.team_id,
            "started_at": package.context.started_at, "note": request.note,
            "target": target, "status": request.status, "revision": revision + 1,
            "updated_at": datetime.now().isoformat(timespec="seconds"), "author_type": "user",
            "recommendation_refs": [item["recommendation_id"] for item in analysis.get("recommendations", [])
                                    if request.claim_id in item.get("claim_refs", [])],
        }
        conn.execute(
            """INSERT INTO report_annotations(session_id,analysis_run_id,claim_id,revision,payload_json)
               VALUES(?,?,?,?,?)""",
            (request.session_id, request.analysis_run_id, request.claim_id, revision + 1,
             json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
    return payload


def read_annotations(repository, request):
    package = repository.get_package(request.session_id)
    claims = []
    if request.analysis_run_id:
        package, analysis = _analysis(repository, request.session_id, request.data_access_scope, request.analysis_run_id)
        for claim in analysis["claims"]:
            facts = _claim_facts(package, analysis, claim)
            claims.append({"claim_id": claim["claim_id"], "analysis_run_id": request.analysis_run_id,
                           "stale": False, "text": claim["text"],
                           "facts": [{"fact_id": fact.fact_id, "label": METRIC_CATALOG[fact.metric_code].label,
                                      "source_ref": fact.source_ref, "unit": fact.unit, "value": fact.value}
                                     for fact in facts]})
    with repository._connect() as conn:
        own_rows = conn.execute(
            """SELECT a.payload_json FROM report_annotations a JOIN report_analyses r
               ON r.analysis_run_id=a.analysis_run_id WHERE a.session_id=?
               AND r.data_access_scope_json IN (?, ?) AND a.id IN
               (SELECT MAX(id) FROM report_annotations GROUP BY analysis_run_id,claim_id) ORDER BY a.id DESC""",
            (request.session_id, repository._scope_json(request.data_access_scope), repository._scope_json(DataAccessScope())),
        ).fetchall()
        earlier_rows = []
        if request.data_access_scope.longitudinal and package.context.subject_id and not package.context.is_temporary:
            earlier_rows = conn.execute(
                """SELECT a.payload_json FROM report_annotations a JOIN test_sessions s ON s.id=a.session_id
                   WHERE s.subject_id=? AND s.team_id IS ? AND s.test_type=? AND s.is_temporary=0
                     AND (s.started_at < ? OR (s.started_at=? AND s.id < ?))
                     AND a.id IN (SELECT MAX(id) FROM report_annotations GROUP BY analysis_run_id,claim_id)
                   ORDER BY a.id DESC""",
                (package.context.subject_id, package.context.team_id, package.context.test_type,
                 package.context.started_at, package.context.started_at, request.session_id),
            ).fetchall()
    notes = [json.loads(row["payload_json"]) for row in own_rows]
    current_protocol = protocol_description(repository._get_session(request.session_id))
    for note in notes:
        note["stale"] = repository.get_validated_analysis(
            note["analysis_run_id"], request.session_id, request.data_access_scope,
            package.metadata.package_digest, include_current_scope=request.data_access_scope.longitudinal,
        ) is None or bool(note["target"] and note["target"]["protocol"] != current_protocol)
        if not any(claim["analysis_run_id"] == note["analysis_run_id"] and claim["claim_id"] == note["claim_id"] for claim in claims):
            facts = []
            if not note["stale"]:
                _, saved = _analysis(repository, request.session_id, request.data_access_scope, note["analysis_run_id"])
                claim = next(item for item in saved["claims"] if item["claim_id"] == note["claim_id"])
                facts = [{"fact_id": f.fact_id, "label": METRIC_CATALOG[f.metric_code].label,
                          "source_ref": f.source_ref, "unit": f.unit, "value": f.value}
                         for f in _claim_facts(package, saved, claim)]
            claims.append({"claim_id": note["claim_id"], "analysis_run_id": note["analysis_run_id"],
                           "text": note["claim_text"], "facts": facts, "stale": note["stale"]})
    progress = []
    for row in earlier_rows:
        annotation = json.loads(row["payload_json"])
        target = annotation["target"]
        if target is None or annotation["status"] != "active":
            continue
        result = {"annotation": annotation, "status": "protocol_mismatch"}
        try:
            baseline = repository.get_package(annotation["session_id"])
            valid_baseline = target["protocol"] == protocol_description(repository._get_session(annotation["session_id"])) and repository.get_validated_analysis(
                annotation["analysis_run_id"], annotation["session_id"], request.data_access_scope,
                baseline.metadata.package_digest, include_current_scope=True,
            ) is not None
        except (KeyError, ValueError):
            valid_baseline = False
        if not valid_baseline:
            result["status"] = "stale_baseline"
        elif target["protocol"] == current_protocol:
            fact = next((f for f in package.scalar_facts if f.source_ref == target["source_ref"]
                         and f.metric_code == target["metric_code"] and f.unit == target["unit"]
                         and f.state == "present" and f.statistic == "mean" and f.sample_count != 0), None)
            result["status"] = "metric_unavailable"
            if fact and not any(flag.invalidates_report or fact.metric_code in flag.invalidates_metric_codes
                                for flag in package.quality_flags):
                reached = fact.value <= target["target_value"] if target["direction"] == "at_most" else fact.value >= target["target_value"]
                reached = reached or math.isclose(fact.value, target["target_value"], rel_tol=1e-12, abs_tol=1e-12)
                result.update(status="reached" if reached else "pending", value=fact.value,
                              difference=fact.value - target["baseline_value"], fact_id=fact.fact_id,
                              package_digest=package.metadata.package_digest)
        progress.append(result)
    return {"analysis_run_id": request.analysis_run_id, "annotations": notes,
            "claims": claims, "progress": progress,
            "can_set_target": bool(package.context.subject_id and not package.context.is_temporary)}


def annotations_html(data):
    if not data:
        return ""
    parts = []
    for annotation in data.get("annotations", []):
        if annotation["status"] == "archived":
            continue
        parts.append("<p><b>用户备注 · " + escape(annotation["updated_at"]) + "</b><br>" + escape(annotation["claim_text"]))
        if annotation["note"]:
            parts.append("<br>" + escape(annotation["note"]).replace("\n", "<br>"))
        if annotation.get("stale"):
            parts.append("<br>该备注关联的报告已更新。")
        if annotation["target"]:
            parts.append("<br>" + _target_text(annotation["target"]))
        if annotation["status"] == "completed":
            parts.append("<br>用户已标记完成。")
        parts.append("</p>")
    labels = {"reached": "本次达到目标值", "pending": "本次尚未达到目标值",
              "protocol_mismatch": "测试协议不同，待同协议复测", "stale_baseline": "基线报告已更新，请重新设定目标",
              "metric_unavailable": "本次缺少该指标的有效均值"}
    for result in data.get("progress", []):
        annotation = result["annotation"]
        target = annotation["target"]
        parts.append("<p><b>复测目标 · 基线 " + escape(annotation["started_at"]) + "</b><br>"
                     + escape(annotation["claim_text"]) + "<br>" + _target_text(target))
        if annotation["note"]:
            parts.append("<br>用户备注　" + escape(annotation["note"]).replace("\n", "<br>"))
        if "value" in result:
            parts.append("<br>本次 " + _target_value(result["value"], target["unit"])
                         + "，较基线 " + _target_value(result["difference"], target["unit"]))
        parts.append("<br>" + labels[result["status"]] + "。</p>")
    return "".join(parts)


def _target_text(target):
    label = METRIC_CATALOG[target["metric_code"]].label
    direction = "不高于" if target["direction"] == "at_most" else "不低于"
    return escape(f"完整测试{label}均值目标{direction} "
                  + _target_value(target["target_value"], target["unit"])
                  + "，基线 " + _target_value(target["baseline_value"], target["unit"]) + "。")


def _target_value(value, unit):
    return f"{value:.12g} {unit}"
