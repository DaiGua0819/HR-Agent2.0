"""浏览器页面抽象。

平台动作层只依赖这里定义的最小接口，避免把 Playwright Locator 细节泄漏给
agent、tools 或测试。真实页面和假页面都实现这组方法。
"""

from __future__ import annotations

from typing import Any, Protocol


class BrowserElement(Protocol):
    """页面元素的最小可操作接口。"""

    async def click(self, timeout_ms: int | None = None) -> None:
        """点击当前元素。"""

    async def fill(self, value: str, timeout_ms: int | None = None) -> None:
        """向输入元素填入文本。"""

    async def text(self) -> str:
        """读取元素可见文本。"""

    async def attr(self, name: str) -> str | None:
        """读取元素属性。"""


class BrowserPage(Protocol):
    """平台动作函数需要的页面接口。"""

    async def goto(self, url: str) -> None:
        """打开 URL。"""

    async def query(self, selector: str) -> BrowserElement | None:
        """查找第一个匹配元素。"""

    async def query_all(self, selector: str) -> list[BrowserElement]:
        """查找所有匹配元素。"""

    async def click(self, selector: str, timeout_ms: int | None = None) -> bool:
        """点击第一个匹配元素，返回是否点击成功。"""

    async def fill(self, selector: str, value: str, timeout_ms: int | None = None) -> bool:
        """填入第一个匹配输入元素，返回是否成功。"""

    async def text(self, selector: str | None = None) -> str:
        """读取指定元素或页面正文文本。"""

    async def eval_js(self, script: str, arg: Any | None = None) -> Any:
        """执行页面脚本；假页面可按脚本名返回预设状态。"""

    async def click_and_download(
        self,
        script: str,
        arg: Any | None = None,
        timeout_ms: int = 15000,
    ) -> dict[str, Any]:
        """执行点击脚本并捕获浏览器下载。"""

    async def wait_for(self, selector: str, timeout_ms: int = 5000) -> bool:
        """等待选择器出现。"""
