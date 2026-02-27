"""Playwright 截图工具 — 截取 Web 页面截图"""

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)


async def take_screenshot(
    url: str,
    save_path: str | Path,
    width: int = 1280,
    height: int = 800,
    wait_ms: int = 2000,
    full_page: bool = True,
) -> bytes | None:
    """
    截取网页截图，返回 PNG 字节。
    如果 Playwright 不可用则返回 None。
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        log.warning("Playwright 未安装，跳过截图")
        return None

    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": width, "height": height})
            await page.goto(url, wait_until="networkidle", timeout=15000)
            if wait_ms > 0:
                await asyncio.sleep(wait_ms / 1000)
            png_bytes = await page.screenshot(path=str(save_path), full_page=full_page)
            await browser.close()
            log.info("截图已保存: %s", save_path)
            return png_bytes
    except Exception:
        log.exception("截图失败: %s", url)
        return None


async def screenshot_project(
    project_dir: Path,
    port: int = 5000,
) -> bytes | None:
    """尝试截取项目的 Web 页面（localhost:port）"""
    url = f"http://localhost:{port}"
    save_path = project_dir / "docs" / "screenshot.png"
    return await take_screenshot(url, save_path)
