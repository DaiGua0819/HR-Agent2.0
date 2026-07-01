"""生产 AI 基础条件话术配置回归测试。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.agent.rules import load_chat_rules
from app.agent.runner import ConversationRunner
from app.browser.fake_page import FakePage
from app.core.constants import Platform
from app.platforms.boss.adapter import BossAdapter
from app.platforms.job51.adapter import Job51Adapter
from app.platforms.zhilian.adapter import ZhilianAdapter

AI_BASIC_PHRASE = (
    "我先介绍下基本情况，日薪150，偶尔加班，加班1.5倍薪资，单休，需要线下工作，"
    "并且最少实习六个月，如果是应届生或者已经毕业的试用期时间需要六个月，"
    "具体薪资需要面试的时候确定，工作地点都能接受吗。"
)


@pytest.mark.parametrize(
    ("platform", "adapter_cls", "owner"),
    [
        (Platform.BOSS, BossAdapter, "宋峰峰"),
        (Platform.ZHILIAN, ZhilianAdapter, "宋峰峰"),
        (Platform.JOB51, Job51Adapter, "宋峰峰"),
    ],
)
@pytest.mark.parametrize("position", ["AI应用开发实习生", "AI应用开发工程师"])
def test_ai_basic_phrase_is_shared_by_three_platforms(
    platform: Platform,
    adapter_cls: type[Any],
    owner: str,
    position: str,
) -> None:
    """三平台都从生产规则发送同一条 AI 基础条件话术。"""

    page = FakePage(
        conversations=[
            {
                "id": f"conv-{platform.value}-{position}",
                "name": "候选人",
                "position": position,
                "label": f"候选人 {position}",
                "latest_message": "你好",
                "unread_count": 1,
                "messages": [{"sender": "other", "text": "你好"}],
            }
        ]
    )
    adapter = adapter_cls(page, owner=owner, dry_run=False)

    state = asyncio.run(
        ConversationRunner(adapter, rules=load_chat_rules()).run_current()
    )

    assert state["next_action"] == "ask_basic_conditions"
    assert page.sent_messages == [AI_BASIC_PHRASE]
