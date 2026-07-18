"""自动化任务路由。

控制面 Web 层只负责参数校验和转发；实际浏览器动作由对应负责人 worker 执行。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.control_plane.dispatcher import Dispatcher
from app.core.constants import Platform

router = APIRouter(prefix="/automation", tags=["automation"])


@router.post("/process-all")
async def process_all(request: Request) -> dict[str, object]:
    """按 run_order 串行处理全部平台账号。"""

    dispatcher: Dispatcher = request.app.state.dispatcher
    return await dispatcher.process_all()


@router.post("/{platform}/process-messages")
async def process_messages(
    platform: Platform,
    owner: str,
    request: Request,
) -> dict[str, object]:
    """转发“处理某平台未读消息”到负责人 worker。"""

    dispatcher: Dispatcher = request.app.state.dispatcher
    result = await dispatcher.dispatch_process_unread(
        owner,
        platform,
        exclude_ids={
            str(item)
            for item in request.query_params.getlist("exclude_conversation_id")
            if str(item)
        },
    )
    return {"accepted": True, "owner": result.owner, "platform": platform.value, **result.result}


@router.post("/{platform}/proactive-contact")
async def proactive_contact(
    platform: Platform,
    owner: str,
    request: Request,
    payload: dict[str, Any] | None = None,
) -> dict[str, object]:
    """转发主动联系任务到负责人 worker。"""

    dispatcher: Dispatcher = request.app.state.dispatcher
    result = await dispatcher.proactive_contact(owner, platform, payload)
    return {"accepted": True, "owner": result.owner, "platform": platform.value, **result.result}


@router.post("/{platform}/pause")
async def pause(platform: Platform, owner: str, request: Request) -> dict[str, object]:
    """暂停指定负责人平台自动化。"""

    dispatcher: Dispatcher = request.app.state.dispatcher
    result = await dispatcher.pause(owner, platform)
    return {"accepted": True, "owner": result.owner, "platform": platform.value, **result.result}
