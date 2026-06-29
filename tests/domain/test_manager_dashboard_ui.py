"""管理者驾驶舱 API 测试。"""

from __future__ import annotations

from app.control_plane.main import create_app
from fastapi.testclient import TestClient


class FakeDashboardDispatcher:
    """测试用 dispatcher，只提供 dashboard 所需的 worker 状态。"""

    async def worker_statuses(self) -> list[dict[str, object]]:
        return [
            {
                "owner": "宋峰峰",
                "status": "ready",
                "agentReady": True,
                "browserReady": True,
                "cdpReady": True,
                "agentBusy": False,
                "browserBackend": "fake",
                "pageCount": 3,
                "dryRun": True,
            },
            {
                "owner": "和新红",
                "status": "ready",
                "agentReady": True,
                "browserReady": True,
                "cdpReady": True,
                "agentBusy": True,
                "browserBackend": "fake",
                "pageCount": 3,
                "dryRun": True,
            },
        ]


def test_dashboard_overview_returns_manager_payload() -> None:
    """首页聚合接口返回前端稳定消费的字段。"""

    app = create_app(dispatcher=FakeDashboardDispatcher())  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.get("/api/dashboard/overview")

    assert response.status_code == 200
    payload = response.json()
    keys = {item["key"] for item in payload["kpis"]}
    assert payload["date"]
    assert isinstance(payload["dryRun"], bool)
    assert {"resumeCount", "pendingReview", "decisionCount", "workerReady"} <= keys
    assert len(payload["services"]) == 2
    assert payload["services"][0]["owner"] == "宋峰峰"
    assert payload["services"][1]["status"] == "busy"
    assert {item["view"] for item in payload["quickFilters"]} >= {
        "resumes",
        "queue",
        "automation",
        "interviews",
    }
