"""
诊断用户主页批量下载失败原因：
1. 提取前5条笔记URL
2. 对每条URL用浏览器测试，打印是否有 <video> 元素、实际页面URL
"""

import asyncio
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))
USER_URL = "https://www.xiaohongshu.com/user/profile/64210ed10000000012013943"
VIDEO_CDN_PATTERNS = ["sns-video", "xhs-video"]


async def extract_urls(page, user_url: str, max_scroll: int = 5) -> list[str]:
    collected = {}
    await page.goto(user_url, wait_until="domcontentloaded", timeout=30000)
    try:
        await page.wait_for_selector("section.note-item, .feeds-container", timeout=10000)
    except Exception:
        pass
    await asyncio.sleep(2)

    for i in range(max_scroll):
        links = await page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href]');
                const results = [];
                for (const a of anchors) {
                    const href = a.getAttribute('href') || '';
                    if (href.includes('/explore/') || href.includes('/discovery/item/')) {
                        const full = href.startsWith('http')
                            ? href
                            : 'https://www.xiaohongshu.com' + href;
                        results.push(full);
                    }
                }
                return results;
            }
        """)
        for link in links:
            m = re.search(r'/(?:explore|discovery/item)/([a-f0-9]+)', link)
            if m:
                collected[m.group(1)] = link
        print(f"  滚动 {i+1}: 已收集 {len(collected)} 条")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(1.5)

    return list(collected.values())


async def test_note_url(page, url: str, idx: int):
    print(f"\n--- 笔记 {idx}: {url}")
    video_url = None

    async def handle_response(response):
        nonlocal video_url
        if video_url:
            return
        ct = response.headers.get("content-type", "")
        u = response.url
        if "video" in ct or any(p in u.lower() for p in VIDEO_CDN_PATTERNS):
            video_url = u
            print(f"  [拦截] {ct} | {u[:80]}")

    page.on("response", handle_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        actual_url = page.url
        print(f"  实际URL: {actual_url[:100]}")
        if "404" in actual_url or "error" in actual_url:
            print(f"  → 404/错误页面")
        else:
            try:
                await page.wait_for_selector("video", timeout=8000)
                print(f"  → 检测到 <video> 元素 ✓")
            except Exception:
                print(f"  → 无 <video> 元素（可能是图片笔记）")
            if video_url:
                print(f"  → 拦截到视频 URL ✓")
            else:
                print(f"  → 未拦截到视频 URL")
    except Exception as e:
        print(f"  → 导航失败: {e}")
    finally:
        page.remove_listener("response", handle_response)


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        print("步骤1: 从用户主页提取前5条笔记URL（滚动5次）")
        urls = await extract_urls(page, USER_URL, max_scroll=3)
        test_urls = urls[:5]
        print(f"提取到 {len(urls)} 条，取前 {len(test_urls)} 条测试\n")

        print("步骤2: 逐条测试是否有视频")
        for i, url in enumerate(test_urls, 1):
            await test_note_url(page, url, i)

        await context.close()


asyncio.run(main())
