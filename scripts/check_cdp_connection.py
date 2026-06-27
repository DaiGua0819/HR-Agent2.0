"""验证 CloakBrowser CDP 连接与 BrowserPage 封装。

脚本只访问 CDP `/json/version` 和公开页面 `https://example.com`，不打开任何招聘平台。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from urllib.request import urlopen

os.environ["DRY_RUN"] = "true"

from app.browser.playwright_cdp import PlaywrightCDPPage  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析 CDP 检查参数。"""

    parser = argparse.ArgumentParser(description="检查 CloakBrowser CDP 和 BrowserPage query")
    parser.add_argument(
        "--cdp",
        default="http://127.0.0.1:9222",
        help="CDP 地址，默认 http://127.0.0.1:9222",
    )
    return parser.parse_args()


def probe_version(cdp_url: str) -> dict[str, object]:
    """读取 `/json/version` 并返回浏览器版本信息。"""

    url = f"{cdp_url.rstrip('/')}/json/version"
    with urlopen(url, timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload


async def check_playwright(cdp_url: str) -> None:
    """连接 CDP，打印上下文/标签页，并验证 BrowserPage query。"""

    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    browser = await playwright.chromium.connect_over_cdp(cdp_url)
    try:
        contexts = list(browser.contexts)
        print(f"CDP attached: contexts={len(contexts)}")
        for context_index, context in enumerate(contexts):
            pages = list(context.pages)
            print(f"context[{context_index}] pages={len(pages)}")
            for page_index, page in enumerate(pages):
                print(f"  page[{page_index}] {page.url}")

        context = contexts[0] if contexts else await browser.new_context()
        page = await context.new_page()
        wrapper = PlaywrightCDPPage(page, name="cdp-check")
        await wrapper.goto("https://example.com")
        h1 = await wrapper.query("h1")
        text = (await h1.text()).strip() if h1 else ""
        print(f"BrowserPage query h1: {'OK' if text else 'MISSING'} text={text!r}")
        await page.close()
    finally:
        await playwright.stop()


async def main_async() -> None:
    """脚本异步入口。"""

    args = parse_args()
    cdp_url = args.cdp.rstrip("/")
    print("DRY_RUN=true")
    version = probe_version(cdp_url)
    print(f"CDP version endpoint: OK {cdp_url}/json/version")
    print(f"Browser: {version.get('Browser', '')}")
    print(f"Protocol-Version: {version.get('Protocol-Version', '')}")
    await check_playwright(cdp_url)


def main() -> None:
    """脚本入口。"""

    asyncio.run(main_async())


if __name__ == "__main__":
    main()
