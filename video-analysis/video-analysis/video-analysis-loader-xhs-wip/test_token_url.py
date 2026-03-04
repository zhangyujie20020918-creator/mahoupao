"""
验证带 xsec_token 的笔记 URL 是否能正常打开（不再 404）
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))

# 从 api_notes_dump.json 拿到的真实数据
NOTE_ID = "6990809b000000002800ba82"
XSEC_TOKEN = "ABO9fO6T0-WL48-JgHCQwnfFy7Y8nz0_95m1StHALbGYY="
TEST_URL = f"https://www.xiaohongshu.com/explore/{NOTE_ID}?xsec_token={XSEC_TOKEN}&xsec_source=pc_user"

VIDEO_CDN_PATTERNS = ["sns-video", "xhs-video"]


async def main():
    print(f"测试 URL: {TEST_URL}")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        video_url = None

        async def handle_response(response):
            nonlocal video_url
            if video_url:
                return
            ct = response.headers.get("content-type", "")
            u = response.url
            if "video" in ct or any(p in u.lower() for p in VIDEO_CDN_PATTERNS):
                video_url = u
                print(f"  [拦截视频] {ct} | {u[:100]}")

        page.on("response", handle_response)
        await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=20000)
        actual_url = page.url
        print(f"  实际URL: {actual_url[:120]}")

        if "404" in actual_url:
            print("  → 404！Token 无效")
        else:
            print("  → 页面正常加载")
            try:
                await page.wait_for_selector("video", timeout=10000)
                print("  → 检测到 <video> 元素 ✓")
            except Exception:
                print("  → 无 <video> 元素（图片笔记）")

            if video_url:
                print(f"  → 拦截到视频 URL ✓")
            else:
                print("  → 未拦截到视频 URL")

        page.remove_listener("response", handle_response)
        await context.close()


asyncio.run(main())
