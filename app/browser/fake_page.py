"""测试用假页面。

FakePage 用结构化会话数据模拟智联页面，不依赖真实浏览器、登录态或数据库。
它同时记录点击、发送和求简历动作，方便测试断言 agent 流程。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeElement:
    """FakePage 返回的元素。"""

    page: FakePage
    selector: str
    text_value: str = ""
    attrs: dict[str, str] = field(default_factory=dict)

    async def click(self) -> None:
        self.page.clicks.append(self.selector)
        await self.page.handle_element_click(self)

    async def fill(self, value: str) -> None:
        self.page.fills.append((self.selector, value))
        self.page.input_text = value

    async def text(self) -> str:
        return self.text_value

    async def attr(self, name: str) -> str | None:
        return self.attrs.get(name)


@dataclass
class FakePage:
    """结构化脚本驱动的浏览器页面。"""

    conversations: list[dict[str, Any]] = field(default_factory=list)
    recommend_candidates: list[dict[str, Any]] = field(default_factory=list)
    url: str = ""
    body_text: str = ""
    selected_index: int | None = None
    selected_recommend_index: int | None = None
    selected_recommend_position: str = ""
    recommend_traditional_mode: bool = True
    input_text: str = ""
    clicks: list[str] = field(default_factory=list)
    fills: list[tuple[str, str]] = field(default_factory=list)
    sent_messages: list[str] = field(default_factory=list)
    resume_requests: int = 0
    proactive_greets: list[str] = field(default_factory=list)
    unread_selected: bool = False
    all_positions_selected: bool = False

    async def goto(self, url: str) -> None:
        self.url = url

    async def query(self, selector: str) -> FakeElement | None:
        items = await self.query_all(selector)
        return items[0] if items else None

    async def query_all(self, selector: str) -> list[FakeElement]:
        if (
            ".im-session-item__box" in selector
            or ".user-list-item" in selector
            or "#conversation-list .list-item" in selector
        ):
            return [
                self._conversation_element(index, item)
                for index, item in enumerate(self.conversations)
            ]
        if "#sensor_talentcommunicate" in selector or "#sensor_recommand_menu" in selector:
            return [FakeElement(self, selector, "人才沟通")]
        if "filter-item" in selector or "ui-tab-item" in selector:
            return [FakeElement(self, selector, "未读")]
        if "unread-checkbox" in selector:
            return [FakeElement(self, selector, "未读")]
        if "btn-send" in selector or "new-send-button" in selector or "class*='send'" in selector:
            return [FakeElement(self, selector, "发送")]
        if (
            "el-message-box__btns" in selector
            or "el-dialog__footer" in selector
            or "km-modal--open" in selector
            or "km-dialog" in selector
            or "im-dialog" in selector
        ):
            return [FakeElement(self, selector, "确定")]
        if "btn-greet" in selector:
            if self.current_recommend_candidate():
                return [FakeElement(self, selector, "打招呼")]
            return []
        if "tm_button" in selector:
            if self.current_recommend_candidate():
                return [FakeElement(self, selector, "立即Hi聊")]
            return []
        if ".candidate-card-wrap" in selector:
            return [
                self._recommend_element(index, item)
                for index, item in enumerate(self.recommend_candidates)
            ]
        if "resume-card" in selector:
            return [
                self._recommend_element(index, item)
                for index, item in enumerate(self.recommend_candidates)
            ]
        if "job-selecter-wrap" in selector:
            return [FakeElement(self, selector, self.selected_recommend_position or "全部职位")]
        if "position-menu" in selector or "menu-item-all" in selector:
            return [FakeElement(self, selector, self.selected_recommend_position or "全部岗位")]
        if "ai-mode-switch-active" in selector:
            if self.recommend_traditional_mode:
                return []
            return [FakeElement(self, selector, "AI淘金")]
        if "ai-mode-switch" in selector:
            return [FakeElement(self, selector, "AI淘金")]
        if "btn-request-resume" in selector or "toolbar" in selector or "chat-op" in selector:
            return [
                FakeElement(self, selector, "求简历"),
                FakeElement(self, selector, "不合适"),
            ]
        if "boss-dialog" in selector or "dialog-wrap.active" in selector:
            return [FakeElement(self, selector, "确认")]
        if "operate-item" in selector:
            return [FakeElement(self, selector, "求简历")]
        if "textarea" in selector or "drop-area" in selector:
            return [FakeElement(self, selector, self.input_text)]
        if "要附件简历" in selector or "im-ask-for-wx" in selector:
            return [FakeElement(self, selector, "要附件简历")]
        if "message-item.mine" in selector or "im-message" in selector:
            return [
                FakeElement(self, selector, message.get("text", ""))
                for message in self.current_messages()
            ]
        if "new-shortcut-resume__modal" in selector:
            return [FakeElement(self, selector, self.body_text)]
        return []

    async def click(self, selector: str) -> bool:
        element = await self.query(selector)
        if element is None:
            return False
        await element.click()
        return True

    async def fill(self, selector: str, value: str) -> bool:
        element = await self.query(selector)
        if element is None:
            return False
        await element.fill(value)
        return True

    async def text(self, selector: str | None = None) -> str:
        if selector is None:
            return self.body_text
        element = await self.query(selector)
        return await element.text() if element else ""

    async def eval_js(self, script: str, arg: Any | None = None) -> Any:
        if script == "zhilian.read_chat_context":
            return self.current_conversation()
        if script == "boss.read_chat_context":
            return self.current_conversation()
        if script == "job51.read_chat_context":
            return self.current_conversation()
        if script == "job51.opened_candidate_state":
            expected = arg if isinstance(arg, dict) else {}
            current = self.current_conversation()
            expected_label = str(expected.get("label") or "")
            expected_name = str(expected.get("name") or "")
            expected_position = str(expected.get("position") or "")
            actual_label = str(current.get("label") or "")
            actual_name = str(current.get("name") or "")
            actual_position = str(current.get("position") or current.get("appliedPosition") or "")
            opened = bool(
                expected_label and expected_label == actual_label
                or expected_name and expected_name == actual_name
                or expected_position and expected_position == actual_position
            )
            return {
                "opened": opened,
                "chatReady": True,
                "reason": "" if opened else "candidate_identity_mismatch",
            }
        if script == "zhilian.inspect_resume_request_state":
            convo = self.current_conversation()
            return {
                "hasResumeAttachment": bool(convo.get("has_resume_attachment")),
                "alreadyRequested": bool(convo.get("resume_requested")),
                "summary": convo.get("resume_summary", ""),
                "source": "fake_page",
            }
        if script == "boss.inspect_resume_request_state":
            convo = self.current_conversation()
            return {
                "hasResumeAttachment": bool(convo.get("has_resume_attachment")),
                "alreadyRequested": bool(convo.get("resume_requested")),
                "summary": convo.get("resume_summary", ""),
                "source": "fake_page",
            }
        if script == "job51.inspect_resume_request_state":
            convo = self.current_conversation()
            return {
                "hasResumeAttachment": bool(
                    convo.get("has_resume_attachment")
                    or convo.get("resume_bytes")
                    or convo.get("preview_only")
                ),
                "alreadyRequested": bool(convo.get("resume_requested")),
                "summary": convo.get("resume_summary", ""),
                "source": "fake_page",
            }
        if script == "zhilian.verify_sent":
            expected = str(arg or "")
            return {"verified": bool(self.sent_messages and self.sent_messages[-1] == expected)}
        if script == "boss.verify_sent":
            expected = str(arg or "")
            return {"verified": bool(self.sent_messages and self.sent_messages[-1] == expected)}
        if script == "job51.verify_sent":
            expected = str(arg or "")
            return {"verified": bool(self.sent_messages and self.sent_messages[-1] == expected)}
        if script == "job51.resume_payload":
            convo = self.current_conversation()
            return {
                "bytes": convo.get("resume_bytes"),
                "href": convo.get("resume_href"),
                "previewOnly": bool(convo.get("preview_only")),
            }
        if script == "job51.fetch_attachment_href":
            convo = self.current_conversation()
            if arg and str(arg) == str(convo.get("resume_href") or ""):
                return {"ok": True, "bytes": convo.get("resume_href_bytes")}
            return {"ok": False, "reason": "href_not_found"}
        if script == "boss.recommend_summary":
            return {"selectedPosition": self.selected_recommend_position}
        if script == "boss.select_recommend_position":
            self.selected_recommend_position = str(arg or "")
            return {"selected": True, "selectedPosition": self.selected_recommend_position}
        if script == "boss.recommend_cards":
            return [
                self._recommend_payload(index, item)
                for index, item in enumerate(self.recommend_candidates)
            ]
        if script == "job51.recommend_cards":
            return [
                self._recommend_payload(index, item)
                for index, item in enumerate(self.recommend_candidates)
            ]
        if script == "boss.open_recommend_card":
            self.selected_recommend_index = int(arg or 0)
            return {"opened": True, "index": self.selected_recommend_index}
        if script == "boss.read_recommend_resume_dialog":
            item = self.current_recommend_candidate()
            return {
                "text": "\n".join(
                    str(value or "")
                    for value in (
                        item.get("resume_text") if item else "",
                        item.get("detail_text") if item else "",
                    )
                ),
                "candidate": item or {},
            }
        if script == "boss.close_recommend_resume_dialog":
            self.selected_recommend_index = None
            return {"closed": True}
        if script == "job51.recommend_mode_state":
            return {
                "traditional": self.recommend_traditional_mode,
                "aiGold": not self.recommend_traditional_mode,
            }
        if script == "job51.set_recommend_traditional_mode":
            self.recommend_traditional_mode = bool(arg)
            return {"traditional": self.recommend_traditional_mode}
        if script == "job51.select_recommend_position":
            self.selected_recommend_position = str(arg or "")
            return {"selected": True, "label": self.selected_recommend_position}
        if script == "job51.select_recommend_card":
            self.selected_recommend_index = int(arg or 0)
            return {"selected": True, "index": self.selected_recommend_index}
        if script == "job51.probe_recommend_candidate_detail":
            self.selected_recommend_index = int(arg or 0)
            item = self.current_recommend_candidate() or {}
            return {
                "opened": True,
                "text": "\n".join(
                    str(value or "")
                    for value in (item.get("resume_text"), item.get("detail_text"))
                ),
            }
        if script == "job51.scroll_recommend_cards":
            return {"scrolled": True}
        return None

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        _ = timeout_ms
        return bool(await self.query(selector))

    def current_conversation(self) -> dict[str, Any]:
        if self.selected_index is None and self.conversations:
            self.selected_index = 0
        if self.selected_index is None:
            return {}
        return self.conversations[self.selected_index]

    def current_messages(self) -> list[dict[str, Any]]:
        return list(self.current_conversation().get("messages") or [])

    def current_recommend_candidate(self) -> dict[str, Any] | None:
        if self.selected_recommend_index is None:
            return None
        if self.selected_recommend_index >= len(self.recommend_candidates):
            return None
        return self.recommend_candidates[self.selected_recommend_index]

    async def handle_element_click(self, element: FakeElement) -> None:
        if element.selector.startswith("conversation:"):
            self.selected_index = int(element.attrs["index"])
        elif element.selector.startswith("recommend:"):
            self.selected_recommend_index = int(element.attrs["index"])
        elif "未读" in element.text_value:
            self.unread_selected = True
        elif "全部职位" in element.text_value:
            self.all_positions_selected = True
        elif "AI淘金" in element.text_value:
            self.recommend_traditional_mode = True
        elif (
            "要附件简历" in element.text_value
            or "求简历" in element.text_value
            or "im-ask-for-wx" in element.selector
        ):
            self.resume_requests += 1
            self.current_conversation()["resume_requested"] = True
        elif "确定" in element.text_value or "确认" in element.text_value:
            self.current_conversation()["resume_request_confirmed"] = True
        elif "打招呼" in element.text_value or "立即Hi聊" in element.text_value:
            candidate = self.current_recommend_candidate()
            if candidate:
                candidate["already_greeted"] = True
                self.proactive_greets.append(str(candidate.get("name") or ""))
            else:
                self.proactive_greets.append(self.current_conversation().get("name", ""))

    def append_sent_message(self, text: str) -> None:
        self.sent_messages.append(text)
        self.current_conversation().setdefault("messages", []).append(
            {"sender": "me", "text": text}
        )

    def _recommend_element(self, index: int, item: dict[str, Any]) -> FakeElement:
        return FakeElement(
            self,
            f"recommend:{index}",
            str(item.get("text") or item.get("card_text") or item.get("name") or ""),
            {"index": str(index), "name": str(item.get("name") or "")},
        )

    def _recommend_payload(self, index: int, item: dict[str, Any]) -> dict[str, Any]:
        text = "\n".join(
            str(value or "")
            for value in (
                item.get("text"),
                item.get("card_text"),
                item.get("name"),
                item.get("position"),
            )
        )
        return {
            "index": index,
            "name": str(item.get("name") or ""),
            "text": text,
            "similar": bool(item.get("similar")),
            "alreadyGreeted": bool(item.get("already_greeted")),
            "viewed": bool(item.get("viewed")),
        }
        self.input_text = ""

    def _conversation_element(self, index: int, item: dict[str, Any]) -> FakeElement:
        label = item.get("label") or f"{item.get('name', '')} {item.get('position', '')}"
        return FakeElement(
            self,
            f"conversation:{index}",
            str(label),
            {
                "index": str(index),
                "id": str(item.get("id") or index),
                "name": str(item.get("name") or ""),
                "position": str(item.get("position") or ""),
                "latest": str(item.get("latest_message") or ""),
                "unread": str(item.get("unread_count") or 0),
            },
        )
