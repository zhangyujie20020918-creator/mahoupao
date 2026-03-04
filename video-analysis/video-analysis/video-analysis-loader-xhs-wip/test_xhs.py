import asyncio
import aiohttp
import re

async def test():
    url = "https://www.xiaohongshu.com/explore/69a597a5000000001a01d5d9?xsec_token=ABlv9yF_BEWNxz3Yv7bCOJUp7vnwuuN7yqpSoEUi7UXp8=&xsec_source=pc_user"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=headers) as r:
            text = await r.text()
            # 搜索视频相关字段
            for keyword in ["noteDetailMap", "video", "masterUrl", "backupUrls", "stream"]:
                idx = text.find(keyword)
                if idx != -1:
                    print(f"找到 {keyword} 在位置 {idx}:")
                    print(text[idx:idx+500])
                    print("---")
                else:
                    print(f"未找到 {keyword}")

asyncio.run(test())
