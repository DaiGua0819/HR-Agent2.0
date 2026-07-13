"""51job 真实简历下载校验与内存去重。

本阶段不接 DB；下载记忆保存在进程内存。仅接受真实附件或真实在线简历导出的
PDF/doc/docx 字节，明确拒绝聊天中的在线简历预览文字伪造 PDF。
"""

from __future__ import annotations

import asyncio
import base64

from app.browser.base import BrowserPage
from app.browser.reliable_actions import reliable_click_element
from app.platforms.job51 import selectors
from app.platforms.job51.actions_resume_close import cleanup_resume_overlays, resume_overlay_state
from app.platforms.job51.dom_scripts import (
    ANNEX_DOWNLOAD_PAYLOAD_JS,
    CLICK_ATTACHMENT_RESUME_JS,
    CLICK_ONLINE_RESUME_JS,
    CLICK_ONLINE_RESUME_SAVE_JS,
    FETCH_BLOB_BYTES_JS,
    ONLINE_RESUME_DOWNLOAD_PAYLOAD_JS,
    ONLINE_RESUME_PREVIEW_STATE_JS,
    READ_CHAT_CONTEXT_JS,
    RESUME_PAYLOAD_JS,
)
from app.platforms.job51.resume_files import (
    GLOBAL_RESUME_MEMORY,
    InMemoryResumeDownloadMemory,
    ResumeValidation,
    resume_content_hash,
    resume_download_suitability_guard,
    resume_identity_guard,
    save_resume_bytes,
    validate_resume_bytes,
)
from app.platforms.types import ResumeRequestState

ONLINE_RESUME_MESSAGE_ENTRY_SELECTOR = (
    ".im-message-item .resume-element .info-content-item, "
    ".message-item .resume-element .info-content-item, "
    ".im-message-item .resume-element, "
    ".message-item .resume-element"
)
ONLINE_RESUME_TOP_RIGHT_ENTRY_SELECTOR = (
    "#sensor_Bchat_newzxjl, "
    ".chat-user-operate .file-style.online, "
    ".chat-new-header .file-style.online, "
    ".chat-user-operate [class*='online'], "
    ".chat-new-header [class*='online']"
)
ONLINE_RESUME_LABEL = "\u5728\u7ebf\u7b80\u5386"
ATTACHMENT_REQUEST_FALLBACK_MESSAGE = "在线简历暂时无法导出，方便发一份附件简历过来吗"

__all__ = [
    "InMemoryResumeDownloadMemory",
    "ResumeValidation",
    "inspect_resume_request_state",
    "request_or_download_resume",
    "resume_content_hash",
    "resume_download_suitability_guard",
    "resume_identity_guard",
    "save_resume_bytes",
    "validate_resume_bytes",
]


async def inspect_resume_request_state(page: BrowserPage) -> ResumeRequestState:
    """检查当前 51job 会话是否已有真实简历或已求过简历。"""

    raw = await _safe_eval_dict(page, "job51.inspect_resume_request_state")
    if not raw:
        payload = await _safe_eval_dict(page, RESUME_PAYLOAD_JS)
        body = str(payload.get("summary") or await page.text())
        has_download_entry = bool(
            payload.get("hasAttachmentCard")
            or payload.get("hasOnlineResumeButton")
            or payload.get("href")
        )
        raw = {
            "hasResumeAttachment": False,
            "alreadyRequested": "已求简历" in body or "简历请求已发送" in body,
            "pendingResumeConsent": has_download_entry,
            "summary": body[-240:],
        }
    return ResumeRequestState(
        has_resume_attachment=bool(raw.get("hasResumeAttachment")),
        already_requested=bool(raw.get("alreadyRequested")),
        pending_resume_consent=bool(raw.get("pendingResumeConsent")),
        summary=str(raw.get("summary") or ""),
    )


async def request_or_download_resume(
    page: BrowserPage,
    *,
    memory: InMemoryResumeDownloadMemory | None = None,
) -> dict[str, object]:
    """优先保存真实简历；没有真实文件时回退为求简历动作。"""

    memory = memory or GLOBAL_RESUME_MEMORY
    context = await _safe_eval_dict(page, "job51.read_chat_context")
    if not context:
        context = await _safe_eval_dict(page, READ_CHAT_CONTEXT_JS)
    candidate_name = str(context.get("name") or context.get("candidate_name") or "")
    position = str(context.get("position") or context.get("appliedPosition") or "")
    payload = await _safe_eval_dict(page, "job51.resume_payload")
    if not payload:
        payload = await _safe_eval_dict(page, RESUME_PAYLOAD_JS)
    if payload.get("hasAttachmentCard") or str(payload.get("href") or "").startswith("blob:"):
        result = await _download_attachment_resume(
            page,
            candidate_name=candidate_name,
            applied_position=position,
            memory=memory,
        )
        if result.get("ok"):
            return {"requested": False, "resumeReceived": True, **result}
        if result.get("blocked"):
            if payload.get("hasOnlineResumeButton") or payload.get("previewOnly"):
                online = await _download_online_resume(
                    page,
                    candidate_name=candidate_name,
                    applied_position=position,
                    memory=memory,
                )
                if online.get("ok"):
                    return {"requested": False, "resumeReceived": True, **online}
                if online.get("blocked") and online.get("buttonFound"):
                    return {"requested": False, "downloaded": False, **online}
            return {"requested": False, "downloaded": False, **result}
        if not payload.get("previewOnly"):
            clicked, confirmed = await _request_resume_with_confirm(page)
            return {"requested": clicked, "confirmed": confirmed, "downloaded": False, **result}
    if payload.get("previewOnly"):
        online = await _download_online_resume(
            page,
            candidate_name=candidate_name,
            applied_position=position,
            memory=memory,
        )
        if online.get("ok"):
            return {"requested": False, "resumeReceived": True, **online}
        opened = online.get("opened")
        if (
            online.get("buttonFound")
            and isinstance(opened, dict)
            and opened.get("verified")
        ):
            return await _request_attachment_after_online_failure(page, online)
        clicked, confirmed = await _request_resume_with_confirm(page)
        return {
            "requested": clicked,
            "confirmed": confirmed,
            "downloaded": False,
            "reason": "preview_only_rejected",
        }
    online = await _download_online_resume(
        page,
        candidate_name=candidate_name,
        applied_position=position,
        memory=memory,
    )
    if online.get("ok"):
        return {"requested": False, "resumeReceived": True, **online}
    if online.get("blocked") and online.get("buttonFound"):
        return await _request_attachment_after_online_failure(page, online)
    content = await _generic_attachment_bytes(page, payload)
    if isinstance(content, str):
        content = content.encode("utf-8")
    if isinstance(content, bytes):
        result = _with_source_kind(save_resume_bytes(
            content,
            candidate_name=candidate_name,
            applied_position=position,
            memory=memory,
        ), "attachment")
        if result.get("ok"):
            return {"requested": False, "resumeReceived": True, **result}
        clicked, confirmed = await _request_resume_with_confirm(page)
        return {"requested": clicked, "confirmed": confirmed, "downloaded": False, **result}
    clicked, confirmed = await _request_resume_with_confirm(page)
    return {"requested": clicked, "confirmed": confirmed, "downloaded": False}


async def _download_attachment_resume(
    page: BrowserPage,
    *,
    candidate_name: str,
    applied_position: str,
    memory: InMemoryResumeDownloadMemory,
) -> dict[str, object]:
    """打开 51job 附件简历预览层，抓取底部真实 PDF blob 并保存。"""

    try:
        payload = await _safe_eval_dict(page, "job51.resume_payload")
        if not payload:
            payload = await _safe_eval_dict(page, RESUME_PAYLOAD_JS)
        content = await _payload_resume_bytes(page, payload)
        if content is not None:
            return _with_source_kind(save_resume_bytes(
                content,
                candidate_name=candidate_name,
                applied_position=applied_position,
                filename=str(payload.get("filename") or ""),
                memory=memory,
            ), "attachment")
        if not payload.get("href"):
            opened = await _open_attachment_resume_preview(page)
            if not opened:
                return {"ok": False, "blocked": True, "reason": "attachment_button_not_found"}
            payload = await _safe_eval_dict(page, ANNEX_DOWNLOAD_PAYLOAD_JS)
        href = str(payload.get("href") or "").strip()
        if not href:
            return {"ok": False, "blocked": True, "reason": "attachment_download_link_missing"}
        content = await _fetch_blob_resume_bytes(page, href)
        if content is None:
            return {"ok": False, "blocked": True, "reason": "attachment_blob_fetch_failed"}
        return _with_source_kind(save_resume_bytes(
            content,
            candidate_name=candidate_name,
            applied_position=applied_position,
            filename=str(payload.get("filename") or ""),
            memory=memory,
        ), "attachment")
    finally:
        await cleanup_resume_overlays(page)


async def _download_online_resume(
    page: BrowserPage,
    *,
    candidate_name: str,
    applied_position: str,
    memory: InMemoryResumeDownloadMemory,
) -> dict[str, object]:
    """点击右上角在线简历并下载真实导出文件。"""

    opened = await _open_online_resume_preview(page)
    if not opened.get("clicked") and not opened.get("verified"):
        return {"ok": False, "buttonFound": False, "reason": opened.get("reason", "")}
    if not opened.get("verified"):
        return {
            "ok": False,
            "blocked": True,
            "buttonFound": True,
            "reason": opened.get("reason") or "online_resume_preview_not_verified",
            "opened": opened,
        }
    try:
        preview_state = await _online_resume_preview_ready(page)
        if not preview_state.get("hasSaveButton"):
            return {
                "ok": False,
                "blocked": True,
                "buttonFound": True,
                "reason": "online_resume_export_not_available",
                "opened": opened,
                "previewState": preview_state,
            }
        payload = await _safe_eval_dict(page, "job51.online_resume_payload")
        if not payload:
            payload = await _safe_eval_dict(page, ONLINE_RESUME_DOWNLOAD_PAYLOAD_JS)
        href = str(payload.get("href") or "").strip()
        content = await _payload_resume_bytes(page, payload)
        if content is None:
            download = await _capture_online_resume_save_download(page)
            content = download.get("bytes") if isinstance(download.get("bytes"), bytes) else None
            if content is not None:
                payload = {**payload, "filename": download.get("filename") or ""}
        if content is None:
            return {
                "ok": False,
                "blocked": True,
                "buttonFound": True,
                "reason": "online_resume_download_link_missing",
                "href": href,
                "opened": opened,
                "download": download,
            }
        return _with_source_kind(save_resume_bytes(
            content,
            candidate_name=candidate_name,
            applied_position=applied_position,
            filename=str(payload.get("filename") or ""),
            memory=memory,
        ), "online_resume")
    finally:
        await cleanup_resume_overlays(page)


async def _generic_attachment_bytes(
    page: BrowserPage, payload: dict[str, object]
) -> bytes | str | None:
    """从通用真实附件来源读取字节，不带账号特判。"""

    content = payload.get("bytes")
    if content:
        return content if isinstance(content, (bytes, str)) else None
    href = str(payload.get("href") or "").strip()
    if not href or href.startswith(("blob:", "javascript:", "#")):
        return None
    fetched = await _safe_eval_dict(page, "job51.fetch_attachment_href", href)
    data = fetched.get("bytes")
    return data if isinstance(data, (bytes, str)) else None


async def _payload_resume_bytes(page: BrowserPage, payload: dict[str, object]) -> bytes | None:
    """从 payload 的 bytes/base64/href 中读取真实简历字节。"""

    content = payload.get("bytes")
    if isinstance(content, str):
        return content.encode("utf-8")
    if isinstance(content, bytes):
        return content
    encoded = str(payload.get("bytesBase64") or "")
    if encoded:
        try:
            return base64.b64decode(encoded)
        except ValueError:
            return None
    href = str(payload.get("href") or "").strip()
    if not href:
        return None
    if not href.startswith("blob:"):
        fetched = await _safe_eval_dict(page, "job51.fetch_attachment_href", href)
        data = fetched.get("bytes")
        if isinstance(data, str):
            return data.encode("utf-8")
        if isinstance(data, bytes):
            return data
    return await _fetch_blob_resume_bytes(page, href)


async def _click_request_resume(page: BrowserPage) -> bool:
    for element in await page.query_all(selectors.REQUEST_RESUME_BUTTON):
        if selectors.REQUEST_RESUME_TEXT in (await element.text()):
            result = await reliable_click_element(
                page,
                element,
                label="51job求简历",
                verify=lambda: _confirm_button_visible(page),
            )
            return bool(result.get("ok"))
    return False


async def _open_attachment_resume_preview(page: BrowserPage) -> bool:
    for element in await page.query_all(selectors.ATTACHMENT_RESUME_BUTTON):
        result = await reliable_click_element(
            page,
            element,
            label="51job附件简历",
            verify=lambda: _annex_download_visible(page),
        )
        if result.get("ok"):
            return True
    opened = await _safe_eval_dict(page, "job51.click_attachment_resume")
    if opened.get("clicked"):
        visible = await _wait_annex_download_visible(page)
        if visible.get("verified"):
            return True
    fallback = await _safe_eval_dict(page, CLICK_ATTACHMENT_RESUME_JS)
    if not fallback.get("clicked"):
        return False
    visible = await _wait_annex_download_visible(page)
    return bool(visible.get("verified"))


async def _open_online_resume_preview(page: BrowserPage) -> dict[str, object]:
    overlay_state = await resume_overlay_state(page)
    visible = await _online_resume_preview_ready(page)
    cleanup: dict[str, object] = {"closed": 0, "actions": [], "remaining": []}
    if overlay_state.get("remaining") or visible.get("verified"):
        cleanup = await cleanup_resume_overlays(page)
    if cleanup.get("remaining"):
        return {
            "clicked": False,
            "verified": False,
            "reason": "stale_resume_overlay_not_closed",
            "cleanup": cleanup,
        }
    opened = await _open_online_resume_preview_from_entries(page)
    return {**opened, "cleanup": cleanup}


async def _open_online_resume_preview_from_entries(page: BrowserPage) -> dict[str, object]:
    message_card = await _trusted_click_online_resume_entry(
        page,
        ONLINE_RESUME_MESSAGE_ENTRY_SELECTOR,
        source="message_card_online_resume_trusted",
        label="51job online resume message card",
        strict_label=True,
    )
    if message_card.get("verified"):
        return message_card

    top_right = await _trusted_click_online_resume_entry(
        page,
        ONLINE_RESUME_TOP_RIGHT_ENTRY_SELECTOR,
        source="top_right_online_resume_trusted",
        label="51job online resume top right",
        strict_label=False,
    )
    if top_right.get("verified"):
        return top_right

    legacy = await _safe_eval_dict(page, "job51.click_online_resume")
    if not legacy:
        legacy = await _safe_eval_dict(page, CLICK_ONLINE_RESUME_JS)
    if not legacy.get("clicked"):
        return _best_online_resume_open_failure(message_card, top_right, legacy)
    await asyncio.sleep(1)
    visible = await _online_resume_preview_ready(page)
    return {
        **legacy,
        "verified": bool(visible.get("verified")),
        "reason": "" if visible.get("verified") else visible.get("reason", ""),
        "source": legacy.get("source") or "legacy_dom_online_resume",
    }


async def _trusted_click_online_resume_entry(
    page: BrowserPage,
    selector: str,
    *,
    source: str,
    label: str,
    strict_label: bool,
) -> dict[str, object]:
    for element in await page.query_all(selector):
        text = " ".join((await element.text()).split())
        element_id = str(await element.attr("id") or "")
        element_class = str(await element.attr("class") or "")
        identity = f"{text} {element_id} {element_class}"
        if strict_label and ONLINE_RESUME_LABEL not in identity:
            continue
        result = await reliable_click_element(
            page,
            element,
            label=label,
            verify=lambda: _online_resume_preview_ready(page),
        )
        if result.get("ok"):
            return {
                "clicked": True,
                "verified": True,
                "source": source,
                "label": text or element_id or element_class,
                "action": result,
            }
        return {
            "clicked": True,
            "verified": False,
            "source": source,
            "label": text or element_id or element_class,
            "reason": result.get("reason") or "online_resume_preview_not_verified",
            "action": result,
        }
    return {
        "clicked": False,
        "verified": False,
        "source": source,
        "reason": "online_resume_entry_not_found",
    }


async def _capture_online_resume_save_download(page: BrowserPage) -> dict[str, object]:
    """点击在线简历右上角存储卡图标并捕获浏览器下载。"""

    try:
        result = await page.click_and_download(
            CLICK_ONLINE_RESUME_SAVE_JS,
            timeout_ms=30000,
        )
        await asyncio.sleep(1)
    except Exception as error:
        return {
            "ok": False,
            "reason": "download_api_unavailable",
            "error": str(error),
        }
    return result if isinstance(result, dict) else {"ok": False, "reason": "bad_download_result"}


async def _fetch_blob_resume_bytes(page: BrowserPage, href: str) -> bytes | None:
    fetched = await _safe_eval_dict(page, FETCH_BLOB_BYTES_JS, href)
    encoded = str(fetched.get("bytesBase64") or "")
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded)
    except ValueError:
        return None


async def _annex_download_visible(page: BrowserPage) -> dict[str, object]:
    payload = await _safe_eval_dict(page, ANNEX_DOWNLOAD_PAYLOAD_JS)
    return {
        "verified": bool(payload.get("href")),
        "reason": "" if payload.get("href") else "annex_download_link_missing",
    }


async def _wait_annex_download_visible(
    page: BrowserPage,
    *,
    timeout_ms: int = 5000,
    interval_ms: int = 150,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + max(timeout_ms, 0) / 1000
    last = {"verified": False, "reason": "annex_download_link_missing"}
    while True:
        last = await _annex_download_visible(page)
        if last.get("verified") or asyncio.get_running_loop().time() >= deadline:
            return last
        await asyncio.sleep(max(interval_ms, 0) / 1000)


async def _online_resume_download_visible(page: BrowserPage) -> dict[str, object]:
    payload = await _safe_eval_dict(page, "job51.online_resume_payload")
    if not payload:
        payload = await _safe_eval_dict(page, ONLINE_RESUME_DOWNLOAD_PAYLOAD_JS)
    verified = bool(payload.get("href") or payload.get("bytes") or payload.get("bytesBase64"))
    return {
        "verified": verified,
        "reason": "" if verified else "online_resume_download_link_missing",
    }


async def _online_resume_preview_ready(page: BrowserPage) -> dict[str, object]:
    state = await _safe_eval_dict(page, "job51.online_resume_preview_state")
    if not state:
        state = await _safe_eval_dict(page, ONLINE_RESUME_PREVIEW_STATE_JS)
    if state.get("verified"):
        return state
    download = await _online_resume_download_visible(page)
    if download.get("verified"):
        return download
    return state or download


def _best_online_resume_open_failure(
    *results: dict[str, object],
) -> dict[str, object]:
    for result in results:
        if result.get("clicked"):
            return {
                "clicked": True,
                "verified": False,
                "source": result.get("source") or "",
                "reason": result.get("reason") or "online_resume_preview_not_verified",
            }
    for result in results:
        if result:
            return {
                "clicked": False,
                "verified": False,
                "source": result.get("source") or "",
                "reason": result.get("reason") or "online_resume_button_not_found",
            }
    return {"clicked": False, "verified": False, "reason": "online_resume_button_not_found"}


async def _click_request_resume_confirm(page: BrowserPage) -> bool:
    for element in await page.query_all(selectors.REQUEST_RESUME_CONFIRM_BUTTON):
        label = await element.text()
        if any(text in label for text in selectors.REQUEST_RESUME_CONFIRM_TEXTS):
            result = await reliable_click_element(page, element, label="51job求简历确认")
            return bool(result.get("ok"))
    return False


async def _request_resume_with_confirm(page: BrowserPage) -> tuple[bool, bool]:
    clicked = await _click_request_resume(page)
    if not clicked:
        return False, False
    confirmed = await _click_request_resume_confirm(page)
    return True, confirmed


async def _request_attachment_after_online_failure(
    page: BrowserPage,
    online_failure: dict[str, object],
) -> dict[str, object]:
    """Close an unusable online preview and request an attachment resume instead."""

    await cleanup_resume_overlays(page)
    clicked, confirmed = await _request_resume_with_confirm(page)
    return {
        "requested": clicked,
        "confirmed": confirmed,
        "downloaded": False,
        "reason": (
            "online_resume_not_exportable_attachment_requested"
            if clicked
            else "online_resume_not_exportable_attachment_request_unavailable"
        ),
        "needsAttachmentRequest": not clicked,
        "attachmentRequestMessage": ATTACHMENT_REQUEST_FALLBACK_MESSAGE,
        "onlineResumeFailure": online_failure,
    }


async def _confirm_button_visible(page: BrowserPage) -> dict[str, object]:
    for element in await page.query_all(selectors.REQUEST_RESUME_CONFIRM_BUTTON):
        label = await element.text()
        if any(text in label for text in selectors.REQUEST_RESUME_CONFIRM_TEXTS):
            return {"verified": True}
    return {"verified": False, "reason": "confirm_not_visible"}


def _with_source_kind(result: dict[str, object], source_kind: str) -> dict[str, object]:
    if result.get("ok"):
        return {**result, "sourceKind": source_kind}
    return result


async def _safe_eval_dict(
    page: BrowserPage, script: str, arg: object | None = None
) -> dict[str, object]:
    try:
        value = await page.eval_js(script, arg)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}
