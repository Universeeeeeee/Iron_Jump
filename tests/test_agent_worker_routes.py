"""Business-route isolation contracts for the single Agent worker."""

import pytest

from agent import worker


def test_config_routes_keep_namespaced_and_legacy_compatibility():
    assert worker._route_name("/config/chat") == "config_chat"
    assert worker._route_name("/chat") == "config_chat"
    assert worker._route_name("/config/chat_stream") == "config_chat_stream"
    assert worker._route_name("/chat_stream") == "config_chat_stream"
    assert worker._route_name("/config/reset") == "config_reset"
    assert worker._route_name("/reset") == "config_reset"


def test_report_routes_are_namespaced_without_sharing_config_state():
    assert worker._route_name("/report/analyze") == "report_analyze"
    assert worker._route_name("/report/latest") == "report_latest"
    assert worker._report_lock is not worker._config_lock
    assert not hasattr(worker, "_agent_lock")


def test_report_rag_construction_failure_is_isolated(monkeypatch):
    monkeypatch.setattr(
        "knowledge.release_gate.v1_release_status", lambda: "enabled"
    )

    class _FailingEmbedding:
        def __init__(self):
            raise RuntimeError("embedding unavailable")

    monkeypatch.setattr(
        "knowledge.embeddings.LocalEmbeddingModel", _FailingEmbedding
    )

    pipeline, error_code = worker._build_report_rag_pipeline()

    assert pipeline is None
    assert error_code == "rag_initialization_failed"


def test_report_rag_catalog_construction_failure_is_isolated(monkeypatch):
    monkeypatch.setattr(
        "knowledge.release_gate.v1_release_status", lambda: "enabled"
    )
    monkeypatch.setattr(
        "knowledge.embeddings.LocalEmbeddingModel", lambda: object()
    )

    class _FailingPipeline:
        def __init__(self, *args, **kwargs):
            raise ValueError("catalog invalid")

    monkeypatch.setattr(
        "knowledge.pipeline.DeterministicRAGPipeline", _FailingPipeline
    )

    pipeline, error_code = worker._build_report_rag_pipeline()

    assert pipeline is None
    assert error_code == "rag_initialization_failed"


def test_report_rag_invalid_enabled_gate_is_reported(monkeypatch):
    monkeypatch.setattr(
        "knowledge.release_gate.v1_release_status", lambda: "invalid"
    )

    pipeline, error_code = worker._build_report_rag_pipeline()

    assert pipeline is None
    assert error_code == "rag_release_gate_invalid"


def test_report_request_accepts_only_session_and_scope_schema():
    request = worker._parse_report_request(
        {
            "session_id": 12,
            "data_access_scope": {
                "current_session": True,
                "longitudinal": False,
                "cohort": False,
            },
        }
    )
    assert request.session_id == 12

    with pytest.raises(ValueError):
        worker._parse_report_request(
            {
                "session_id": 12,
                "data_access_scope": {"current_session": True},
                "sql": "SELECT * FROM test_sessions",
            }
        )


def test_report_request_rejects_disabled_current_session_scope():
    with pytest.raises(ValueError):
        worker._parse_report_request(
            {
                "session_id": 12,
                "data_access_scope": {"current_session": False},
            }
        )


def test_unknown_route_is_not_resolved():
    assert worker._route_name("/tools/run") is None


@pytest.mark.parametrize(
    "error_code,status",
    (
        ("analysis_timeout", 504),
        ("report_configuration_invalid", 503),
        ("analysis_failed", 500),
        ("unsupported_predicate", 422),
    ),
)
def test_report_error_codes_have_stable_http_status(error_code, status):
    assert worker._report_error_status(error_code) == status


def test_routed_chat_selects_prompt_before_configuration(monkeypatch):
    from agent.config.intent import ModeIntent
    from config.walking_config import WalkingConfig
    calls, responses = [], []
    class Service:
        def chat(self, message, profile, mode):
            calls.append((message, mode))
            return WalkingConfig(), "已配置地面走路"
    monkeypatch.setattr(worker, "_get_status", lambda: ("ready", ""))
    monkeypatch.setattr(worker, "_get_config_service", lambda: Service())
    monkeypatch.setattr("agent.config.intent.classify", lambda *args: ModeIntent(
        action="configure", movement="walk", surface="ground"))
    handler = object.__new__(worker._Handler)
    handler._send_json = lambda result, status=200: responses.append(result)
    handler._handle_chat({"message": "地面走路", "agent_mode": "jump", "route_intent": True, "segment_count": 8})
    assert calls == [("地面走路", "walking")]
    assert responses[0]["mode"] == "walking"
    assert responses[0]["config"]["test_type"] == "Sprint and Gait Test"
    monkeypatch.setattr("agent.config.intent.classify", lambda *args: ModeIntent(
        action="configure", movement="walk", surface="unknown"))
    handler._handle_chat({"message": "走路", "route_intent": True, "segment_count": 8})
    assert len(calls) == 1
    assert "pending" in responses[-1] and "config" not in responses[-1]
