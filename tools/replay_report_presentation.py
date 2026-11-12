"""Replay saved Report Agent decisions with deterministic tools and no model calls."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

if __name__ == "__main__" and not __package__:
    os.chdir(Path(__file__).resolve().parents[1])
    os.execv(sys.executable, [sys.executable, "-m", "tools.replay_report_presentation", *sys.argv[1:]])
import qt_runtime  # noqa: F401,E402
from pydantic import TypeAdapter
from agent.report.service import ReportAnalysisService
from config.test_config import default_jump_config
from config.treadmill_config import TreadmillGaitConfig
from config.test_report import JumpTestReport
from data.subject_store import SubjectStore
from reporting.models import AnalysisDecision, DataAccessScope, DraftAnalysisClaim, DraftAnalysisPackage, PredicateBinding, StopAnalysis
from reporting.repository import ReportRepository
from tools.benchmark_report_agent import load_report_agent_cases


class RecordedDecisionAgent:
    model_name = 'recorded-decisions'
    sequential_prompt_version = 'presentation-replay/1.0'

    def __init__(self, decisions):
        self.decisions = list(decisions)
        self.position = 0
        self.targets = {d['action_id']: d['hypothesis']['target_predicate'] for d in decisions if d['decision_type'] == 'analyze'}

    def decide(self, observation, state, evidence, skill_context):
        if self.position == len(self.decisions):
            return StopAnalysis(reason_code='evidence_sufficient', reason='Saved decisions exhausted')
        decision = self.decisions[self.position]
        self.position += 1
        return TypeAdapter(AnalysisDecision).validate_python(decision)

    def synthesize_sequential(self, observation, state, evidence, skill_context):
        claims = []
        for bundle in evidence:
            for item in bundle.items:
                target = self.targets.get(item.node_id)
                predicate = next((p for p in item.predicates if p.predicate == target and p.supported), None)
                if predicate is None or item.analysis_status != 'conclusive':
                    continue
                claims.append(DraftAnalysisClaim(
                    claim_id=f'c{len(claims)+1}', claim_type='derived',
                    text_template='该项分析已有计算结果。',
                    evidence_refs=(item.evidence_id,), tool_run_ids=(item.tool_run_id,),
                    predicate_bindings=(PredicateBinding(predicate=predicate.predicate, predicate_evidence_ref=predicate.predicate_evidence_id),),
                ))
        return DraftAnalysisPackage(summary='Saved decision replay', claims=tuple(claims))


def replay(source, output, *, preview=False):
    saved = json.loads(source.read_text())
    runs = saved.get('sequential', saved)['runs']
    cases = {c.case_id: c for c in load_report_agent_cases()}
    output.mkdir(parents=True, exist_ok=True)
    results = []
    previews = {}
    for run in runs:
        decisions = run.get('decision_trace', {}).get('sequential_decisions', [])
        if not decisions:
            continue
        case = cases[run['case_id']]
        with tempfile.TemporaryDirectory() as temporary:
            store = SubjectStore(Path(temporary) / 'replay.sqlite3')
            config = default_jump_config() if isinstance(case.report, JumpTestReport) else TreadmillGaitConfig(stop_type='End of Time', test_length='01:00', treadmill_speed=5.0, direction='Interface side')
            session_id = store.record_session(None, config, case.report)
            repository = ReportRepository(store)
            agent = RecordedDecisionAgent(decisions)
            service = ReportAnalysisService(repository, agent=agent)
            try:
                analysis = service.analyze(session_id, DataAccessScope())
                restored = repository.get_latest_validated_analysis(session_id, DataAccessScope(), analysis.package_digest)
                assert restored == analysis.model_dump(mode='json')
                name = f'{case.case_id}_{run["repetition"]}'
                (output / f'{name}.json').write_text(json.dumps(restored, ensure_ascii=False, indent=2))
                results.append({'case_id': case.case_id, 'repetition': run['repetition'], 'status': 'passed', 'highlights': len(analysis.presentation.insight_cards), 'charts': len(analysis.presentation.charts)})
                if case.case_id in {'temporal_increase', 'side_change', 'cross_metric'}:
                    previews.setdefault(case.case_id, (case.report, restored))
            except Exception as exc:
                results.append({'case_id': case.case_id, 'repetition': run['repetition'], 'status': 'failed', 'error': str(exc)})
    summary = {'source': str(source.resolve()), 'mode': 'saved tool decisions; fresh deterministic evidence and evidence-derived wording', 'model_calls': 0, 'data_kind': 'synthetic benchmark', 'runs': results}
    (output / 'replay_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    if preview:
        render_previews(previews, output)
    print(json.dumps({'runs': len(results), 'passed': sum(r['status'] == 'passed' for r in results), 'output': str(output.resolve())}, ensure_ascii=False))
    return all(r['status'] == 'passed' for r in results)


def render_previews(previews, output):
    from qtpy.QtWidgets import QApplication
    from qtpy.QtGui import QFont
    from ui.views.report_view import ReportView
    from ui.report_pdf import write_report_pdf

    app = QApplication.instance() or QApplication([])
    app.setFont(QFont('PingFang SC', 10))
    app.setStyle('Fusion')
    for name, (report, analysis) in previews.items():
        view = ReportView()
        view.load_report(report, analysis['session_id'])
        view.show_validated_analysis(analysis)
        view.resize(1280, 900)
        view.show()
        app.processEvents()
        view.grab().save(str(output / f'{name}_overview.png'))
        view._analysis_panel.resize(1000, 940)
        view._analysis_panel.show()
        app.processEvents()
        view._analysis_panel.grab().save(str(output / f'{name}.png'))
        if view._evidence_charts:
            chart = view._evidence_charts[0]
            chart.records_button.setChecked(True)
            app.processEvents()
            view._analysis_scroll.ensureWidgetVisible(chart)
            app.processEvents()
            view._analysis_panel.grab().save(str(output / f'{name}_records.png'))
        write_report_pdf(output / f'{name}.pdf', report, title='报告分析回放 · 合成测试', stats=view._export_stats, reason='历史工具决策回放', analysis=analysis)
        view.close()
        view._analysis_panel.close()
        view.deleteLater()
        app.processEvents()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('benchmark_results/report_agent_production_paired_compare_12x3_20260825.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()
    return 0 if replay(args.source, args.output, preview=args.preview) else 1


if __name__ == '__main__':
    raise SystemExit(main())
