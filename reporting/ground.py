"""Ground snapshot adapters: SI distances, independent metrics, no inferred feet."""
from copy import deepcopy

from config.test_report import GaitTestReport
from .builders import _stable_id, _metric_value
from .metric_catalog import METRIC_CATALOG
from .models import GroundPayload, MetricValue, QualityFlag, RecordSet, RecordStatus, SemanticRecord


_WALK_METRICS = {
    "contacts": {"contact_time_s": "contact_time_s"},
    "steps": {"step_length_m": "length_m", "step_time_s": "time_s", "speed_m_s": "speed_m_s"},
    "cycles": {"gait_cycle_s": "duration_s", "single_support_s": "single_support_s", "total_double_support_s": "double_support_s"},
}
_RUN_METRICS = {
    "contacts": {"contact_time_s": "contact_s"},
    "steps": {**_WALK_METRICS["steps"], "flight_time_s": "flight_s"},
    "cycles": {**_WALK_METRICS["cycles"], "stride_length_m": "length_m", "stance_phase_s": "contact_s",
               "swing_phase_s": "swing_s", "total_flight_time_s": "flight_s"},
}


def _running_metric(code, source):
    if source is None:
        return _metric_value(code, None)
    if source["valid"]:
        return _metric_value(code, source["value"])
    return MetricValue(metric_code=code, state="invalid", reason=source.get("missing_reason") or "not_observed")


def build_ground_data(builder, package_id, report):
    walking = isinstance(report, GaitTestReport)
    summary = report.walking_summary if walking else report.running_summary
    source_name = "walking_summary" if walking else "running_summary"
    mappings = _WALK_METRICS if walking else _RUN_METRICS
    contacts = {row["id"]: row for row in summary["contacts"]}
    if len(contacts) != len(summary["contacts"]):
        raise ValueError("duplicate ground contact ids")
    anchored = report.report_config_snapshot.get("starting_foot") in {"Left", "Right"}
    flags, record_sets, sources = [], [], {}

    for kind, record_type in (("contacts", "ground_contact"), ("steps", "ground_step"), ("cycles", "ground_cycle")):
        set_id = _stable_id(package_id, "record_set", record_type)
        records = []
        for ordinal, row in enumerate(summary[kind]):
            record_id = _stable_id(set_id, "record", ordinal)
            sources[record_id] = {"source_ref": f"{source_name}:{kind}:{ordinal}", "row": deepcopy(row)}
            target = contacts.get(row.get("to_id"), {})
            side = row.get("side", target.get("side", "unknown"))
            side = side if anchored and side in {"left", "right"} else "unknown"
            exclusion = None
            if walking:
                timestamp = row.get("start", row.get("start_s", target.get("start")))
                raw = dict(row)
                if kind == "contacts":
                    complete = (row.get("confirmed") and row.get("touch_known", bool(row.get("label")))
                                and row.get("end") is not None)
                    exclusion = row.get("exclusion") or (None if complete else "incomplete_contact")
                    if complete and exclusion == 'pending_touch_order':
                        exclusion = None
                    raw["contact_time_s"] = row["end"] - row["start"] if complete else None
                    if not exclusion and any(row["start"] < stop["end_s"] and row["end"] > stop["start_s"] for stop in summary["stops"]):
                        exclusion = "stop_interval"
                values = {code: _metric_value(code, raw.get(field)) for code, field in mappings[kind].items()}
            else:
                touch = row.get("touch_s") if kind == "contacts" else target.get("touch_s")
                if kind == "cycles":
                    touch = contacts.get(row.get("from_id"), {}).get("touch_s")
                timestamp = touch["value"] if touch and touch["valid"] else None
                values = {code: _running_metric(code, row.get(field)) for code, field in mappings[kind].items()}
            has_values = any(value.state == "present" for value in values.values())
            if not has_values and exclusion is None:
                exclusion = "no_valid_metrics"
            reasons = tuple(dict.fromkeys([exclusion] if exclusion else []))
            if walking and kind == 'contacts' and row.get('exclusion') == 'pending_touch_order':
                reasons += ('pending_touch_order',)
            reasons += tuple(dict.fromkeys(value.reason for value in values.values() if value.reason and value.reason not in reasons))
            row_flags = builder._row_quality_flags(package_id, record_id, reasons)
            flags.extend(row_flags)
            records.append(SemanticRecord(
                record_id=record_id, ordinal=ordinal, source_index=row.get("id", ordinal),
                timestamp_s=timestamp, side=side,
                status=RecordStatus(validity="valid" if has_values and (not walking or exclusion in {None, "stop_interval"}) else "invalid",
                                    inclusion="excluded" if exclusion else "included", exclusion_reason=exclusion),
                quality_flag_ids=tuple(flag.quality_flag_id for flag in row_flags), values=values,
            ))
        record_sets.append(RecordSet(record_set_id=set_id, record_type=record_type,
                                    metric_codes=tuple(mappings[kind]), records=tuple(records)))

    facts = [builder._fact(package_id, code, "count", getattr(report, code), "count", 1)
             for code in ("touch_count", "lift_count")]
    def add_fact(code, value, count, source, statistic="mean"):
        facts.append(builder._fact(package_id, code, statistic, value, METRIC_CATALOG[code].unit,
                                   count, source_name=source))
    add_fact("duration_s", summary.get("duration_s"), 1 if summary.get("duration_s") is not None else 0, source_name, "value")
    if walking:
        contact_count = sum(r.status.inclusion == "included" and r.status.validity == "valid" for r in record_sets[0].records)
        for code, key, count in (
            ("step_length_m", "mean_step_m", summary.get("valid_step_lengths", summary["valid_steps"])),
            ("stride_length_m", "mean_stride_m", len(summary["stride_lengths_m"])),
            ("contact_time_s", "mean_contact_s", summary.get("valid_contact_durations", contact_count)),
            ("speed_m_s", "walking_speed_m_s", summary.get("valid_step_lengths", summary["valid_steps"])),
            ("cadence_steps_per_min", "cadence_per_min", summary["valid_steps"]),
            ("single_support_s", "single_support_s", summary.get("valid_support_cycles", summary["valid_cycles"])),
            ("total_double_support_s", "double_support_s", summary.get("valid_support_cycles", summary["valid_cycles"])),
        ):
            add_fact(code, summary.get(key), count, source_name + ":" + key)
        add_fact("passage_speed_m_s", summary.get("passage_speed_m_s"), contact_count, source_name, "value")
    else:
        for group, stats, mapping in (
            ("step_statistics", summary["step_statistics"], _RUN_METRICS["steps"]),
            ("groups:all", summary["groups"]["all"], _RUN_METRICS["cycles"]),
        ):
            for code, field in mapping.items():
                metric = stats[field]
                add_fact(code, metric["mean"], metric["count"], source_name + ":" + group)
        # This is the producer's distance/time aggregate, not an average of step speeds.
        speed_count = summary.get('valid_step_speeds', sum(s['speed_m_s']['valid'] for s in summary['steps']))
        add_fact("speed_m_s", summary.get("running_speed_m_s"), speed_count, source_name)

    for kind in ("issues", "stops"):
        for ordinal, item in enumerate(summary[kind]):
            flags.append(QualityFlag(quality_flag_id=_stable_id(package_id, kind, ordinal),
                                     code=item.get("code", "stop_interval"), severity="warning", scope="report",
                                     source_ref=f"{source_name}:{kind}:{ordinal}", details=deepcopy(item)))
    if any(record.side == "unknown" for rs in record_sets for record in rs.records):
        flags.append(QualityFlag(quality_flag_id=_stable_id(package_id, "identity_unknown"),
                                 code="anatomical_side_unknown", severity="info", scope="report", source_ref=source_name,
                                 details={"meaning": "A/B are alternation labels, not anatomical left/right"}))
    flags.append(QualityFlag(quality_flag_id=_stable_id(package_id, "ground_contract"),
                             code="ground_measurement_scope", severity="info", scope="report", source_ref=source_name,
                             details={"spatial_reference": "contact_center" if walking else "stable_toe_proxy",
                                      "identity_basis": "manual_first_foot_and_alternation" if anchored else "alternation_only",
                                      "segment_count": summary["segment_count"],
                                      "steps_and_cycles": "producer records only; excluded candidates are not reconstructed",
                                      "walking_stride": "aggregate only; no invented cycle-to-stride pairing" if walking else None,
                                      "finish_reason": report.finish_reason}))
    payload = GroundPayload(kind="overground_walk" if walking else "overground_run",
                            contact_record_set_id=record_sets[0].record_set_id,
                            step_record_set_id=record_sets[1].record_set_id,
                            gait_cycle_record_set_id=record_sets[2].record_set_id,
                            spatial_reference="contact_center" if walking else "stable_toe_proxy",
                            record_sources=sources)
    return record_sets, facts, flags, payload
