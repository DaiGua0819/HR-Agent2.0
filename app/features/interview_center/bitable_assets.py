"""飞书多维表资产兼容入口。"""

from __future__ import annotations

from app.features.interview_center.feishu.bitable import FeishuBitableClient


async def upload_bitable_asset(file_path: str) -> str:
    """上传图片或文件到飞书多维表。真实调用由 FeishuBitableClient 封装。"""

    return await FeishuBitableClient().upload_file(file_path)
