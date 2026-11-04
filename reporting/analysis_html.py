"""Shared readable analysis content for the report UI and PDF."""

import html
from urllib.parse import urlparse


_LIMITATIONS = {
    'co_change_is_not_causation': '共同变化只描述本次记录中的关联。',
    'insufficient_sample_size': '有效样本不足。',
    'quality_invalidation': '相关数据的质量条件不足。',
    'investigation_deadline_reached': '分析已达到本次时间限制。',
    'decision_request_timeout': '本次分析请求超时。',
}


def _limitations(values, label):
    if not values:
        return ''
    text = '；'.join(html.escape(_LIMITATIONS.get(str(v), str(v))) for v in values)
    return f'<p style="color:#7e8998">{label}：{text}</p>'


def analysis_html(analysis: dict, chart_sources=None) -> str:
    claims = analysis.get('claims', [])
    claim_by_id = {c.get('claim_id'): c for c in claims if c.get('claim_id')}
    references = analysis.get('references', [])
    reference_by_id = {r.get('citation_id'): i for i, r in enumerate(references, 1) if r.get('citation_id')}
    recommendations = analysis.get('recommendations', [])
    recommendation_by_id = {r.get('recommendation_id'): r for r in recommendations if r.get('recommendation_id')}
    presentation = analysis.get('presentation') or {}
    charts = presentation.get('charts', [])
    chart_by_id = {c['chart_id']: i for i, c in enumerate(charts)}
    sections = []
    shown_claims = set()
    shown_texts = set()
    shown_recommendations = set()
    shown_charts = set()

    def claim_content(claim):
        return '<p>' + html.escape(claim.get('text', '').strip()) + '</p>' + _limitations(claim.get('limitations', []), '证据限制')

    def recommendation_content(recommendation):
        citations = ' '.join(f'[{reference_by_id[ref]}]' for ref in recommendation.get('citation_refs', []) if ref in reference_by_id)
        return '<p>' + html.escape(str(recommendation.get('text', '')).strip()) + ' ' + citations + '</p>' + _limitations(recommendation.get('limitations', []), '建议限制')

    cards = presentation.get('insight_cards', [])
    if cards:
        sections.append('<h3>本次重点</h3><p>' + html.escape(analysis.get('summary', '')) + '</p>')
    for index, card in enumerate(cards, 1):
        claim = claim_by_id.get(card.get('claim_id'))
        if claim is None:
            continue
        shown_claims.add(card['claim_id'])
        shown_claims.update(card.get('related_claim_ids', []))
        shown_texts.add(claim.get('text', ''))
        page_break = ' style="page-break-before:always"' if chart_sources is not None and index > 1 else ''
        sections.append(f'<h3{page_break}>{index}. {html.escape(card.get("title", "分析发现"))}</h3>' + claim_content(claim))
        for chart_id in card.get('chart_ids', []):
            if chart_id not in chart_by_id or chart_id in shown_charts:
                continue
            shown_charts.add(chart_id)
            if chart_sources and chart_id in chart_sources:
                uri, height = chart_sources[chart_id]
                sections.append(f'<p style="margin:0;line-height:100%"><img width="500" height="{height}" src="{html.escape(uri, quote=True)}"></p>')
            elif chart_sources is None:
                chart_title = html.escape(charts[chart_by_id[chart_id]]['title'])
                sections.append(f'<p><a style="color:#67dce9" href="analysis-chart:{chart_by_id[chart_id]}">查看{chart_title}证据图与记录</a></p>')
        linked = []
        for rec_id in card.get('recommendation_ids', []):
            recommendation = recommendation_by_id.get(rec_id)
            if recommendation and set(recommendation.get('claim_refs', [])).intersection((card['claim_id'], *card.get('related_claim_ids', []))):
                shown_recommendations.add(rec_id)
                linked.append(recommendation_content(recommendation))
        if linked:
            sections.append('<b>关联行动建议</b>' + ''.join(linked))
    other_claims = []
    for claim in claims:
        text = claim.get('text', '')
        if not text or claim.get('claim_id') in shown_claims or (cards and text in shown_texts):
            continue
        shown_texts.add(text)
        other_claims.append(claim_content(claim))
    if other_claims:
        sections.append(('<h3>其他分析结论</h3>' if cards else '<h3>分析结论</h3>') + ''.join(other_claims))
    remaining = [recommendation_content(r) for r in recommendations if r.get('recommendation_id') not in shown_recommendations]
    if remaining:
        sections.append('<h3>循证行动建议</h3>' + ''.join(remaining))
    reference_lines = []
    for index, reference in enumerate(references, 1):
        url = str(reference.get('url', ''))
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            continue
        title = html.escape(str(reference.get('title', '参考资料')))
        locator = html.escape(str(reference.get('locator', '')))
        reference_lines.append(f'<p>[{index}] <a href="{html.escape(url, quote=True)}">{title}</a> {locator}</p>')
    if reference_lines:
        sections.append('<h3>参考资料</h3>' + ''.join(reference_lines))
    audit = analysis.get('rag_audit') or {}
    if audit.get('status') == 'degraded':
        sections.append('<p>循证建议暂时不可用，确定性分析不受影响。</p>')
    elif audit.get('status') == 'no_evidence':
        sections.append('<p>当前测试场景或已验证指标尚无适用的循证建议，因此未生成建议。</p>' if audit.get('error_code') == 'no_supported_query' else '<p>未检索到满足条件的文献证据，因此未生成建议。</p>')
    sections.append(_limitations(analysis.get('overall_limitations', []), '限制'))
    return ''.join(sections) or '未形成可验证的分析结论。'
