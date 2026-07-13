"""Hard timeout coverage for unresponsive CloakBrowser CDP operations."""

from __future__ import annotations

import asyncio

import pytest
from app.browser import playwright_cdp
from app.browser.playwright_cdp import PlaywrightCDPPage, PlaywrightElement


def test_playwright_element_click_has_python_side_hard_timeout(monkeypatch) -> None:
    """A stalled CDP click must not outlive the requested Playwright timeout."""

    monkeypatch.setattr(playwright_cdp, "CDP_TIMEOUT_GRACE_SECONDS", 0.01)
    element = PlaywrightElement(_HangingLocator())

    with pytest.raises(TimeoutError):
        asyncio.run(element.click(timeout_ms=1))


def test_playwright_page_evaluate_has_python_side_hard_timeout(monkeypatch) -> None:
    """A stalled page.evaluate call must return control to the platform runner."""

    monkeypatch.setattr(playwright_cdp, "CDP_EVAL_TIMEOUT_SECONDS", 0.01)
    page = PlaywrightCDPPage(_HangingPage())

    with pytest.raises(TimeoutError):
        asyncio.run(page.eval_js("() => true"))


class _HangingLocator:
    async def click(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        _ = kwargs
        await asyncio.Event().wait()


class _HangingPage:
    async def evaluate(self, script: str, arg=None):  # type: ignore[no-untyped-def]
        _ = script, arg
        await asyncio.Event().wait()
