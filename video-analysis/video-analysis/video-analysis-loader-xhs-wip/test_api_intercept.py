"""
拦截 XHS 用户主页加载时的 API 请求，找含有 xsec_token 的 note 列表接口
"""

import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))
USER_URL = "https://www.xiaohongshu.com/user/profile/64210ed10000000012013943"


async def main():
    api_responses = []

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.pages[0] if context.pages else await context.new_page()

        async def handle_response(response):
            url = response.url
            # 只关注 XHS API 请求
            if "xiaohongshu.com/api/" in url or "xhslink.com" in url:
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        body = await response.json()
                        body_str = json.dumps(body, ensure_ascii=False)
                        # 如果含有 xsec_token 或 note
                        if "xsec_token" in body_str or "user_posted" in url:
                            api_responses.append({
                                "url": url,
                                "status": response.status,
                                "body_preview": body_str[:500],
                            })
                            print(f"[API] {url}")
                except Exception:
                    pass

        page.on("response", handle_response)

        print(f"正在打开: {USER_URL}")
        await page.goto(USER_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("section.note-item", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)

        # 滚动触发更多加载
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        page.remove_listener("response", handle_response)

        print(f"\n=== 捕获到 {len(api_responses)} 个含 xsec_token 或 user_posted 的 API 响应 ===\n")
        for r in api_responses:
            print(f"URL: {r['url']}")
            print(f"Status: {r['status']}")
            print(f"Body (前500字符):\n{r['body_preview']}")
            print("-" * 60)

        # 同时检查通过 JS 点击事件能否获取完整 URL
        print("\n=== 检查 note-item 上的 Vue/Router 数据 ===")
        vue_data = await page.evaluate("""
            () => {
                // 尝试通过 Vue 实例获取 note 数据
                const noteItems = document.querySelectorAll('section.note-item');
                const results = [];
                for (const item of noteItems) {
                    // 查找 Vue 实例
                    const vueKey = Object.keys(item).find(k => k.startsWith('__vue'));
                    if (vueKey) {
                        const vueInst = item[vueKey];
                        try {
                            const data = JSON.stringify(vueInst.$.props || vueInst.$props || {}).substring(0, 300);
                            results.push(data);
                        } catch(e) {}
                    }
                    if (results.length >= 2) break;
                }
                return results;
            }
        """)
        if vue_data:
            for i, d in enumerate(vue_data, 1):
                print(f"[note-item {i} Vue props]: {d}")
        else:
            print("未找到 Vue 实例数据")

        await context.close()


asyncio.run(main())
