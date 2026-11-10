"""Compare authoritative report means under an identical saved protocol."""

import hashlib
import json
from html import escape

from .metric_catalog import METRIC_CATALOG
from .text import format_numeric_value


def protocol_description(session):
    snapshot = dict(session.report.report_config_snapshot)
    for key in ("beam_quality", "raw_buffer", "payload_mirror_guard"):
        snapshot.pop(key, None)
    return {"config": session.config.to_dict(), "measurement": snapshot}


def protocol_digest(protocol):
    encoded = json.dumps(protocol, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def compare_packages(current, previous, protocol):
    previous_facts = {fact.source_ref: fact for fact in previous.scalar_facts}
    rows = []
    for fact in current.scalar_facts:
        prior = previous_facts.get(fact.source_ref)
        if (
            fact.statistic != "mean" or fact.state != "present"
            or prior is None or prior.state != "present" or prior.statistic != fact.statistic
            or prior.metric_code != fact.metric_code or prior.unit != fact.unit
            or fact.sample_count == 0 or prior.sample_count == 0
        ):
            continue
        if any(
            flag.invalidates_report or fact.metric_code in flag.invalidates_metric_codes
            for package in (current, previous) for flag in package.quality_flags
        ):
            continue
        label = METRIC_CATALOG[fact.metric_code].label
        if fact.source_ref.startswith("recognized_measurements:"):
            label += "（识别足迹）"
        rows.append({
            "metric_code": fact.metric_code, "label": label, "unit": fact.unit,
            "current": fact.value, "previous": prior.value,
            "difference": fact.value - prior.value,
            "current_count": fact.sample_count, "previous_count": prior.sample_count,
            "current_fact_ref": fact.fact_id, "previous_fact_ref": prior.fact_id,
            "source_ref": fact.source_ref,
        })
    return {
        "status": "matched" if rows else "no_common_metrics",
        "current_session_id": current.metadata.session_id,
        "previous_session_id": previous.metadata.session_id,
        "current_started_at": current.context.started_at,
        "previous_started_at": previous.context.started_at,
        "current_package_digest": current.metadata.package_digest,
        "previous_package_digest": previous.metadata.package_digest,
        "protocol_digest": protocol,
        "metrics": rows,
    }


def comparison_html(comparison):
    if not comparison or comparison.get("status") == "guest":
        return ""
    title = "<h3>完整测试与上次同协议记录对比</h3>"
    if comparison["status"] == "no_previous":
        return title + "<p>暂无此前的同协议测试记录。</p>"
    if comparison["status"] == "no_common_metrics":
        return title + "<p>两次记录暂无共同的有效均值指标。</p>"
    content = title + "<p>上次测试　" + escape(comparison["previous_started_at"]) + "</p>"
    content += '<table width="100%" cellpadding="5"><tr><th>指标</th><th>上次均值</th><th>本次均值</th><th>本次减上次</th></tr>'
    for row in comparison["metrics"]:
        values = [escape(row["label"])]
        values.extend(escape(format_numeric_value(row[key], row["unit"]))
                      for key in ("previous", "current", "difference"))
        content += "<tr>" + "".join("<td>" + value + "</td>" for value in values) + "</tr>"
    return content + "</table>"
