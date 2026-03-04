"""异步工具"""

import asyncio
import json
from pathlib import Path
from typing import Any

import aiofiles


async def read_json(file_path: Path) -> Any:
    """异步读取 JSON 文件"""
    async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
        content = await f.read()
        return json.loads(content)


async def write_json(file_path: Path, data: Any) -> None:
    """异步写入 JSON 文件"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))


async def run_parallel(*coroutines):
    """并行运行多个协程"""
    return await asyncio.gather(*coroutines, return_exceptions=True)
