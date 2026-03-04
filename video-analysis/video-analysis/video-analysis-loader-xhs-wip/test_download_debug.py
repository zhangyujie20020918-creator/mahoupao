"""
诊断：拦截视频 URL 并检查 aiohttp 响应头
"""

import asyncio
import os
from pathlib import Path
import aiohttp
from playwright.async_api import async_playwright

PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))
TARGET_URL = "https://www.xiaohongshu.com/discovery/item/6992e3c0000000001a036f39?source=webshare&xhsshare=pc_web&xsec_token=ABMQ3hzl5z5i4owKJf1TNvRxVpZzz7aGRT-bTvY9NPAOE=&xsec_source=pc_share"
VIDEO_CDN_PATTERNS = ["sns-video", "xhs-video"]


async def main():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    print("步骤1: 浏览器拦截视频 URL...")
    video_url = None

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        async def handle_response(response):
            nonlocal video_url
            if video_url:
                return
            url = response.url
            ct = response.headers.get("content-type", "")
            if "video" in ct or any(p in url.lower() for p in VIDEO_CDN_PATTERNS):
                video_url = url
                print(f"  [拦截到] {url}")
                print(f"           Content-Type={ct}  Content-Length={response.headers.get('content-length','未知')}")
                print(f"           请求 Range 头={response.request.headers.get('range', '无')}")

        page.on("response", handle_response)
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("video", timeout=15000)
        except Exception:
            pass
        if not video_url:
            await asyncio.sleep(3)

        await context.close()

    if not video_url:
        print("未捕获到视频 URL")
        return

    print(f"\n捕获到的视频 URL：\n  {video_url}\n")

    async with aiohttp.ClientSession() as s:
        base_headers = {
            "Referer": "https://www.xiaohongshu.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }

        print("步骤2: 不带 Range 头")
        async with s.get(video_url, headers=base_headers) as r:
            print(f"  Status={r.status}  Content-Length={r.headers.get('content-length','未知')}  Content-Range={r.headers.get('content-range','无')}")
            print(f"  实际 URL: {r.url}")

        print("\n步骤3: 带 Range: bytes=0-")
        async with s.get(video_url, headers={**base_headers, "Range": "bytes=0-"}) as r:
            print(f"  Status={r.status}  Content-Length={r.headers.get('content-length','未知')}  Content-Range={r.headers.get('content-range','无')}")
            print(f"  实际 URL: {r.url}")


asyncio.run(main())
