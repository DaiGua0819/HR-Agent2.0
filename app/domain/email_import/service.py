"""邮箱简历导入服务。

本阶段解析可 mock IMAP 客户端返回的邮件和附件，生成内存导入结果；不连接真实邮箱，
也不写真实数据库。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.text import clean_text
from app.domain.batch.service import parse_resume_text
from app.domain.email_import.imap_client import EmailMessage, ImapClientProtocol, ImapResumeClient


@dataclass
class EmailImportService:
    """邮箱导入用例。"""

    client: ImapClientProtocol = field(default_factory=ImapResumeClient)
    auto_enabled: bool = False

    async def import_resumes(self) -> dict[str, Any]:
        """导入邮件中的简历附件和正文。"""

        messages = await self.client.fetch_resume_messages()
        imported: list[dict[str, Any]] = []
        skipped = 0
        for message in messages:
            parsed = parse_email_message(message)
            if parsed:
                imported.extend(parsed)
            else:
                skipped += 1
        return {"imported": len(imported), "skipped": skipped, "items": imported}

    def auto_status(self) -> dict[str, bool]:
        """返回自动检测状态。"""

        return {"enabled": self.auto_enabled}

    def set_auto_enabled(self, enabled: bool) -> dict[str, bool]:
        """切换自动检测开关。"""

        self.auto_enabled = enabled
        return self.auto_status()


GLOBAL_EMAIL_IMPORT_SERVICE = EmailImportService()


def parse_email_message(message: EmailMessage) -> list[dict[str, Any]]:
    """解析单封邮件，附件优先，正文兜底。"""

    results: list[dict[str, Any]] = []
    for attachment in message.attachments:
        text = _decode_attachment(attachment.content)
        if not text:
            continue
        payload = parse_resume_text(text, file_name=attachment.file_name)
        payload["source"] = "email"
        payload["emailSubject"] = clean_text(message.subject)
        payload["emailSender"] = clean_text(message.sender)
        results.append(payload)
    if not results and clean_text(message.body):
        payload = parse_resume_text(message.body, file_name=message.subject)
        payload["source"] = "email"
        payload["emailSubject"] = clean_text(message.subject)
        payload["emailSender"] = clean_text(message.sender)
        results.append(payload)
    return results


async def import_resumes_from_email() -> dict[str, Any]:
    """兼容旧 stub 的邮箱导入入口。"""

    return await GLOBAL_EMAIL_IMPORT_SERVICE.import_resumes()


def _decode_attachment(content: bytes) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""
