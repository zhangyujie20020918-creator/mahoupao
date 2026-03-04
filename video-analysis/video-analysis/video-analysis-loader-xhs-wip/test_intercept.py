"""
拦截小红书页面的所有视频相关请求，打印 URL 和文件大小
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))
TARGET_URL = "https://www.xiaohongshu.com/discovery/item/6992e3c0000000001a036f39?source=webshare&xhsshare=pc_web&xsec_token=ABMQ3hzl5z5i4owKJf1TNvRxVpZzz7aGRT-bTvY9NPAOE=&xsec_source=pc_share"

VIDEO_KEYWORDS = ["sns-video", "xhscdn.com", "xhs-video", ".mp4", "video"]


async def main():
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        captured = []  # [(url, content_type, content_length)]

        async def handle_response(response):
            url = response.url
            headers = response.headers
            content_type = headers.get("content-type", "")
            content_length = headers.get("content-length", "未知")

            url_lower = url.lower()
            is_video = "video" in content_type or any(k in url_lower for k in VIDEO_KEYWORDS)

            if is_video:
                captured.append((url, content_type, content_length))
                size_str = f"{int(content_length):,} bytes" if content_length != "未知" else "未知大小"
                print(f"[拦截] {content_type or '无content-type'} | {size_str}")
                print(f"       {url}")
                print()

        # 先注册拦截，再导航，确保不遗漏请求
        page.on("response", handle_response)

        print(f"导航到目标页面：")
        print(f"  {TARGET_URL}")
        print()
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=30000)
        print(f"页面加载完成，当前 URL：{page.url}")
        print()

        print("等待 <video> 元素出现（最多 20 秒）...")
        try:
            await page.wait_for_selector("video", timeout=20000)
            print("检测到 <video> 元素，开始捕获视频请求")
        except Exception:
            print("未检测到 <video> 元素（可能是图片笔记或加载失败）")
        print()

        # 额外等待，确保延迟发起的视频请求也能被拦截
        print("再等 5 秒捕获延迟请求...")
        await asyncio.sleep(5)

        # 汇总输出
        print("=" * 60)
        print(f"共拦截到 {len(captured)} 个视频相关请求：")
        print("=" * 60)
        for i, (url, ct, cl) in enumerate(captured, 1):
            size_str = f"{int(cl):,} bytes" if cl != "未知" else "未知大小"
            print(f"{i}. [{size_str}] {ct}")
            print(f"   {url}")
            print()

        await context.close()


asyncio.run(main())
