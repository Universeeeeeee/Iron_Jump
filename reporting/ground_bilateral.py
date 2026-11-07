"""Present the frozen bilateral snapshot; no metric recalculation here."""
import html
import json

from .metric_catalog import METRIC_CATALOG


def comparison_rows(summary):
    for code, item in summary.get('bilateral', {}).get('statistics', {}).items():
        definition = METRIC_CATALOG[code]
        row = {'metric': code, 'label': '本侧单支撑时间' if code == 'single_support_s' else definition.label,
               'unit': definition.unit}
        for side in ('left', 'right', 'all', 'unknown'):
            for key in ('count', 'mean', 'std', 'cv_percent', 'min', 'max', 'source_refs', 'missing_reasons'):
                row[f'{side}_{key}'] = item[side][key]
        row.update(difference=item['difference']['value'],
                   difference_unit='百分点' if definition.unit == '%' else definition.unit,
                   si_percent=item['si_percent']['value'], si_missing_reason=item['si_percent']['missing_reason'])
        row.update(diff_percent=item.get('diff_percent', {}).get('value'),
                   diff_missing_reason=item.get('diff_percent', {}).get('missing_reason', 'historical_metric_not_recorded'))
        yield row


def bilateral_html(summary):
    snapshot = summary.get('bilateral')
    if not snapshot:
        return '<p>左右参数：历史记录未包含本版统计。</p>'
    def show(number):
        return '—' if number is None else f'{number:.4g}'
    available = [row for row in comparison_rows(summary) if row['left_count'] or row['right_count']]
    if not available:
        reason = ('未指定起始脚，无法对应左右脚' if snapshot['starting_foot'] not in {'Left', 'Right'}
                  else '缺少可确认侧别的有效样本，无法进行左右比较')
        count = snapshot['statistics']['contact_time_s']['all']['count']
        guidance = ('测试前指定实际首先进入测量区的脚，才能按可靠落脚顺序统计左右参数。'
                    if snapshot['starting_foot'] not in {'Left', 'Right'} else '')
        return (f'<h3>左右参数（有效观测）</h3><p>{reason}。'
                f'有效接触样本 {count} 个，总体指标仍予保留。{guidance}</p>')
    content = ('<h3>左右参数（有效观测）</h3><p>按可靠落脚交替分侧；仅使用原始有效指标，'
               '不包含补全估算。标准差采用总体口径；不足两个样本不显示标准差和变异系数。'
               '不对称率为均值归一化绝对差异，每侧至少 3 个样本；零分母留空。'
               '差值为左减右，比例指标的差值单位为百分点。</p>')
    reference = '足迹中心' if snapshot['spatial_reference'] == 'contact_center' else '稳定脚尖代理'
    foot = {'Left': '左脚', 'Right': '右脚'}.get(snapshot['starting_foot'], '未指定')
    content += f'<p>起始脚：{foot}；空间参考：{reference}。</p>'
    contacts = snapshot['statistics']['contact_time_s']
    content += (f"<p>有效接触时间样本：左 {contacts['left']['count']}、右 {contacts['right']['count']}、"
                f"未知侧别 {contacts['unknown']['count']}。其余指标按各自有效样本计数。</p>")
    content += '<table cellspacing="8"><tr>' + ''.join(f'<th>{label}</th>' for label in
        ('指标', '单位', '左均值 ± 标准差', '右均值 ± 标准差', '样本数 左/右', '变异系数% 左/右', '左−右', '不对称率%', '左侧参照差异%')) + '</tr>'
    labels = {'duty_factor_percent': '触地占比（单步分母）',
              'imbalance_theory_percent': '接触不平衡率（相邻均值分母）',
              'imbalance_sample_percent': '接触不平衡率（当前接触分母）',
              'stride_angle_deg': '轨迹角（估计）'}
    for row in available:
        cells = [labels.get(row['metric'], row['label']), {'steps/min': '步/分钟', 'deg': '°'}.get(row['unit'], row['unit']),
                 show(row['left_mean']) + ' ± ' + show(row['left_std']),
                 show(row['right_mean']) + ' ± ' + show(row['right_std']),
                 f"{row['left_count']}/{row['right_count']}",
                 show(row['left_cv_percent']) + '/' + show(row['right_cv_percent']),
                 show(row['difference']), show(row['si_percent']), show(row['diff_percent'])]
        content += '<tr>' + ''.join('<td>' + html.escape(str(cell)) + '</td>' for cell in cells) + '</tr>'
    content += '</table><p>“—”表示未观测、样本不足或分母为零；不代表零。无左右有效样本的指标未列出；未知侧别仅进入总体统计。</p>'
    reasons = {reason for item in snapshot['statistics'].values() for reason in item['all']['missing_reasons']}
    if 'entry_support_not_observed' in reasons:
        content += '<p>入口周期缺少前一次对侧接触，单／双支撑阶段未纳入统计。</p>'
    if snapshot.get('contact_phase_version'):
        content += '<p>足内阶段为光学估计。左侧参照差异以左均值为分母；两种接触不平衡率均保留正负方向，分母分别为相邻接触均值和当前接触时间。</p>'
    return content


def export_bilateral(wb, summary):
    snapshot = summary.get('bilateral')
    if not snapshot:
        return
    def cell(item):
        return json.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else item
    rows = list(comparison_rows(summary))
    sheet = wb.create_sheet('左右统计')
    if rows:
        columns = list(rows[0])
        sheet.append(columns)
        for row in rows:
            sheet.append([cell(row[key]) for key in columns])
    sheet = wb.create_sheet('左右参数明细')
    sheet.append(['source_ref', 'contact_ids', 'side', 'metric', 'value', 'valid', 'missing_reason', 'derivation_contact_ids'])
    for records in snapshot['records'].values():
        for row in records:
            for code, metric in row['metrics'].items():
                sheet.append([row['source_ref'], cell(row['contact_ids']), row['side'], code,
                              metric['value'], metric['valid'], metric['missing_reason'], cell(row.get('derivation_contact_ids', row['contact_ids']))])
    sheet = wb.create_sheet('左右参数定义')
    for key, item in snapshot.items():
        if key not in {'records', 'statistics'}:
            sheet.append([key, cell(item)])
    if summary.get('contact_phases'):
        sheet = wb.create_sheet('足内阶段证据')
        sheet.append(['contact_id', 'event_id', 'event_revision', 'boundaries', 'evidence_available_sample', 'interpretation'])
        for row in summary['contact_phases']['contacts']:
            sheet.append([row['contact_id'], row.get('event_id'), row.get('event_revision'),
                          cell(row['boundaries']), row.get('evidence_available_sample'), row['interpretation']])
        sheet = wb.create_sheet('足内形状')
        sheet.append(['contact_id', 'start_sample', 'end_sample_exclusive', 'islands', 'missing_reason'])
        for row in summary['contact_phases']['contacts']:
            for a, b, islands, reason in row['shape_runs']:
                sheet.append([row['contact_id'], a, b, cell(islands), reason])
