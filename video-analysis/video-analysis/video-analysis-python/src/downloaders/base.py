"""
基础下载器 - 使用yt-dlp作为核心引擎
提供通用实现，子类可以覆盖特定行为
"""

import asyncio
import time
from abc import abstractmethod
from pathlib import Path
from typing import Optional, Any

import yt_dlp

from src.core.interfaces import IDownloader, IProgressCallback
from src.core.models import VideoInfo, DownloadResult, DownloadProgress, Platform
from src.core.exceptions import (
    DownloadFailedError,
    VideoNotFoundError,
    NetworkError,
)
from src.config import get_settings


class BaseDownloader(IDownloader):
    """
    基础下载器实现
    使用yt-dlp作为后端，提供通用的下载逻辑
    子类只需覆盖平台特定的配置和解析逻辑
    """

    def __init__(self):
        self.settings = get_settings()
        self._progress_callback: Optional[IProgressCallback] = None
        self._current_progress = DownloadProgress()

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """子类必须实现：返回平台类型"""
        pass

    @property
    @abstractmethod
    def supported_domains(self) -> list[str]:
        """子类必须实现：返回支持的域名"""
        pass

    def supports_url(self, url: str) -> bool:
        """检查URL是否属于本下载器支持的平台"""
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)

    def _get_yt_dlp_options(self, output_dir: Path, quality: str = "best") -> dict:
        """
        获取yt-dlp配置选项
        子类可以覆盖此方法添加平台特定配置
        """
        # 质量映射
        quality_format = self._get_quality_format(quality)

        options = {
            "format": quality_format,
            "outtmpl": str(output_dir / "%(title)s.%(ext)s").replace("\\", "/"),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
            "retries": self.settings.download.max_retries,
            "socket_timeout": self.settings.download.timeout,
            "ffmpeg_location": self._get_ffmpeg_location(),
            "restrictfilenames": True,  # 限制文件名只使用安全字符
            # 字幕下载选项
            "writesubtitles": True,  # 下载字幕
            "subtitleslangs": ["all"],  # 下载所有可用语言的字幕
            "subtitlesformat": "srt/vtt/best",  # 字幕格式优先级
        }

        # 代理配置
        if self.settings.proxy.enabled:
            if self.settings.proxy.https:
                options["proxy"] = self.settings.proxy.https
            elif self.settings.proxy.http:
                options["proxy"] = self.settings.proxy.http

        return options

    def _get_quality_format(self, quality: str) -> str:
        """获取质量对应的format字符串"""
        quality_map = {
            "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "1080p": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]",
            "720p": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]",
            "480p": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]",
            "audio": "bestaudio[ext=m4a]/bestaudio",
        }
        return quality_map.get(quality, quality_map["best"])

    def _progress_hook(self, d: dict) -> None:
        """yt-dlp进度回调钩子"""
        if d["status"] == "downloading":
            self._current_progress.status = "downloading"
            self._current_progress.downloaded_bytes = d.get("downloaded_bytes", 0)
            self._current_progress.total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate")
            self._current_progress.speed = d.get("speed", 0) or 0
            self._current_progress.eta = d.get("eta")

            if self._current_progress.total_bytes:
                self._current_progress.percentage = (
                    self._current_progress.downloaded_bytes / self._current_progress.total_bytes * 100
                )

            if self._progress_callback:
                self._progress_callback.on_progress(self._current_progress)

        elif d["status"] == "finished":
            self._current_progress.status = "merging"
            self._current_progress.percentage = 100
            if self._progress_callback:
                self._progress_callback.on_progress(self._current_progress)

    def _parse_video_info(self, info: dict, url: str) -> VideoInfo:
        """
        解析yt-dlp返回的信息为VideoInfo
        子类可以覆盖此方法处理平台特定字段
        """
        from datetime import datetime

        upload_date = None
        if date_str := info.get("upload_date"):
            try:
                upload_date = datetime.strptime(date_str, "%Y%m%d")
            except ValueError:
                pass

        return VideoInfo(
            url=url,
            platform=self.platform,
            video_id=info.get("id", ""),
            title=info.get("title", "未知标题"),
            author=info.get("uploader") or info.get("channel"),
            duration=info.get("duration"),
            thumbnail=info.get("thumbnail"),
            description=info.get("description"),
            upload_date=upload_date,
            view_count=info.get("view_count"),
            like_count=info.get("like_count"),
            available_qualities=self._extract_qualities(info),
            raw_data=info,
        )

    def _extract_qualities(self, info: dict) -> list[str]:
        """从info中提取可用画质"""
        qualities = set()
        for fmt in info.get("formats", []):
            if height := fmt.get("height"):
                qualities.add(f"{height}p")
        return sorted(qualities, key=lambda x: int(x[:-1]), reverse=True)

    async def get_video_info(self, url: str) -> VideoInfo:
        """获取视频信息"""
        options = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }
        options.update(self._get_extra_options())

        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(
                None,
                lambda: self._extract_info(url, options)
            )
            return self._parse_video_info(info, url)
        except yt_dlp.utils.DownloadError as e:
            if "not found" in str(e).lower() or "unavailable" in str(e).lower():
                raise VideoNotFoundError(url, str(e))
            raise DownloadFailedError(url, str(e))
        except Exception as e:
            raise NetworkError(url, str(e))

    def _extract_info(self, url: str, options: dict) -> dict:
        """同步提取视频信息"""
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=False)

    async def download(
        self,
        url: str,
        output_dir: Path,
        quality: str = "best",
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """下载视频"""
        self._progress_callback = progress_callback
        self._current_progress = DownloadProgress()
        start_time = time.time()

        # 先获取视频信息
        video_info = await self.get_video_info(url)

        if progress_callback:
            progress_callback.on_start(video_info)

        options = self._get_yt_dlp_options(output_dir, quality)
        options.update(self._get_extra_options())

        try:
            loop = asyncio.get_event_loop()
            result_info = await loop.run_in_executor(
                None,
                lambda: self._do_download(url, options)
            )

            # 获取下载的文件路径
            file_path = self._get_downloaded_file_path(result_info, output_dir)
            file_size = file_path.stat().st_size if file_path and file_path.exists() else None

            # 查找并转换字幕文件
            subtitle_path = self._find_and_convert_subtitles(file_path, output_dir)

            result = DownloadResult(
                success=True,
                video_info=video_info,
                file_path=file_path,
                file_size=file_size,
                elapsed_time=time.time() - start_time,
                subtitle_path=subtitle_path,
            )

            if progress_callback:
                progress_callback.on_complete(result)

            return result

        except Exception as e:
            result = DownloadResult(
                success=False,
                video_info=video_info,
                error_message=str(e),
                elapsed_time=time.time() - start_time,
            )

            if progress_callback:
                progress_callback.on_error(e)

            return result

    def _do_download(self, url: str, options: dict) -> dict:
        """同步执行下载"""
        with yt_dlp.YoutubeDL(options) as ydl:
            return ydl.extract_info(url, download=True)

    def _get_downloaded_file_path(self, info: dict, output_dir: Path) -> Optional[Path]:
        """获取下载后的文件路径"""
        if requested_downloads := info.get("requested_downloads"):
            return Path(requested_downloads[0]["filepath"])

        # 备用方案：根据标题查找
        title = info.get("title", "")
        for ext in ["mp4", "webm", "mkv", "mp3", "m4a"]:
            potential_path = output_dir / f"{title}.{ext}"
            if potential_path.exists():
                return potential_path

        return None

    def _find_and_convert_subtitles(self, video_path: Optional[Path], output_dir: Path) -> Optional[Path]:
        """
        查找下载的字幕文件并转换为txt格式
        返回txt字幕文件路径，如果没有字幕则返回None
        """
        if not video_path:
            return None

        video_stem = video_path.stem  # 视频文件名（不含扩展名）

        # 查找可能的字幕文件（yt-dlp下载的字幕文件名格式：video.lang.ext）
        subtitle_extensions = [".srt", ".vtt", ".ass", ".ssa", ".sub"]
        subtitle_files = []

        for file in output_dir.iterdir():
            if file.is_file() and file.stem.startswith(video_stem):
                if file.suffix.lower() in subtitle_extensions:
                    subtitle_files.append(file)
                # 也检查带语言代码的格式，如 video.en.srt
                for ext in subtitle_extensions:
                    if file.name.endswith(ext):
                        subtitle_files.append(file)
                        break

        # 去重
        subtitle_files = list(set(subtitle_files))

        if not subtitle_files:
            return None

        # 合并所有字幕内容到一个txt文件
        txt_path = output_dir / f"{video_stem}_subtitle.txt"
        all_text_lines = []

        for sub_file in subtitle_files:
            try:
                content = sub_file.read_text(encoding="utf-8")
                # 提取纯文本（去除时间码等）
                clean_text = self._extract_text_from_subtitle(content, sub_file.suffix.lower())
                if clean_text:
                    all_text_lines.append(f"--- {sub_file.name} ---")
                    all_text_lines.append(clean_text)
                    all_text_lines.append("")
            except Exception:
                continue

        if all_text_lines:
            txt_path.write_text("\n".join(all_text_lines), encoding="utf-8")
            return txt_path

        return None

    def _extract_text_from_subtitle(self, content: str, ext: str) -> str:
        """从字幕文件内容中提取纯文本"""
        import re

        lines = content.strip().split("\n")
        text_lines = []

        if ext in [".srt", ".vtt"]:
            # SRT/VTT格式：跳过序号和时间码
            for line in lines:
                line = line.strip()
                # 跳过空行
                if not line:
                    continue
                # 跳过序号（纯数字）
                if line.isdigit():
                    continue
                # 跳过时间码（包含 --> 或 WEBVTT头）
                if "-->" in line or line.startswith("WEBVTT"):
                    continue
                # 跳过NOTE等VTT注释
                if line.startswith("NOTE"):
                    continue
                # 移除HTML标签
                line = re.sub(r"<[^>]+>", "", line)
                # 移除大括号样式标记
                line = re.sub(r"\{[^}]+\}", "", line)
                if line:
                    text_lines.append(line)

        elif ext in [".ass", ".ssa"]:
            # ASS/SSA格式：提取Dialogue行的文本部分
            for line in lines:
                if line.startswith("Dialogue:"):
                    # 格式：Dialogue: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
                    parts = line.split(",", 9)
                    if len(parts) >= 10:
                        text = parts[9]
                        # 移除样式标记
                        text = re.sub(r"\{[^}]+\}", "", text)
                        # 移除换行标记
                        text = text.replace("\\N", " ").replace("\\n", " ")
                        if text.strip():
                            text_lines.append(text.strip())

        else:
            # 其他格式：直接返回内容
            text_lines = [line.strip() for line in lines if line.strip()]

        return "\n".join(text_lines)

    async def download_audio_only(
        self,
        url: str,
        output_dir: Path,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """仅下载音频"""
        self._progress_callback = progress_callback
        self._current_progress = DownloadProgress()
        start_time = time.time()

        video_info = await self.get_video_info(url)

        if progress_callback:
            progress_callback.on_start(video_info)

        options = self._get_yt_dlp_options(output_dir, "audio")
        options.update(self._get_extra_options())
        options["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

        try:
            loop = asyncio.get_event_loop()
            result_info = await loop.run_in_executor(
                None,
                lambda: self._do_download(url, options)
            )

            file_path = self._get_downloaded_file_path(result_info, output_dir)
            file_size = file_path.stat().st_size if file_path and file_path.exists() else None

            # 查找并转换字幕文件
            subtitle_path = self._find_and_convert_subtitles(file_path, output_dir)

            result = DownloadResult(
                success=True,
                video_info=video_info,
                file_path=file_path,
                file_size=file_size,
                elapsed_time=time.time() - start_time,
                subtitle_path=subtitle_path,
            )

            if progress_callback:
                progress_callback.on_complete(result)

            return result

        except Exception as e:
            result = DownloadResult(
                success=False,
                video_info=video_info,
                error_message=str(e),
                elapsed_time=time.time() - start_time,
            )

            if progress_callback:
                progress_callback.on_error(e)

            return result

    def _get_ffmpeg_location(self) -> Optional[str]:
        """获取ffmpeg位置"""
        import shutil
        import sys
        import os

        # 从Python可执行文件路径推断conda环境路径
        # sys.executable 类似 D:\...\envs\video-analysis\python.exe
        python_exe = Path(sys.executable)
        env_root = python_exe.parent  # conda环境根目录

        # Windows conda环境中ffmpeg位置
        conda_ffmpeg = env_root / "Library" / "bin" / "ffmpeg.exe"
        if conda_ffmpeg.exists():
            return str(conda_ffmpeg.parent)

        # 检查CONDA_PREFIX环境变量
        conda_prefix = os.environ.get("CONDA_PREFIX")
        if conda_prefix:
            conda_ffmpeg = Path(conda_prefix) / "Library" / "bin" / "ffmpeg.exe"
            if conda_ffmpeg.exists():
                return str(conda_ffmpeg.parent)

        # 检查系统PATH
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            return str(Path(ffmpeg_path).parent)

        return None

    def _get_extra_options(self) -> dict:
        """
        获取平台特定的额外选项
        子类应该覆盖此方法
        """
        return {}
