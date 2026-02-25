"""
数据准备服务
从 downloads/{博主}/ 的 mp3 + ASR json 准备训练数据
"""

import json
import logging
from pathlib import Path
from typing import Generator, Dict, Any, List
from dataclasses import dataclass

import numpy as np
from pydub import AudioSegment
import noisereduce as nr

import config

logger = logging.getLogger(__name__)


def denoise_audio(audio_segment: AudioSegment, sample_rate: int = 32000) -> AudioSegment:
    """
    对音频进行降噪处理

    Args:
        audio_segment: pydub AudioSegment 对象
        sample_rate: 采样率

    Returns:
        降噪后的 AudioSegment
    """
    # 转换为 numpy 数组
    samples = np.array(audio_segment.get_array_of_samples(), dtype=np.float32)

    # 归一化到 [-1, 1]
    if audio_segment.sample_width == 2:  # 16-bit
        samples = samples / 32768.0
    elif audio_segment.sample_width == 1:  # 8-bit
        samples = (samples - 128) / 128.0

    # 使用 noisereduce 进行降噪
    # prop_decrease: 降噪强度 (0-1)，0.8 表示降低 80% 的噪音
    reduced_noise = nr.reduce_noise(
        y=samples,
        sr=sample_rate,
        prop_decrease=0.8,  # 降噪强度
        stationary=False,   # 非平稳噪音（更适合语音）
    )

    # 转换回 16-bit 整数
    reduced_noise = np.clip(reduced_noise * 32768.0, -32768, 32767).astype(np.int16)

    # 创建新的 AudioSegment
    denoised_audio = AudioSegment(
        data=reduced_noise.tobytes(),
        sample_width=2,  # 16-bit
        frame_rate=sample_rate,
        channels=1,
    )

    return denoised_audio


@dataclass
class AudioSegmentInfo:
    """音频片段信息"""
    source_file: str
    segment_index: int
    start: float
    end: float
    duration: float
    text: str
    output_path: Path


def get_blogger_source_data(blogger_name: str) -> Dict[str, Any]:
    """获取博主的源数据信息"""
    blogger_dir = config.DOWNLOADS_DIR / blogger_name

    if not blogger_dir.exists():
        return {"exists": False, "error": "博主目录不存在"}

    # 查找配对的 mp3 + json 文件
    mp3_files = list(blogger_dir.glob("*.mp3"))
    pairs = []

    for mp3_file in mp3_files:
        json_file = mp3_file.with_suffix(".json")
        if json_file.exists() and not json_file.name.startswith("_"):
            pairs.append({
                "mp3": mp3_file.name,
                "json": json_file.name,
                "mp3_size_mb": round(mp3_file.stat().st_size / 1e6, 2),
            })

    return {
        "exists": True,
        "blogger_name": blogger_name,
        "source_dir": str(blogger_dir),
        "file_pairs": pairs,
        "total_pairs": len(pairs),
    }


def prepare_dataset_stream(
    blogger_name: str,
    min_duration: float = None,
    max_duration: float = None,
    enable_denoise: bool = True,
) -> Generator[Dict[str, Any], None, None]:
    """
    准备训练数据集 (流式输出进度)

    Args:
        blogger_name: 博主名称
        min_duration: 最小片段时长
        max_duration: 最大片段时长
        enable_denoise: 是否启用降噪

    Yields:
        进度信息字典
    """
    min_duration = min_duration or config.MIN_DURATION
    max_duration = max_duration or config.MAX_DURATION

    blogger_dir = config.DOWNLOADS_DIR / blogger_name
    dataset_dir = config.DATASETS_DIR / blogger_name
    audio_dir = dataset_dir / "audio"

    # 创建输出目录
    audio_dir.mkdir(parents=True, exist_ok=True)

    denoise_status = "已启用" if enable_denoise else "已禁用"
    yield {"type": "start", "message": f"开始准备 {blogger_name} 的训练数据 (降噪: {denoise_status})"}

    # 获取所有配对文件
    mp3_files = sorted(blogger_dir.glob("*.mp3"))
    valid_pairs = []

    for mp3_file in mp3_files:
        json_file = mp3_file.with_suffix(".json")
        if json_file.exists() and not json_file.name.startswith("_"):
            valid_pairs.append((mp3_file, json_file))

    if not valid_pairs:
        yield {"type": "error", "message": "没有找到有效的 mp3 + json 配对文件"}
        return

    total_files = len(valid_pairs)
    total_segments = 0
    valid_segments = 0
    skipped_segments = 0
    list_entries = []
    segment_counter = 0

    for file_idx, (mp3_file, json_file) in enumerate(valid_pairs):
        yield {
            "type": "progress",
            "step": "processing",
            "current": file_idx + 1,
            "total": total_files,
            "file": mp3_file.name,
            "message": f"处理 {mp3_file.name}",
        }

        try:
            # 加载音频
            audio = AudioSegment.from_mp3(str(mp3_file))

            # 加载 ASR 数据
            with open(json_file, "r", encoding="utf-8") as f:
                asr_data = json.load(f)

            segments = asr_data.get("segments", [])
            total_segments += len(segments)

            for seg_idx, segment in enumerate(segments):
                start = segment.get("start", 0)
                end = segment.get("end", 0)
                text = segment.get("text", "").strip()
                duration = end - start

                # 跳过不符合条件的片段
                if duration < min_duration or duration > max_duration:
                    skipped_segments += 1
                    continue

                if not text or len(text) < 2:
                    skipped_segments += 1
                    continue

                # 切片音频
                segment_counter += 1
                output_filename = f"{segment_counter:04d}.wav"
                output_path = audio_dir / output_filename

                start_ms = int(start * 1000)
                end_ms = int(end * 1000)
                audio_segment = audio[start_ms:end_ms]

                # 导出为 WAV (GPT-SoVITS 推荐格式)
                audio_segment = audio_segment.set_frame_rate(config.SAMPLE_RATE)
                audio_segment = audio_segment.set_channels(1)  # 单声道

                # 降噪处理
                if enable_denoise:
                    try:
                        audio_segment = denoise_audio(audio_segment, config.SAMPLE_RATE)
                    except Exception as e:
                        logger.warning(f"降噪失败 {output_filename}: {e}")

                audio_segment.export(str(output_path), format="wav")

                # 添加到标注列表
                # 格式: audio_path|speaker|language|text
                list_entries.append(f"audio/{output_filename}|{blogger_name}|zh|{text}")
                valid_segments += 1

        except Exception as e:
            logger.error(f"处理 {mp3_file.name} 失败: {e}")
            yield {
                "type": "warning",
                "file": mp3_file.name,
                "message": f"处理失败: {str(e)}",
            }
            continue

    # 写入标注文件
    list_file = dataset_dir / f"{blogger_name}.list"
    with open(list_file, "w", encoding="utf-8") as f:
        f.write("\n".join(list_entries))

    # 写入元数据
    metadata = {
        "blogger_name": blogger_name,
        "total_files": total_files,
        "total_segments": total_segments,
        "valid_segments": valid_segments,
        "skipped_segments": skipped_segments,
        "min_duration": min_duration,
        "max_duration": max_duration,
        "sample_rate": config.SAMPLE_RATE,
        "denoise_enabled": enable_denoise,
    }

    metadata_file = dataset_dir / "metadata.json"
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # 计算总时长
    total_duration = 0
    for wav_file in audio_dir.glob("*.wav"):
        try:
            audio = AudioSegment.from_wav(str(wav_file))
            total_duration += len(audio) / 1000
        except:
            pass

    yield {
        "type": "done",
        "message": "数据准备完成",
        "total_files": total_files,
        "valid_segments": valid_segments,
        "skipped_segments": skipped_segments,
        "total_duration_minutes": round(total_duration / 60, 1),
        "dataset_dir": str(dataset_dir),
        "list_file": str(list_file),
    }


def get_dataset_info(blogger_name: str) -> Dict[str, Any]:
    """获取已准备的数据集信息"""
    dataset_dir = config.DATASETS_DIR / blogger_name

    if not dataset_dir.exists():
        return {"exists": False}

    metadata_file = dataset_dir / "metadata.json"
    list_file = dataset_dir / f"{blogger_name}.list"
    audio_dir = dataset_dir / "audio"

    result = {
        "exists": True,
        "blogger_name": blogger_name,
        "dataset_dir": str(dataset_dir),
    }

    if metadata_file.exists():
        with open(metadata_file, "r", encoding="utf-8") as f:
            result["metadata"] = json.load(f)

    if list_file.exists():
        with open(list_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            result["segment_count"] = len(lines)

    if audio_dir.exists():
        wav_files = list(audio_dir.glob("*.wav"))
        result["audio_files"] = len(wav_files)

        # 计算总时长
        total_duration = 0
        for wav_file in wav_files:
            try:
                audio = AudioSegment.from_wav(str(wav_file))
                total_duration += len(audio) / 1000
            except:
                pass
        result["total_duration_minutes"] = round(total_duration / 60, 1)

    return result
