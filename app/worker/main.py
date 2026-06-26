"""worker 应用工厂。"""

from __future__ import annotations

from app.worker.runtime import WorkerRuntime
from app.worker.server import create_worker_app


def build_worker_app(owner: str, port: int, cdp_port: int = 0, browser_backend: str = "fake"):
    """按负责人和端口创建 worker FastAPI app。"""

    runtime = WorkerRuntime(
        owner=owner,
        port=port,
        cdp_port=cdp_port,
        browser_backend=browser_backend,
    )
    return create_worker_app(runtime)
