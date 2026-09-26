"""
llm_client.py — Agent Worker HTTP 客户端

主进程通过此模块与 agent/worker.py 通信。
不 import 任何 Agent 业务模块。
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path

import requests

PORT_FILE = Path(tempfile.gettempdir()) / "ironjump_llm_port.txt"
DEFAULT_REPORT_ANALYSIS_DEADLINE_SECONDS = 90.0
REPORT_ANALYSIS_CLIENT_GRACE_SECONDS = 15.0


def _default_report_analysis_client_timeout() -> float:
    raw = os.getenv("REPORT_ANALYSIS_DEADLINE_SECONDS")
    try:
        deadline = (
            DEFAULT_REPORT_ANALYSIS_DEADLINE_SECONDS
            if raw is None or not raw.strip()
            else float(raw)
        )
    except ValueError:
        deadline = DEFAULT_REPORT_ANALYSIS_DEADLINE_SECONDS
    if not math.isfinite(deadline) or deadline <= 20:
        deadline = DEFAULT_REPORT_ANALYSIS_DEADLINE_SECONDS
    return deadline + REPORT_ANALYSIS_CLIENT_GRACE_SECONDS


class AgentWorkerClient:
    """Agent Worker HTTP 客户端。

    管理 worker 进程的启动、健康检查、请求转发。
    """

    def __init__(
        self,
        python_exe: str,
        worker_script: str,
        port_file: Path | None = None,
        startup_grace_seconds: float = 60.0,
    ):
        self._python_exe = python_exe
        self._worker_script = worker_script
        self._port_file = port_file or PORT_FILE
        self._startup_grace_seconds = startup_grace_seconds
        self._started_at: float | None = None
        self._process = None

    # ------------------------------------------------------------------
    #  进程管理
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        if self._process is None:
            return False
        try:
            state = self._process.state()
        except RuntimeError:
            return False

        running_state = getattr(self._process, "Running", None)
        if running_state is None:
            process_state = getattr(self._process, "ProcessState", None)
            running_state = getattr(process_state, "Running", None)
        if running_state is None:
            try:
                from qtpy.QtCore import QProcess
                process_state = getattr(QProcess, "ProcessState", None)
                running_state = getattr(process_state, "Running", None)
                if running_state is None:
                    running_state = getattr(QProcess, "Running", None)
            except Exception:
                running_state = None

        if running_state is not None:
            return state == running_state
        return str(state).endswith("Running")

    def start(self) -> bool:
        """启动 worker 进程（非阻塞）。返回 True 若启动成功。"""
        if self.is_running:
            return True
        from qtpy.QtCore import QProcess
        self._port_file.unlink(missing_ok=True)
        self._process = QProcess()
        self._process.setProgram(self._python_exe)
        self._process.setArguments([self._worker_script])
        self._process.start()
        started = self._process.waitForStarted(3000)
        self._started_at = time.monotonic() if started else None
        return started

    def stop(self):
        if self._process is not None:
            self._process.terminate()
            self._process.waitForFinished(3000)
            self._process = None
            self._started_at = None
        self._port_file.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    #  通信
    # ------------------------------------------------------------------

    def _process_id(self) -> int | None:
        if self._process is None:
            return None
        try:
            return int(self._process.processId())
        except Exception:
            return None

    def _within_startup_grace(self) -> bool:
        return (
            self._started_at is not None
            and time.monotonic() - self._started_at < self._startup_grace_seconds
        )

    def _read_port_info(self) -> dict | None:
        try:
            raw = self._port_file.read_text().strip()
            if raw.startswith("{"):
                info = json.loads(raw)
            else:
                info = {"port": int(raw)}
            port = int(info["port"])
            pid = info.get("pid")
            process_id = self._process_id()
            if pid is not None and process_id is not None and int(pid) != process_id:
                return None
            return {"port": port, "pid": pid}
        except Exception:
            return None

    def _base_url(self) -> str | None:
        info = self._read_port_info()
        if info is None:
            return None
        try:
            port = int(info["port"])
            return f"http://127.0.0.1:{port}"
        except Exception:
            return None

    def worker_status(self, timeout: float = 0.5) -> str:
        if not self.is_running:
            return "stopped"
        url = self._base_url()
        if url is None:
            return "starting" if self._within_startup_grace() else "unreachable"
        try:
            r = requests.get(f"{url}/health", timeout=timeout)
            if r.status_code != 200:
                return "unreachable"
            status = r.json().get("status")
            return status if status in {"warming", "ready", "error"} else "unreachable"
        except Exception:
            return "starting" if self._within_startup_grace() else "unreachable"

    def health_check(self, timeout: float = 0.5) -> bool:
        return self.worker_status(timeout=timeout) == "ready"

    def chat(self, message: str, athlete: dict, agent_mode: str = "jump") -> dict:
        """POST /config/chat，返回配置结果或稳定错误。"""
        url = self._base_url()
        if url is None:
            return {"error": "worker 未启动"}
        if not self.health_check(timeout=0.5):
            return {"error": "worker 未就绪"}
        r = requests.post(f"{url}/config/chat", json={
            "message": message,
            "athlete": athlete,
            "agent_mode": agent_mode,
        }, timeout=120)
        return r.json()

    def reset(self):
        url = self._base_url()
        if url is None:
            return
        try:
            requests.post(f"{url}/config/reset", timeout=5)
        except Exception:
            pass

    def analyze_report(
        self,
        session_id: int,
        scope: dict,
        timeout: float | None = None,
    ) -> dict:
        url = self._base_url()
        if url is None:
            return {"error_code": "worker_not_started"}
        if not self.health_check(timeout=0.5):
            return {"error_code": "worker_not_ready"}
        try:
            response = requests.post(
                f"{url}/report/analyze",
                json={
                    "session_id": session_id,
                    "data_access_scope": scope,
                },
                timeout=(
                    _default_report_analysis_client_timeout()
                    if timeout is None
                    else timeout
                ),
            )
            return response.json()
        except requests.Timeout:
            return {"error_code": "analysis_client_timeout"}
        except requests.RequestException:
            return {"error_code": "worker_unreachable"}

    def get_latest_analysis(
        self,
        session_id: int,
        scope: dict,
        timeout: float = 5,
    ) -> dict | None:
        url = self._base_url()
        if url is None or not self.health_check(timeout=0.5):
            return None
        try:
            response = requests.post(
                f"{url}/report/latest",
                json={
                    "session_id": session_id,
                    "data_access_scope": scope,
                },
                timeout=timeout,
            )
            payload = response.json()
            return payload.get("analysis") if response.status_code == 200 else None
        except requests.RequestException:
            return None


# Compatibility name retained while callers migrate to the business-neutral name.
LLMWorkerClient = AgentWorkerClient
