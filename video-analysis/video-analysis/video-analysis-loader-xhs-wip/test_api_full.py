"""
捕获 XHS user_posted API 完整响应，分析笔记结构（特别是 xsec_token 字段）
"""

import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright

PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))
USER_URL = "https://www.xiaohongshu.com/user/profile/64210ed10000000012013943"


async def main():
    all_notes = []

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
            if "user_posted" in url:
                try:
                    body = await response.json()
                    notes = body.get("data", {}).get("notes", [])
                    all_notes.extend(notes)
                    print(f"[API] user_posted -> {len(notes)} notes (total: {len(all_notes)})")
                except Exception as e:
                    print(f"[API] 解析失败: {e}")

        page.on("response", handle_response)

        await page.goto(USER_URL, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("section.note-item", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(3)

        # 滚动几次触发更多 API 请求
        for i in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

        page.remove_listener("response", handle_response)
        await context.close()

    output_file = Path("api_notes_dump.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(all_notes, f, ensure_ascii=False, indent=2)

    print(f"共捕获 {len(all_notes)} 条笔记，已写入 {output_file}")

    if all_notes:
        # 打印前10条关键字段
        lines = []
        lines.append(f"共捕获 {len(all_notes)} 条笔记")
        lines.append("\n--- 所有字段名（第1条）---")
        lines.append(str(list(all_notes[0].keys())))
        lines.append("\n--- 前10条关键字段 ---")
        for i, note in enumerate(all_notes[:10], 1):
            note_id = note.get("id", note.get("note_id", "?"))
            note_type = note.get("type", "?")
            xsec_token = note.get("xsec_token", "MISSING")
            token_preview = (xsec_token[:30] + "...") if xsec_token != "MISSING" else "MISSING"
            lines.append(f"[{i:2d}] id={note_id} type={note_type} xsec_token={token_preview!r}")

        with open("api_summary.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print("摘要已写入 api_summary.txt")


asyncio.run(main())
