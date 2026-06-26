"""飞书客户端兼容入口。

新代码已拆到 `features.interview_center.feishu.*`；保留本文件让旧导入路径继续可用。
"""

from __future__ import annotations

from app.features.interview_center.feishu.bitable import FeishuBitableClient


class FeishuClient(FeishuBitableClient):
    """兼容旧名称的多维表客户端。"""
