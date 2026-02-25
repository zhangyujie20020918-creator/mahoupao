"""
表情音频库
收集和管理笑声、语气词、叹息等表情音频片段
用于在合成时插入真实录音，而不是让 TTS 模拟
"""

import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
import soundfile as sf
import numpy as np
from pydub import AudioSegment
import io

import config

logger = logging.getLogger(__name__)


# 表情类型定义 - 按类别组织，方便扩展
EXPRESSION_TYPES = {
    # ========== 笑声类 ==========
    "laugh_light": {
        "name": "轻笑",
        "description": "轻微的笑声",
        "triggers": ["呵", "哈", "嘿"],
        "color": "#fda4af",
        "category": "laugh",
    },
    "laugh_normal": {
        "name": "笑声",
        "description": "正常的笑声",
        "triggers": ["哈哈", "嘻嘻", "嘿嘿", "呵呵"],
        "color": "#f472b6",
        "category": "laugh",
    },
    "laugh_big": {
        "name": "大笑",
        "description": "开怀大笑",
        "triggers": ["哈哈哈", "哈哈哈哈", "嘻嘻嘻", "啊哈哈"],
        "color": "#ec4899",
        "category": "laugh",
    },
    "laugh_shy": {
        "name": "害羞笑",
        "description": "害羞、腼腆的笑",
        "triggers": ["嘻", "嘻嘻嘻"],
        "color": "#f9a8d4",
        "category": "laugh",
    },
    "laugh_mock": {
        "name": "嘲笑",
        "description": "讽刺、嘲讽的笑",
        "triggers": ["切", "哼", "呵呵呵"],
        "color": "#fb7185",
        "category": "laugh",
    },

    # ========== 思考/犹豫类 ==========
    "think_short": {
        "name": "短思考",
        "description": "短暂的思考",
        "triggers": ["嗯", "唔"],
        "color": "#a78bfa",
        "category": "think",
    },
    "think_long": {
        "name": "长思考",
        "description": "较长的思考犹豫",
        "triggers": ["嗯...", "这个嘛", "让我想想"],
        "color": "#8b5cf6",
        "category": "think",
    },
    "think_hesitate": {
        "name": "犹豫",
        "description": "犹豫不决的声音",
        "triggers": ["额", "呃", "这..."],
        "color": "#7c3aed",
        "category": "think",
    },
    "think_recall": {
        "name": "回忆",
        "description": "回想、回忆时的声音",
        "triggers": ["emmm", "emm", "hmm"],
        "color": "#6d28d9",
        "category": "think",
    },

    # ========== 叹气/感叹类 ==========
    "sigh_tired": {
        "name": "疲惫叹气",
        "description": "疲惫、无奈的叹气",
        "triggers": ["唉", "哎", "唉..."],
        "color": "#93c5fd",
        "category": "sigh",
    },
    "sigh_relief": {
        "name": "松口气",
        "description": "如释重负的叹气",
        "triggers": ["呼", "吁"],
        "color": "#60a5fa",
        "category": "sigh",
    },
    "sigh_regret": {
        "name": "遗憾叹气",
        "description": "遗憾、惋惜的叹气",
        "triggers": ["可惜", "唉呀"],
        "color": "#3b82f6",
        "category": "sigh",
    },

    # ========== 惊讶/感叹类 ==========
    "surprise_wow": {
        "name": "惊叹",
        "description": "惊喜、惊叹",
        "triggers": ["哇", "哇塞", "我去", "卧槽"],
        "color": "#fde047",
        "category": "surprise",
    },
    "surprise_oh": {
        "name": "恍然",
        "description": "恍然大悟",
        "triggers": ["哦", "噢", "原来如此"],
        "color": "#fbbf24",
        "category": "surprise",
    },
    "surprise_shock": {
        "name": "震惊",
        "description": "震惊、不可思议",
        "triggers": ["啊", "什么", "真的假的", "不会吧"],
        "color": "#f59e0b",
        "category": "surprise",
    },
    "surprise_question": {
        "name": "疑问",
        "description": "疑惑、不解",
        "triggers": ["啊？", "嗯？", "哈？", "欸？"],
        "color": "#d97706",
        "category": "surprise",
    },

    # ========== 语气词/填充词类 ==========
    "filler_this": {
        "name": "这个那个",
        "description": "常用填充词",
        "triggers": ["这个", "那个", "这个那个"],
        "color": "#6ee7b7",
        "category": "filler",
    },
    "filler_then": {
        "name": "然后就是",
        "description": "连接词",
        "triggers": ["然后", "就是", "然后就是", "接着"],
        "color": "#34d399",
        "category": "filler",
    },
    "filler_well": {
        "name": "其实反正",
        "description": "转折填充词",
        "triggers": ["其实", "反正", "总之", "所以说"],
        "color": "#10b981",
        "category": "filler",
    },
    "filler_you_know": {
        "name": "你知道吧",
        "description": "口头禅类",
        "triggers": ["你知道吧", "对吧", "是吧", "懂吗"],
        "color": "#059669",
        "category": "filler",
    },

    # ========== 情绪感叹类 ==========
    "emotion_excited": {
        "name": "兴奋",
        "description": "兴奋激动的声音",
        "triggers": ["耶", "太棒了", "好耶"],
        "color": "#fb923c",
        "category": "emotion",
    },
    "emotion_angry": {
        "name": "生气",
        "description": "生气愤怒的声音",
        "triggers": ["哼", "啧", "烦死了"],
        "color": "#ef4444",
        "category": "emotion",
    },
    "emotion_sad": {
        "name": "伤心",
        "description": "难过伤心的声音",
        "triggers": ["呜", "呜呜", "好难过"],
        "color": "#64748b",
        "category": "emotion",
    },
    "emotion_cute": {
        "name": "撒娇",
        "description": "撒娇卖萌的声音",
        "triggers": ["嘛", "啦", "呀", "人家"],
        "color": "#f0abfc",
        "category": "emotion",
    },
    "emotion_disgust": {
        "name": "嫌弃",
        "description": "嫌弃鄙视的声音",
        "triggers": ["切", "呸", "啧啧"],
        "color": "#a3a3a3",
        "category": "emotion",
    },

    # ========== 回应/应答类 ==========
    "response_yes": {
        "name": "肯定",
        "description": "肯定、同意",
        "triggers": ["对", "是的", "没错", "对对对", "嗯嗯"],
        "color": "#4ade80",
        "category": "response",
    },
    "response_no": {
        "name": "否定",
        "description": "否定、不同意",
        "triggers": ["不", "不是", "没有", "不对"],
        "color": "#f87171",
        "category": "response",
    },
    "response_ok": {
        "name": "好的",
        "description": "应答、确认",
        "triggers": ["好", "好的", "行", "可以", "OK"],
        "color": "#a3e635",
        "category": "response",
    },

    # ========== 拟声词类 ==========
    "sound_eat": {
        "name": "吃东西",
        "description": "吃东西的声音",
        "triggers": ["嗯~", "好吃", "真香"],
        "color": "#fca5a5",
        "category": "sound",
    },
    "sound_drink": {
        "name": "喝东西",
        "description": "喝水等声音",
        "triggers": ["咕噜", "啊~"],
        "color": "#7dd3fc",
        "category": "sound",
    },
    "sound_breath": {
        "name": "呼吸",
        "description": "深呼吸、喘气",
        "triggers": ["呼...", "哈..."],
        "color": "#d4d4d8",
        "category": "sound",
    },

    # ========== 口头禅/个人特色类 ==========
    "catchphrase_1": {
        "name": "口头禅1",
        "description": "博主特有口头禅",
        "triggers": [],  # 用户自定义
        "color": "#c084fc",
        "category": "catchphrase",
    },
    "catchphrase_2": {
        "name": "口头禅2",
        "description": "博主特有口头禅",
        "triggers": [],
        "color": "#a855f7",
        "category": "catchphrase",
    },
    "catchphrase_3": {
        "name": "口头禅3",
        "description": "博主特有口头禅",
        "triggers": [],
        "color": "#9333ea",
        "category": "catchphrase",
    },
}

# 表情分类
EXPRESSION_CATEGORIES = {
    "laugh": {"name": "笑声", "color": "#ec4899"},
    "think": {"name": "思考", "color": "#8b5cf6"},
    "sigh": {"name": "叹气", "color": "#3b82f6"},
    "surprise": {"name": "惊讶", "color": "#f59e0b"},
    "filler": {"name": "语气词", "color": "#10b981"},
    "emotion": {"name": "情绪", "color": "#f97316"},
    "response": {"name": "回应", "color": "#84cc16"},
    "sound": {"name": "拟声", "color": "#06b6d4"},
    "catchphrase": {"name": "口头禅", "color": "#a855f7"},
}


@dataclass
class ExpressionClip:
    """表情音频片段"""
    id: str                    # 唯一ID
    blogger_name: str          # 博主名称
    expression_type: str       # 表情类型
    source_file: str           # 来源音频文件
    start_time: float          # 开始时间 (秒)
    end_time: float            # 结束时间 (秒)
    text: str                  # 对应文本
    audio_path: str            # 导出的音频路径
    duration: float            # 时长


def get_library_dir(blogger_name: str) -> Path:
    """获取博主的表情库目录"""
    return config.DATASETS_DIR / blogger_name / "expressions"


def get_library_file(blogger_name: str) -> Path:
    """获取表情库索引文件"""
    return get_library_dir(blogger_name) / "library.json"


def load_library(blogger_name: str) -> List[ExpressionClip]:
    """加载表情库"""
    library_file = get_library_file(blogger_name)
    if not library_file.exists():
        return []

    try:
        with open(library_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [ExpressionClip(**item) for item in data.get("clips", [])]
    except Exception as e:
        logger.error(f"加载表情库失败: {e}")
        return []


def save_library(blogger_name: str, clips: List[ExpressionClip]) -> bool:
    """保存表情库"""
    library_dir = get_library_dir(blogger_name)
    library_dir.mkdir(parents=True, exist_ok=True)
    library_file = get_library_file(blogger_name)

    try:
        data = {
            "blogger_name": blogger_name,
            "clips": [asdict(clip) for clip in clips],
        }
        with open(library_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存表情库失败: {e}")
        return False


def extract_expression_clip(
    blogger_name: str,
    source_audio: str,
    start_time: float,
    end_time: float,
    expression_type: str,
    text: str,
) -> Optional[ExpressionClip]:
    """
    从音频中提取表情片段

    Args:
        blogger_name: 博主名称
        source_audio: 源音频文件路径
        start_time: 开始时间 (秒)
        end_time: 结束时间 (秒)
        expression_type: 表情类型
        text: 对应文本

    Returns:
        ExpressionClip 或 None
    """
    if expression_type not in EXPRESSION_TYPES:
        logger.error(f"无效的表情类型: {expression_type}")
        return None

    library_dir = get_library_dir(blogger_name)
    library_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 加载源音频
        audio = AudioSegment.from_file(source_audio)

        # 提取片段
        start_ms = int(start_time * 1000)
        end_ms = int(end_time * 1000)
        clip_audio = audio[start_ms:end_ms]

        # 生成唯一ID
        import hashlib
        clip_id = hashlib.md5(f"{source_audio}_{start_time}_{end_time}".encode()).hexdigest()[:8]

        # 导出音频
        audio_filename = f"{expression_type}_{clip_id}.wav"
        audio_path = library_dir / audio_filename

        clip_audio = clip_audio.set_frame_rate(config.SAMPLE_RATE)
        clip_audio = clip_audio.set_channels(1)
        clip_audio.export(str(audio_path), format="wav")

        duration = (end_time - start_time)

        clip = ExpressionClip(
            id=clip_id,
            blogger_name=blogger_name,
            expression_type=expression_type,
            source_file=source_audio,
            start_time=start_time,
            end_time=end_time,
            text=text,
            audio_path=str(audio_path),
            duration=round(duration, 3),
        )

        # 添加到库
        clips = load_library(blogger_name)
        clips.append(clip)
        save_library(blogger_name, clips)

        logger.info(f"提取表情片段: {expression_type} - '{text}' ({duration:.2f}s)")
        return clip

    except Exception as e:
        logger.error(f"提取表情片段失败: {e}")
        return None


def delete_expression_clip(blogger_name: str, clip_id: str) -> bool:
    """删除表情片段"""
    clips = load_library(blogger_name)

    # 找到并删除
    new_clips = []
    deleted = False
    for clip in clips:
        if clip.id == clip_id:
            # 删除音频文件
            try:
                Path(clip.audio_path).unlink(missing_ok=True)
            except:
                pass
            deleted = True
        else:
            new_clips.append(clip)

    if deleted:
        save_library(blogger_name, new_clips)

    return deleted


def get_expression_by_type(blogger_name: str, expression_type: str) -> List[ExpressionClip]:
    """获取指定类型的所有表情片段"""
    clips = load_library(blogger_name)
    return [c for c in clips if c.expression_type == expression_type]


def get_random_expression(blogger_name: str, expression_type: str) -> Optional[ExpressionClip]:
    """随机获取一个指定类型的表情片段"""
    import random
    clips = get_expression_by_type(blogger_name, expression_type)
    if clips:
        return random.choice(clips)
    return None


def get_library_stats(blogger_name: str) -> Dict[str, int]:
    """获取表情库统计"""
    clips = load_library(blogger_name)
    stats = {key: 0 for key in EXPRESSION_TYPES.keys()}
    for clip in clips:
        if clip.expression_type in stats:
            stats[clip.expression_type] += 1
    return stats


def detect_expressions_in_text(text: str) -> List[Tuple[str, str, int, int]]:
    """
    检测文本中的表情词

    Returns:
        List of (expression_type, matched_text, start_pos, end_pos)
    """
    results = []

    for expr_type, info in EXPRESSION_TYPES.items():
        for trigger in info["triggers"]:
            # 查找所有匹配
            pattern = re.escape(trigger) + "+"  # 匹配重复的，如"哈哈哈"
            for match in re.finditer(pattern, text):
                results.append((
                    expr_type,
                    match.group(),
                    match.start(),
                    match.end(),
                ))

    # 按位置排序
    results.sort(key=lambda x: x[2])
    return results


def synthesize_with_expressions(
    synthesize_func,
    text: str,
    blogger_name: str,
    **kwargs,
) -> Dict[str, Any]:
    """
    带表情插入的合成

    1. 检测文本中的表情词
    2. 将文本分割为普通文本和表情
    3. 普通文本用 TTS 合成
    4. 表情用真实录音替换
    5. 拼接所有音频
    """
    # 检测表情
    expressions = detect_expressions_in_text(text)

    if not expressions:
        # 没有表情，直接合成
        return synthesize_func(text, blogger_name, **kwargs)

    # 检查是否有可用的表情库
    stats = get_library_stats(blogger_name)
    has_library = any(count > 0 for count in stats.values())

    if not has_library:
        # 没有表情库，直接合成
        logger.info("没有表情库，跳过表情插入")
        return synthesize_func(text, blogger_name, **kwargs)

    # 分割文本并合成
    segments = []
    last_end = 0

    for expr_type, matched, start, end in expressions:
        # 前面的普通文本
        if start > last_end:
            normal_text = text[last_end:start]
            if normal_text.strip():
                segments.append(("text", normal_text))

        # 表情
        clip = get_random_expression(blogger_name, expr_type)
        if clip:
            segments.append(("expression", clip))
        else:
            # 没有对应表情录音，保留原文本
            segments.append(("text", matched))

        last_end = end

    # 最后的普通文本
    if last_end < len(text):
        remaining = text[last_end:]
        if remaining.strip():
            segments.append(("text", remaining))

    # 合成并拼接
    try:
        combined_audio = AudioSegment.empty()
        sample_rate = config.SAMPLE_RATE

        for seg_type, content in segments:
            if seg_type == "text":
                # TTS 合成
                result = synthesize_func(content, blogger_name, **kwargs)
                if result.get("success") and result.get("audio_base64"):
                    import base64
                    audio_bytes = base64.b64decode(result["audio_base64"])
                    audio_seg = AudioSegment.from_wav(io.BytesIO(audio_bytes))
                    combined_audio += audio_seg
                    sample_rate = result.get("sample_rate", sample_rate)

            elif seg_type == "expression":
                # 插入表情录音
                clip = content
                if Path(clip.audio_path).exists():
                    expr_audio = AudioSegment.from_wav(clip.audio_path)
                    combined_audio += expr_audio

        # 导出合并后的音频
        if len(combined_audio) > 0:
            import base64
            buffer = io.BytesIO()
            combined_audio.export(buffer, format="wav")
            audio_bytes = buffer.getvalue()
            audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

            return {
                "success": True,
                "text": text,
                "blogger_name": blogger_name,
                "duration_seconds": round(len(combined_audio) / 1000, 2),
                "format": "wav",
                "sample_rate": sample_rate,
                "audio_base64": audio_base64,
                "audio_size_bytes": len(audio_bytes),
                "expressions_used": len([s for s in segments if s[0] == "expression"]),
            }
        else:
            return synthesize_func(text, blogger_name, **kwargs)

    except Exception as e:
        logger.error(f"表情合成失败: {e}")
        import traceback
        traceback.print_exc()
        # 回退到普通合成
        return synthesize_func(text, blogger_name, **kwargs)
