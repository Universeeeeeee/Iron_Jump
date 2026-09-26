"""Offline contracts for production Report Agent benchmark modes."""

from tools import benchmark_report_agent as benchmark


def test_legacy_benchmark_agent_cannot_enter_sequential_production_path():
    assert callable(getattr(benchmark.TracedReportAgent(), "decide", None))
    assert not callable(
        getattr(benchmark.LegacyTracedReportAgent(), "decide", None)
    )


def test_comparison_runs_both_execution_modes(monkeypatch):
    calls = []

    def fake_run(cases, repetitions, **kwargs):
        calls.append(kwargs["execution_mode"])
        return {
            "execution_mode": kwargs["execution_mode"],
            "runs": [
                {
                    "status": "validated",
                    "elapsed_ms": 1,
                    "expected_predicates": (),
                    "discovered_predicates": (),
                    "decision_assertions": {},
                }
            ],
        }

    monkeypatch.setattr(benchmark, "run_report_agent_benchmark", fake_run)

    result = benchmark.run_report_agent_comparison(
        [
            benchmark.BenchmarkCase(
                "fixture", "fixture", object(), ()
            )
        ],
        1,
        ablation=benchmark.ABLATIONS["B"],
    )

    assert calls == ["legacy", "sequential"]
    assert result["execution_order"] == "paired_alternating"
    assert result["legacy"]["execution_mode"] == "legacy"
    assert result["sequential"]["execution_mode"] == "sequential"
