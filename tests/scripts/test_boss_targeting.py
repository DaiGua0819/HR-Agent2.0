from __future__ import annotations

import asyncio

from app.browser.fake_page import FakeElement, FakePage
from app.platforms.boss import selectors
from scripts.boss_targeting import _click_conversation_by_id, select_all_filter


class DelayedAllConversationPage(FakePage):
    def __init__(self) -> None:
        super().__init__(
            conversations=[
                {
                    "id": "_66235835-0",
                    "name": "刘倞伊",
                    "position": "企业内容运营负责人（B2B/短视频方向）",
                    "label": "刘倞伊 企业内容运营负责人（B2B/短视频方向）",
                    "messages": [{"sender": "other", "text": "你好"}],
                }
            ]
        )
        self.active_filter = "未读"
        self.row_queries = 0

    async def query_all(self, selector: str):
        if selector == selectors.MESSAGE_FILTER_OPTION:
            return [
                FakeElement(self, "filter-all", "全部"),
                FakeElement(self, "filter-unread", "未读"),
            ]
        if selector == selectors.SESSION_ITEM:
            self.row_queries += 1
            if self.row_queries == 1:
                return []
        return await super().query_all(selector)

    async def handle_element_click(self, element) -> None:
        if element.selector == "filter-all":
            self.active_filter = "全部"
            return
        await super().handle_element_click(element)

    async def eval_js(self, script: str, arg: object | None = None) -> object:
        if ".chat-message-filter-left span.active" in script:
            return self.active_filter
        return await super().eval_js(script, arg)

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        _ = selector, timeout_ms
        return self.selected_index is not None


def test_targeting_waits_for_all_filter_rows_and_matches_stable_id() -> None:
    page = DelayedAllConversationPage()

    selected = asyncio.run(select_all_filter(page))
    clicked = asyncio.run(_click_conversation_by_id(page, "_66235835-0"))

    assert selected["selected"] is True
    assert clicked is True
    assert page.selected_index == 0
    assert page.row_queries >= 2
