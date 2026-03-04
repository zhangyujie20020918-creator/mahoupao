"""
诊断 XHS 笔记链接中的 xsec_token：
- 检查 a.href（浏览器解析后的完整 URL）vs a.getAttribute('href')（原始属性）
- 检查页面 __INITIAL_STATE__ / __NEXT_DATA__ 中是否含有 token
"""

import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))
USER_URL = "https://www.xiaohongshu.com/user/profile/64210ed10000000012013943"


async def main():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        await page.goto(USER_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("section.note-item, .feeds-container", timeout=10000)
        except Exception:
            pass
        await asyncio.sleep(3)

        # 滚动一次让内容加载
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        # 检查 a.href（含 xsec_token 吗？）vs getAttribute('href')
        result = await page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href]');
                const items = [];
                for (const a of anchors) {
                    const raw = a.getAttribute('href') || '';
                    const full = a.href;
                    if (raw.includes('/explore/') || raw.includes('/discovery/item/')) {
                        items.push({ raw, full });
                        if (items.length >= 5) break;
                    }
                }
                return items;
            }
        """)

        print("=== 前5条笔记链接 ===")
        for i, item in enumerate(result, 1):
            print(f"\n[{i}]")
            print(f"  getAttribute: {item['raw']}")
            print(f"  a.href:       {item['full']}")

        # 检查 JS 全局变量中是否有 token
        js_vars = await page.evaluate("""
            () => {
                const keys = Object.keys(window).filter(k =>
                    k.includes('INITIAL') || k.includes('NEXT') || k.includes('STATE') || k.includes('DATA')
                );
                return keys;
            }
        """)
        print(f"\n=== 页面 JS 全局变量（含 INITIAL/NEXT/STATE/DATA）===")
        print(js_vars)

        # 尝试从 __INITIAL_STATE__ 提取笔记 URL
        state = await page.evaluate("""
            () => {
                try {
                    const s = window.__INITIAL_STATE__;
                    if (!s) return null;
                    return JSON.stringify(s).substring(0, 2000);
                } catch(e) { return 'Error: ' + e; }
            }
        """)
        if state:
            print(f"\n=== __INITIAL_STATE__ 前2000字符 ===")
            print(state)

        # 检查 note-item 的 data-* 属性
        data_attrs = await page.evaluate("""
            () => {
                const items = document.querySelectorAll('section.note-item, .note-item');
                const result = [];
                for (const item of items) {
                    const attrs = {};
                    for (const attr of item.attributes) {
                        attrs[attr.name] = attr.value;
                    }
                    // 找内部的 a 标签
                    const a = item.querySelector('a[href]');
                    if (a) {
                        attrs['_a_href'] = a.getAttribute('href');
                        attrs['_a_full_href'] = a.href;
                    }
                    result.push(attrs);
                    if (result.length >= 3) break;
                }
                return result;
            }
        """)
        print(f"\n=== 前3条 note-item 的属性 ===")
        for i, item in enumerate(data_attrs, 1):
            print(f"\n[{i}]", item)

        await context.close()


asyncio.run(main())
