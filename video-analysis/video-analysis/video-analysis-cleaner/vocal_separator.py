"""
人声分离服务 - 使用 Demucs 去除背景音乐
"""

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import torch
import torchaudio

from config import FFMPEG_PATH

# Demucs lazy import — 首次调用时加载
_separator = None


def _get_separator():
    """懒加载 Demucs 模型（htdemucs，质量最好的预训练模型）"""
    global _separator
    if _separator is None:
        from demucs.pretrained import get_model

        print("[VocalSep] Loading demucs model: htdemucs")
        model = get_model("htdemucs")
        if torch.cuda.is_available():
            model = model.cuda()
            print("[VocalSep] Using GPU")
        else:
            print("[VocalSep] Using CPU")
        _separator = model
    return _separator


def _save_as_mp3_ffmpeg(wav_path: Path, mp3_path: Path, bitrate: int = 192) -> bool:
    """用系统 ffmpeg 将 WAV 转为 MP3（比 torchaudio MP3 后端更可靠）"""
    cmd = [
        FFMPEG_PATH,
        "-i", str(wav_path),
        "-acodec", "libmp3lame",
        "-ab", f"{bitrate}k",
        "-y",
        str(mp3_path),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
    result = subprocess.run(cmd, capture_output=True, creationflags=creationflags)
    return result.returncode == 0


def separate_vocals(
    input_path: Path,
    output_path: Optional[Path] = None,
    mp3_bitrate: int = 192,
) -> dict:
    """
    对单个音频文件执行人声分离，去除背景音乐。

    Args:
        input_path: 输入 MP3 文件
        output_path: 输出路径（默认覆盖原文件）
        mp3_bitrate: 输出 MP3 比特率 (kbps)

    Returns:
        {"success": bool, "message": str}
    """
    input_path = Path(input_path)
    if output_path is None:
        output_path = input_path

    if not input_path.exists():
        return {"success": False, "message": "文件不存在"}

    tmp_wav_path = None
    tmp_mp3_path = None
    try:
        from demucs.apply import apply_model

        model = _get_separator()

        # 加载音频
        wav, sr = torchaudio.load(str(input_path))

        # Demucs 需要的采样率
        target_sr = model.samplerate
        if sr != target_sr:
            wav = torchaudio.functional.resample(wav, sr, target_sr)
            sr = target_sr

        # 确保是立体声 (2 channels)
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)
        elif wav.shape[0] > 2:
            wav = wav[:2]

        # Normalize
        ref = wav.mean(0)
        wav = (wav - ref.mean()) / ref.std()
        device = next(model.parameters()).device
        wav_input = wav.unsqueeze(0).to(device)

        # 执行分离（split=True 分段处理，防止显存溢出；shifts=0 加速）
        duration_sec = wav_input.shape[-1] / target_sr
        print(f"[VocalSep] 正在分离: {input_path.name} (音频时长 {duration_sec:.0f}s, 设备 {device})")
        t0 = time.time()
        with torch.no_grad():
            sources = apply_model(
                model, wav_input, device=device,
                split=True, overlap=0.25, shifts=0,
            )
        elapsed = time.time() - t0
        print(f"[VocalSep] 模型推理完成: {elapsed:.1f}s")

        # sources shape: (1, num_sources, channels, samples)
        # htdemucs 源顺序: drums, bass, other, vocals
        sources = sources[0]  # 去掉 batch 维度
        # 还原 normalize
        sources = sources * ref.std() + ref.mean()

        # 提取 vocals (最后一个 source)
        vocals = sources[-1]

        # 先保存为 WAV 临时文件（torchaudio WAV 保存最可靠）
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_wav_path = Path(tmp.name)
        torchaudio.save(str(tmp_wav_path), vocals.cpu(), target_sr, format="wav")

        # 用 ffmpeg 将 WAV 转为 MP3（比 torchaudio MP3 后端更可靠）
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_mp3_path = Path(tmp.name)

        if not _save_as_mp3_ffmpeg(tmp_wav_path, tmp_mp3_path, mp3_bitrate):
            return {"success": False, "message": "ffmpeg WAV→MP3 转换失败"}

        # 移动到目标位置（覆盖原文件）
        shutil.move(str(tmp_mp3_path), str(output_path))

        print(f"[VocalSep] 完成: {output_path.name}")
        return {"success": True, "message": "人声分离完成"}

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"人声分离失败: {str(e)[:200]}"}

    finally:
        # 清理临时文件
        for p in (tmp_wav_path, tmp_mp3_path):
            if p is not None:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
