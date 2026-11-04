"""Readable PDF exports from report snapshots using the application's Qt runtime."""
from __future__ import annotations

from html import escape


from config.test_report import JumpTestReport
from config.treadmill_report import TreadmillGaitReport, TreadmillRunningReport
from reporting.overground_running import REASONS, VALUES


def _text(value):
    if isinstance(value, dict) and 'valid' in value:
        return _text(value['value']) if value['valid'] else REASONS.get(
            value.get('missing_reason'), value.get('missing_reason') or '数据不足')
    if value is None:
        return '未测得'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, float):
        return f'{value:.3f}'
    return VALUES.get(str(value), REASONS.get(str(value), str(value)))


def _table(headers, rows):
    rows = list(rows)
    if not rows:
        return '<p>无记录</p>'
    header = ''.join('<th>' + escape(str(v)) + '</th>' for v in headers)
    body = ''.join('<tr>' + ''.join('<td>' + escape(_text(v)) + '</td>' for v in row)
                   + '</tr>' for row in rows)
    return '<table width="100%" cellspacing="0" cellpadding="5"><thead><tr>' + header + '</tr></thead>' + body + '</table>'


def report_html(report, *, title, stats, reason, detailed=False, subject=None, started_at=None, analysis=None, chart_sources=None):
    """Include all rows in the chosen sections, regardless of UI filters."""
    title = title.removeprefix('📊').strip()
    version = '详细版' if detailed else '精简版'
    subject = subject or {}
    content = '<h1>映衡 · ' + escape(title) + '</h1><p>' + version + '</p>'
    content += _table(['运动员', '测试时间', '结束状态'], [[
        subject.get('display_name') or '未记录', started_at or '未记录', reason]])
    snapshot = report.report_config_snapshot
    if snapshot.get('data_source') == 'simulation':
        content += '<p><b>模拟数据，非受试者实测。</b></p>'
    ground = getattr(report, 'walking_summary', None) or getattr(report, 'running_summary', None)
    core = stats[:8]
    if ground and any(row[0] in {'识别步数', '识别步数 / 步间'} for row in stats):
        labels = {'识别步数', '识别步数 / 步间', '识别步间 / 完整周期', '落脚点平均步长',
                  '落脚点平均速度', '识别步频', '平均接触时间', '平均接触（含估算）', '测量时长'}
        core = [row for row in stats if row[0] in labels]
    content += '<h2>测试摘要</h2>' + _table(['指标', '结果'], [(label, value) for label, value, _ in core])
    content += '<p>“未测得”或“数据不足”表示缺少有效测量证据，不等于零。各指标可能使用不同的有效样本。</p>'
    if snapshot.get('raw_buffer', {}).get('truncated'):
        content += '<p>原始帧缓存已截断；统计基于完整处理过程，原始数据导出仅含保留帧。</p>'
    quality = snapshot.get('beam_quality')
    if quality:
        bad = quality.get('preflight', {}).get('bad_indices', quality.get('masked', []))
        content += '<p>设备质量：' + ('存在降级或屏蔽光束，相关指标可能缺失。' if quality.get('degraded') or bad else '已记录设备质量检查。') + '</p>'
    if ground:
        from reporting.contact_quality import contact_quality_html
        content += contact_quality_html(report)
    if analysis:
        from reporting.analysis_html import analysis_html
        content += '<h2>运动分析</h2>' + analysis_html(analysis, chart_sources=chart_sources or {})
    if not detailed:
        return content
    content += '<p>逐帧数据与完整算法证据可另行导出 Excel。</p>'
    content += '<h2 style="page-break-before:always">指标说明</h2>' + _table(['指标', '结果', '统计口径'], stats)
    if isinstance(report, JumpTestReport):
        from reporting.excel import _jump_metric_rows
        rows = _jump_metric_rows(report)
        # Existing row adapter also supports saved legacy jump reports.
        content += '<h2>逐次跳跃</h2>' + _table(
            ['序号', '腾空(s)', '触地(s)', '周期(s)', '跳高(m)', '节奏(次/min)'],
            [row[:6] for row in rows])
        if report.jump_results:
            from reporting.excel import _statistics_reason_label, _quality_flags_text
            content += '<h2>跳跃质量</h2>' + _table(['序号', '纳入统计', '排除原因', '质量标记'], [
                [i + 1, r.is_included_in_statistics, _statistics_reason_label(r.statistics_exclusion_reason) if r.statistics_exclusion_reason else '',
                 _quality_flags_text(r.quality_flags)] for i, r in enumerate(report.jump_results)])
    elif isinstance(report, (TreadmillGaitReport, TreadmillRunningReport)):
        from reporting.excel import _statistics_reason_label, _quality_flags_text
        content += '<h2>逐步接触</h2>' + _table(
            ['序号', '脚', '触地(s)', '腾空(s)', '纳入统计', '说明'],
            [[i + 1, r.side, r.contact_time_s, r.flight_time_s, r.is_included_in_statistics,
              _statistics_reason_label(r.statistics_exclusion_reason) if r.statistics_exclusion_reason else _quality_flags_text(r.quality_flags)]
             for i, r in enumerate(report.per_step_results)])
        content += '<h2>同脚周期</h2>' + _table(
            ['序号', '脚', '周期(s)', '支撑相(%)', '摆动相(%)', '步幅(cm)'],
            [[i + 1, r.side, r.gait_cycle_s, r.stance_phase_percent, r.swing_phase_percent, r.stride_length_cm]
             for i, r in enumerate(report.gait_cycles)])
    elif ground:
        from reporting.ground_bilateral import bilateral_html
        content += bilateral_html(ground)
        from reporting.recognized_gait import recognized_html
        content += recognized_html(ground)
        content += '<h2>边界完整性明细</h2>' + _table(
            ['编号', '脚', '触地(s)', '离地(s)', '接触(s)', '状态'],
            [[r['id'], r.get('side'), r.get('touch_s', r.get('start')), r.get('lift_s', r.get('end')),
              r.get('contact_s'), r.get('exclusion') or r.get('candidate_outcome') or '已记录']
             for r in ground.get('contacts', [])])
        content += '<h2>逐步结果</h2>' + _table(
            ['起始编号', '结束编号', '步长(m)', '步间时间(s)', '速度(m/s)'],
            [[r.get(k) for k in ('from_id', 'to_id', 'length_m', 'time_s', 'speed_m_s')]
             for r in ground.get('steps', [])])
        running = bool(getattr(report, 'running_summary', None))
        endpoints = ('from_id', 'to_id') if running else ('start_s', 'end_s')
        headers = ['起始接触', '结束接触'] if running else ['开始(s)', '结束(s)']
        content += '<h2>同脚周期</h2>' + _table(
            headers + ['周期(s)', '单支撑(s)', '双支撑(s)', '腾空(s)'],
            [[r.get(k) for k in endpoints + ('duration_s', 'single_support_s', 'double_support_s', 'flight_s')]
             for r in ground.get('cycles', [])])
        if ground.get('issues'):
            content += '<h2>采集异常</h2>' + _table(['时间(s)', '原因'], [
                [r.get('time_s'), r.get('code')] for r in ground['issues']])
    return content
