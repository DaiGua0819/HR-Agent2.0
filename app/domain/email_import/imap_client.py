"""IMAP 邮件客户端接口。

真实 IMAP 连接留到最后阶段；当前文件定义可 mock 协议和一个默认空实现，保证测试与
控制面启动不依赖邮箱账号。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class EmailAttachment:
    """邮件附件。"""

    file_name: str
    content: bytes


@dataclass(frozen=True)
class EmailMessage:
    """候选简历邮件。"""

    subject: str
    sender: str
    body: str = ""
    attachments: list[EmailAttachment] = field(default_factory=list)


class ImapClientProtocol(Protocol):
    """可 mock 的 IMAP 客户端协议。"""

    async def fetch_resume_messages(self) -> list[EmailMessage]:
        """读取未处理简历邮件。"""


class ImapResumeClient:
    """默认空实现；真实 IMAP 下载留到最后阶段。"""

    async def fetch_resume_messages(self) -> list[EmailMessage]:
        """返回空邮件列表，避免 Phase 5 依赖外部邮箱。"""

        return []

    async def fetch_resume_attachments(self) -> list[bytes]:
        """兼容旧 stub 的附件下载入口。"""

        messages = await self.fetch_resume_messages()
        return [attachment.content for message in messages for attachment in message.attachments]
