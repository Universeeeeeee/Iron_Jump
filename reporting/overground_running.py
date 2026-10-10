"""Presentation/export of independently valid ground-running metrics."""
import html
import json


FINISH_LABELS = {
    "passage_complete": "自动完成 · 已通过测量区域", "manual": "手动结束",
    "disconnected": "中止 · 设备断连", "data_timeout": "中止 · 数据超时",
    "layout_mismatch": "中止 · 布局变化", "device_changed": "中止 · 设备或数据流变化",
    "out_of_order_or_reset": "中止 · 设备帧序号异常", "counter_reset": "中止 · 设备计数重启",
    "packet_base_changed": "中止 · 协议分包变化", "turn_detected": "中止 · 检测到转身",
}

LABELS = {
    "id": "接触编号", "epoch": "连续观测段", "label": "A/B 身份", "side": "侧别",
    "candidate_outcome": "候选状态", "first_seen_sample": "首次观测采样",
    "touch_sample": "触地采样", "lift_sample": "离地采样", "confirmed_sample": "确认采样",
    "first_sample": "首采样", "last_sample": "末采样", "closed_sample": "结案采样",
    "source": "来源", "contact_id": "接触编号", "owner_id": "归属接触",
    "source_id": "片段证据编号", "outcome": "结案状态", "reason": "原因", "observed_samples": "有效观测数",
    "identity_source": "身份依据", "touch_s": "触地(s)", "lift_s": "离地(s)",
    "toe_m": "脚尖代理位置(m)", "contact_s": "接触时间(s)", "from_id": "起始接触",
    "to_id": "结束接触", "length_m": "距离(m)", "time_s": "步间时间(s)",
    "speed_m_s": "步间速度(m/s)", "flight_s": "腾空时间(s)", "duration_s": "周期时间(s)",
    "swing_s": "摆动时间(s)", "single_support_s": "单支撑(s)", "double_support_s": "双支撑(s)",
    "start_s": "开始(s)", "end_s": "结束(s)", "time_s_issue": "时间(s)",
    "code": "原因", "frame_index": "设备帧序号", "sample": "样本序号", "group": "分组",
    "metric": "指标", "count": "有效样本数", "mean": "均值", "left_count": "左侧样本数",
    "right_count": "右侧样本数", "left_mean": "左侧均值", "right_mean": "右侧均值",
    "asymmetry_percent": "描述性不对称率(%)", "step_length_m": "步长(m)",
}
REASONS = {
    "direction_unknown": "方向未确认", "short_contact": "接触过短",
    "toe_clipped": "脚尖被边界截断", "no_stable_toe_platform": "无可靠脚尖平台",
    "touch_not_observed": "未完整观测触地", "lift_not_observed": "未完整观测离地",
    "toe_unavailable": "脚尖参考缺失", "incomplete_contact": "接触不完整",
    "continuity_break": "连续性中断", "frame_gap": "丢帧", "stop_interval": "停步候选区间",
    "uncertain_short_clear": "短暂空白无法确认", "incomplete_observation": "观测不完整",
    "ambiguous_contacts": "遮挡合并或身份不明确", "simultaneous_contacts": "同时出现，身份不明确",
    "identity_uncertain": "身份不明确", "length_or_time_unavailable": "距离或时间缺失",
    "insufficient_bilateral_samples": "左右各需至少3个有效样本", "not_observed": "未观测",
    "invalid_sample": "样本无效", "checksum_or_tail_error": "校验错误", "turn_detected": "检测到转身",
    "local_unknown_timeout": "相关区域数据不足",
    "masked_contact_boundary": "接触边界邻近坏束",
    "unconfirmed_narrow_fragment": "窄候选关系未决",
    "excluded_nonstep": "已排除非步候选", "short_narrow_contact": "短窄候选未决",
    "closed_isolated_single_sample": "可靠释放的孤立单采样非步候选",
    "joined_existing_footprint": "归属已有光学组",
    "unresolved_coalescence": "光学合组的脚身份未决",
    "immature_islands_coalesced": "未成熟光学岛汇合，脚身份未决",
    "associated_fragment": "已有光学组片段",
}
VALUES = {"unresolved_group": "光学合组，脚身份未决",
          "immature_island": "合组前光学片段", "pending": "候选未决", "unresolved": "证据不足，保留未决",
          "confirmed_contact": "已确认接触", "associated_fragment": "已有光学组片段",
          "contact": "接触候选", "narrow": "暂存窄候选", "left": "左", "right": "右", "unknown": "未指定/无法确认",
          "manual_first_foot_and_alternation": "手动首脚＋单人交替假设",
          "alternation_only": "仅交替假设，使用 A/B", "all": "全部有效周期", "with_flight": "有腾空周期"}


def detail_html(report):
    s = report.running_summary
    content = '<p>脚尖代理：稳定前缘平台；与地面走路的中心参考口径不同。实测阈值与测量误差待验证。左右不对称率仅作描述，不作异常诊断。</p>'
    if 'record_count' in s:
        content += (f"<p>接触记录 {s['record_count']}；已确认接触 {s['confirmed_contacts']}；"
                    f"有效触地 {s['valid_touches']}；有效步间时间 {s['valid_steps']}；"
                    f"有效步长 {s['valid_step_lengths']}；有效周期时间 {s['valid_cycles']}；"
                    f"有效支撑周期 {s['valid_support_cycles']}。各项按自身证据计数。</p>")
    if report.report_config_snapshot.get('raw_buffer', {}).get('truncated'):
        content += '<p>原始帧缓存已截断，导出仅含末尾保留帧，统计基于完整处理过程。</p>'
    def show(v):
        if isinstance(v, dict) and 'valid' in v:
            return show(v['value']) if v['valid'] else '数据不足：' + REASONS.get(v['missing_reason'], str(v['missing_reason']))
        if v is None:
            return '数据不足'
        if isinstance(v, float):
            return f'{v:.4f}'
        return VALUES.get(v, REASONS.get(v, LABELS.get(v, str(v))))
    sections = [("逐步结果", s['steps']), ("逐接触结果", s['contacts']), ("同脚周期", s['cycles']),
                ("分组统计", [{"group": group, "metric": key, **stats}
                             for group, metrics in s['groups'].items() for key, stats in metrics.items()]),
                ("左右比较及样本数", [{"metric": k, **v} for k, v in s['sides'].items()]),
                ("候选结案证据", s.get('candidate_decisions', [])),
                ("停步候选区间", s['stops']), ("采集异常", s['issues'])]
    for label, rows in sections:
        content += '<h3>' + label + '</h3>'
        if not rows:
            content += '<p>无记录</p>'
            continue
        columns = list(dict.fromkeys(k for r in rows for k in r))
        content += '<table cellspacing="8"><tr>' + ''.join('<th>' + html.escape(LABELS.get(c, c)) + '</th>' for c in columns) + '</tr>'
        for row in rows:
            content += '<tr>' + ''.join('<td>' + html.escape(show(row.get(c))) + '</td>' for c in columns) + '</tr>'
        content += '</table>'
    return content


def export_sheets(wb, report):
    def flatten(data, prefix=''):
        out = {}
        for k, v in data.items():
            name = prefix + k
            if isinstance(v, dict):
                out.update(flatten(v, name + '.'))
            else:
                out[name] = json.dumps(v, ensure_ascii=False) if isinstance(v, (list, tuple)) else v
        return out
    summary = report.running_summary
    ws = wb.create_sheet('Running Summary')
    for k, v in flatten({k: v for k, v in summary.items() if k not in ('contacts', 'steps', 'cycles', 'stops', 'issues', 'candidate_decisions')}).items():
        ws.append([k, v])
    ws = wb.create_sheet('Device and Config')
    for k, v in report.report_config_snapshot.items():
        ws.append([k, json.dumps(v, ensure_ascii=False)])
    for key in ('contacts', 'steps', 'cycles', 'stops', 'issues', 'candidate_decisions'):
        if key == 'candidate_decisions' and key not in summary:
            continue
        ws = wb.create_sheet('Running ' + key)
        rows = [flatten(r) for r in summary.get(key, [])]
        columns = list(dict.fromkeys(k for r in rows for k in r))
        if columns:
            ws.append(columns)
            for r in rows:
                ws.append([r.get(k) for k in columns])
