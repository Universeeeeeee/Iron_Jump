"""
worker.py — Agent 独立 Worker 进程

常驻后台，按业务路由复用独立 Service，通过 HTTP 与主进程通信。
启动: python agent/worker.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from agent import ConfigService, AthleteProfile

PORT_FILE = Path(tempfile.gettempdir()) / "ironjump_llm_port.txt"
IDLE_TIMEOUT = 600  # 10 分钟

_config_service: ConfigService | None = None
_report_service = None
_last_active = time.monotonic()
_config_lock = threading.RLock()
_report_lock = threading.RLock()
_state_lock = threading.Lock()
_status = "warming"
_startup_error = ""


def _get_config_service() -> ConfigService:
    global _config_service
    with _config_lock:
        if _config_service is None:
            service = ConfigService(mode="online")
            service.warmup()
            _config_service = service
        return _config_service


def _build_report_rag_pipeline():
    from knowledge.embeddings import LocalEmbeddingModel
    from knowledge.ingestion import DEFAULT_DATA_DIR
    from knowledge.pipeline import DeterministicRAGPipeline
    from knowledge.release_gate import (
        RELEASE_GATE_DISABLED,
        RELEASE_GATE_ENABLED,
        v1_release_status,
    )
    from knowledge.retrieval import HybridRetriever
    from knowledge.store import KnowledgeStore

    gate_status = v1_release_status()
    if gate_status == RELEASE_GATE_DISABLED:
        return None, None
    if gate_status != RELEASE_GATE_ENABLED:
        print(
            "[llm_worker] RAG release gate configuration is invalid; "
            "deterministic report analysis remains available"
        )
        return None, "rag_release_gate_invalid"
    try:
        embedder = LocalEmbeddingModel()
        return (
            DeterministicRAGPipeline(
                HybridRetriever(KnowledgeStore(), embedder),
                manifest_path=DEFAULT_DATA_DIR / "manifest.json",
            ),
            None,
        )
    except Exception:
        print(
            "[llm_worker] RAG initialization failed; "
            "deterministic report analysis remains available:\n"
            f"{traceback.format_exc()}"
        )
        return None, "rag_initialization_failed"


def _get_report_service():
    global _report_service
    with _report_lock:
        if _report_service is None:
            from agent.report.service import ReportAnalysisService
            from data.subject_store import SubjectStore
            from reporting.repository import ReportRepository

            rag_pipeline, rag_unavailable_error_code = (
                _build_report_rag_pipeline()
            )
            _report_service = ReportAnalysisService(
                ReportRepository(SubjectStore()),
                rag_pipeline=rag_pipeline,
                rag_unavailable_error_code=rag_unavailable_error_code,
            )
        return _report_service


def _set_status(status: str, error: str = ""):
    global _status, _startup_error
    with _state_lock:
        _status = status
        _startup_error = error


def _get_status() -> tuple[str, str]:
    with _state_lock:
        return _status, _startup_error


def _warmup_agent():
    try:
        print("[llm_worker] warming up agent...")
        _get_config_service()
        _set_status("ready")
        print("[llm_worker] ready")
    except Exception:
        error = traceback.format_exc()
        _set_status("error", error)
        print(f"[llm_worker] warmup failed:\n{error}")


def _touch_active():
    global _last_active
    _last_active = time.monotonic()


def _profile_from_dict(data: dict) -> AthleteProfile:
    return AthleteProfile(
        age=data.get("age", 30),
        weight=data.get("weight", 70.0),
        height=data.get("height", 170.0),
        level=data.get("level", "intermediate"),
        focus_side=data.get("focus_side", ""),
        device_channels=data.get("device_channels", 8),
        history=data.get("history", []),
    )


def _route_name(path: str) -> str | None:
    """Resolve compatibility and namespaced HTTP paths to one business route."""
    return {
        "/chat": "config_chat",
        "/config/chat": "config_chat",
        "/chat_stream": "config_chat_stream",
        "/config/chat_stream": "config_chat_stream",
        "/reset": "config_reset",
        "/config/reset": "config_reset",
        "/report/analyze": "report_analyze",
        "/report/latest": "report_latest",
    }.get(path)


def _report_error_status(error_code: str) -> int:
    if error_code == "analysis_timeout":
        return 504
    if error_code == "report_configuration_invalid":
        return 503
    if error_code == "analysis_failed":
        return 500
    return 422


class _Handler(BaseHTTPRequestHandler):

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            status, error = _get_status()
            payload = {"status": status}
            if error:
                payload["error"] = error
            self._send_json(payload)
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # curl on Windows Git Bash may send GBK-encoded Chinese
            try:
                data = json.loads(raw.decode("gbk", errors="replace"))
            except Exception:
                self._send_json({"error": "invalid json"}, 400)
                return

        route = _route_name(self.path)
        if route == "config_chat":
            self._handle_chat(data)
        elif route == "config_chat_stream":
            self._handle_chat_stream(data)
        elif route == "config_reset":
            self._handle_reset()
        elif route == "report_analyze":
            self._handle_report_analyze(data)
        elif route == "report_latest":
            self._handle_report_latest(data)
        else:
            self._send_json({"error": "not found"}, 404)

    def _handle_chat(self, data: dict):
        _touch_active()
        status, error = _get_status()
        if status != "ready":
            self._send_json({"error": error or "worker not ready", "status": status}, 503)
            return
        service = _get_config_service()
        message = data.get("message", "")
        agent_mode = data.get("agent_mode", "jump")
        profile = _profile_from_dict(data.get("athlete", {}))
        try:
            with _config_lock:
                config, reply = service.chat(message, profile, mode=agent_mode)
            result: dict = {"reply": reply}
            if config is not None:
                result["config"] = config.to_dict()
            self._send_json(result)
        except Exception:
            self._send_json({"error": traceback.format_exc()}, 500)

    def _handle_chat_stream(self, data: dict):
        _touch_active()
        status, error = _get_status()
        if status != "ready":
            self._send_json({"error": error or "worker not ready", "status": status}, 503)
            return
        service = _get_config_service()
        message = data.get("message", "")
        agent_mode = data.get("agent_mode", "jump")
        profile = _profile_from_dict(data.get("athlete", {}))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            def on_chunk(text: str):
                chunk = json.dumps({"text": text}, ensure_ascii=False)
                self.wfile.write(f"data: {chunk}\n\n".encode())
                self.wfile.flush()
            with _config_lock:
                config, reply = service.chat_stream(
                    message, profile, agent_mode, on_chunk
                )
            done = json.dumps({"reply": reply, "config": config.to_dict() if config else None}, ensure_ascii=False)
            self.wfile.write(f"data: {done}\n\n".encode())
        except Exception:
            err = json.dumps({"error": traceback.format_exc()})
            self.wfile.write(f"data: {err}\n\n".encode())

    def _handle_reset(self):
        _touch_active()
        status, error = _get_status()
        if status != "ready":
            self._send_json({"error": error or "worker not ready", "status": status}, 503)
            return
        service = _get_config_service()
        with _config_lock:
            service.reset()
        self._send_json({"status": "ok"})

    def _handle_report_analyze(self, data: dict):
        _touch_active()
        status, error = _get_status()
        if status != "ready":
            self._send_json(
                {"error_code": "worker_not_ready", "status": status},
                503,
            )
            return
        try:
            request = _parse_report_request(data)
        except ValueError as exc:
            self._send_json(
                {"error_code": "invalid_request", "message": str(exc)},
                400,
            )
            return
        try:
            with _report_lock:
                analysis = _get_report_service().analyze(
                    request.session_id,
                    request.data_access_scope,
                )
            self._send_json(
                {
                    "analysis": analysis.model_dump(mode="json"),
                    "analysis_run_id": analysis.analysis_run_id,
                }
            )
        except Exception as exc:
            error_code = getattr(exc, "code", "analysis_failed")
            status = _report_error_status(error_code)
            payload = {"error_code": error_code, "message": str(exc)}
            analysis_run_id = getattr(exc, "analysis_run_id", None)
            timeout_stage = getattr(exc, "timeout_stage", None)
            if analysis_run_id is not None:
                payload["analysis_run_id"] = analysis_run_id
            if timeout_stage is not None:
                payload["timeout_stage"] = timeout_stage
            self._send_json(
                payload,
                status,
            )

    def _handle_report_latest(self, data: dict):
        _touch_active()
        try:
            request = _parse_report_request(data)
        except ValueError as exc:
            self._send_json(
                {"error_code": "invalid_request", "message": str(exc)},
                400,
            )
            return
        try:
            with _report_lock:
                analysis = _get_report_service().get_latest(
                    request.session_id,
                    request.data_access_scope,
                )
            self._send_json({"analysis": analysis})
        except Exception as exc:
            self._send_json(
                {
                    "error_code": getattr(exc, "code", "analysis_unavailable"),
                    "message": str(exc),
                },
                422,
            )

    def log_message(self, format, *args):
        pass  # silence HTTP log


class _ThreadingServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True


def _parse_report_request(data: dict):
    from pydantic import ValidationError

    from agent.report.models import ReportAnalysisRequest

    try:
        return ReportAnalysisRequest.model_validate(data)
    except ValidationError as exc:
        raise ValueError("report analysis request does not match schema") from exc


def _idle_monitor():
    while True:
        time.sleep(10)
        if time.monotonic() - _last_active > IDLE_TIMEOUT:
            print("[llm_worker] idle timeout, exiting")
            os._exit(0)


def main():
    server = _ThreadingServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    PORT_FILE.write_text(json.dumps({"pid": os.getpid(), "port": port}))
    print(f"[llm_worker] listening on 127.0.0.1:{port}")

    threading.Thread(target=_warmup_agent, daemon=True).start()
    threading.Thread(target=_idle_monitor, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        PORT_FILE.unlink(missing_ok=True)
        server.server_close()


if __name__ == "__main__":
    main()
