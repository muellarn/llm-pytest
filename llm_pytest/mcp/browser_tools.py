"""Playwright-based browser tools (optional dependency).

These tools require the [browser] extra to be installed:
    pip install llm-pytest[browser]

Usage:
    These functions can be imported and added to a project-specific
    MCP server that needs browser automation.
"""

from __future__ import annotations

from typing import Any

try:
    from playwright.async_api import async_playwright, Page, Browser, Playwright

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    Page = Any
    Browser = Any
    Playwright = Any


# Global state for browser instance
_playwright: Playwright | None = None
_browser: Browser | None = None
_page: Page | None = None
_console_logs: list[dict[str, Any]] = []


def check_playwright():
    """Check if Playwright is available."""
    if not HAS_PLAYWRIGHT:
        raise ImportError(
            "Playwright not installed. Install with: pip install llm-pytest[browser]"
        )


async def get_page() -> Page:
    """Get or create browser page."""
    global _playwright, _browser, _page
    check_playwright()

    if _page is None:
        _playwright = await async_playwright().start()
        _browser = await _playwright.chromium.launch(headless=True)
        _page = await _browser.new_page()

        # Set up console log listener
        _page.on("console", _handle_console)

    return _page


def _handle_console(msg):
    """Handle console messages from the browser."""
    _console_logs.append(
        {
            "type": msg.type,
            "text": msg.text,
            "location": msg.location,
        }
    )


async def navigate(url: str, wait_until: str = "load") -> dict[str, Any]:
    """Navigate to a URL.

    Args:
        url: The URL to navigate to
        wait_until: When to consider navigation complete
                   ("load", "domcontentloaded", "networkidle")

    Returns:
        Dict with navigation result
    """
    page = await get_page()
    response = await page.goto(url, wait_until=wait_until)

    return {
        "url": page.url,
        "status": response.status if response else None,
        "ok": response.ok if response else False,
    }


async def wait_for_selector(
    selector: str,
    timeout: int = 30000,
    state: str = "visible",
) -> dict[str, Any]:
    """Wait for an element to appear.

    Args:
        selector: CSS selector to wait for
        timeout: Maximum wait time in milliseconds
        state: State to wait for ("attached", "detached", "visible", "hidden")

    Returns:
        Dict with element found status
    """
    page = await get_page()
    try:
        await page.wait_for_selector(selector, timeout=timeout, state=state)
        return {"found": True, "selector": selector}
    except Exception as e:
        return {"found": False, "selector": selector, "error": str(e)}


async def evaluate_js(script: str) -> dict[str, Any]:
    """Evaluate JavaScript in the browser.

    Args:
        script: JavaScript code to execute

    Returns:
        Dict with the result
    """
    page = await get_page()
    try:
        result = await page.evaluate(script)
        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def take_screenshot(path: str = "screenshot.png", full_page: bool = False) -> dict[str, str]:
    """Take a screenshot of the current page.

    Args:
        path: File path to save the screenshot
        full_page: Whether to capture the full scrollable page

    Returns:
        Dict with the screenshot path
    """
    page = await get_page()
    await page.screenshot(path=path, full_page=full_page)
    return {"path": path}


async def get_console_logs(clear: bool = True) -> list[dict[str, Any]]:
    """Get browser console logs.

    Args:
        clear: Whether to clear the logs after returning

    Returns:
        List of console log entries
    """
    global _console_logs
    logs = _console_logs.copy()
    if clear:
        _console_logs = []
    return logs


async def click(selector: str) -> dict[str, Any]:
    """Click an element.

    Args:
        selector: CSS selector of element to click

    Returns:
        Dict with click result
    """
    page = await get_page()
    try:
        await page.click(selector)
        return {"clicked": True, "selector": selector}
    except Exception as e:
        return {"clicked": False, "selector": selector, "error": str(e)}


async def fill(selector: str, value: str) -> dict[str, Any]:
    """Fill an input field.

    Args:
        selector: CSS selector of input element
        value: Value to fill

    Returns:
        Dict with fill result
    """
    page = await get_page()
    try:
        await page.fill(selector, value)
        return {"filled": True, "selector": selector}
    except Exception as e:
        return {"filled": False, "selector": selector, "error": str(e)}


async def get_text(selector: str) -> dict[str, Any]:
    """Get text content of an element.

    Args:
        selector: CSS selector

    Returns:
        Dict with text content
    """
    page = await get_page()
    try:
        text = await page.text_content(selector)
        return {"text": text, "selector": selector}
    except Exception as e:
        return {"text": None, "selector": selector, "error": str(e)}


async def close_browser() -> dict[str, str]:
    """Close the browser.

    Returns:
        Dict confirming closure
    """
    global _playwright, _browser, _page, _console_logs

    if _page:
        await _page.close()
        _page = None

    if _browser:
        await _browser.close()
        _browser = None

    if _playwright:
        await _playwright.stop()
        _playwright = None

    _console_logs = []

    return {"status": "closed"}
