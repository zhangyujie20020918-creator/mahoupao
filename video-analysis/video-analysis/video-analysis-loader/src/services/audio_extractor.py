"""
音频提取服务
从视频文件中提取音频
"""

import asyncio
import subprocess
import shutil
from pathlib import Path
from typing import Optional
import sys


class AudioExtractor:
    """音频提取器"""

    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()

    def _find_ffmpeg(self) -> Optional[str]:
        """查找 ffmpeg 路径"""
        # 检查 conda 环境
        python_exe = Path(sys.executable)
        env_root = python_exe.parent
        conda_ffmpeg = env_root / "Library" / "bin" / "ffmpeg.exe"
        if conda_ffmpeg.exists():
            return str(conda_ffmpeg)

        # 检查系统 PATH
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return ffmpeg_path

        return None

    async def extract_audio(
        self,
        video_path: Path,
        output_path: Optional[Path] = None,
        format: str = "mp3",
        bitrate: str = "192k",
    ) -> Path:
        """
        从视频提取音频

        Args:
            video_path: 视频文件路径
            output_path: 输出路径（可选，默认同目录）
            format: 输出格式 (mp3, aac, wav, flac)
            bitrate: 比特率 (128k, 192k, 256k, 320k)

        Returns:
            输出文件路径
        """
        if not self.ffmpeg_path:
            raise RuntimeError("未找到 ffmpeg，请确保已安装")

        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        # 确定输出路径
        if output_path is None:
            output_path = video_path.with_suffix(f".{format}")

        # 构建 ffmpeg 命令
        cmd = [
            self.ffmpeg_path,
            "-i", str(video_path),
            "-vn",  # 不处理视频
            "-acodec", self._get_codec(format),
            "-ab", bitrate,
            "-y",  # 覆盖已存在文件
            str(output_path),
        ]

        # 异步执行
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._run_ffmpeg(cmd))

        return output_path

    def _get_codec(self, format: str) -> str:
        """获取对应格式的编解码器"""
        codecs = {
            "mp3": "libmp3lame",
            "aac": "aac",
            "wav": "pcm_s16le",
            "flac": "flac",
            "ogg": "libvorbis",
        }
        return codecs.get(format, "libmp3lame")

    def _run_ffmpeg(self, cmd: list) -> None:
        """运行 ffmpeg 命令"""
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 错误: {result.stderr}")

    async def get_audio_info(self, file_path: Path) -> dict:
        """获取音频/视频文件信息"""
        if not self.ffmpeg_path:
            raise RuntimeError("未找到 ffmpeg")

        ffprobe_path = str(Path(self.ffmpeg_path).parent / "ffprobe.exe")
        if not Path(ffprobe_path).exists():
            ffprobe_path = shutil.which("ffprobe")

        if not ffprobe_path:
            return {}

        cmd = [
            ffprobe_path,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(file_path),
        ]

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, text=True)
        )

        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
        return {}
