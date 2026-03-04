"""测试下载功能"""
import asyncio
from pathlib import Path
from src.services import DownloadService
from src.config import get_settings

async def test():
    service = DownloadService()
    settings = get_settings()

    print(f"Output dir: {settings.download.output_dir}")
    print(f"Output dir exists: {settings.download.output_dir.exists()}")

    url = "https://www.youtube.com/shorts/cjUdBdh6vlc"

    try:
        result = await service.download(
            url=url,
            output_dir=settings.download.output_dir,
            quality="best",
            audio_only=False,
        )
        print(f"Success: {result.success}")
        print(f"File path: {result.file_path}")
        print(f"Error: {result.error_message}")
    except Exception as e:
        import traceback
        print(f"Exception: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
