"""
情绪管理服务
管理参考音频的情绪标签，用于情绪化语音合成
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
import soundfile as sf

import config

logger = logging.getLogger(__name__)

# 预定义的情绪类型 - 丰富的情绪分类，方便扩展
EMOTION_TYPES = {
    # ========== 基础情绪 ==========
    "neutral": {"name": "平静", "description": "正常、平稳的语气", "category": "basic", "color": "#94a3b8"},
    "happy": {"name": "开心", "description": "愉快、积极的语气", "category": "basic", "color": "#fbbf24"},
    "sad": {"name": "伤感", "description": "低落、忧伤的语气", "category": "basic", "color": "#64748b"},
    "angry": {"name": "生气", "description": "愤怒、不满的语气", "category": "basic", "color": "#ef4444"},
    "fear": {"name": "害怕", "description": "恐惧、担忧的语气", "category": "basic", "color": "#a855f7"},
    "surprise": {"name": "惊讶", "description": "意外、震惊的语气", "category": "basic", "color": "#f97316"},
    "disgust": {"name": "厌恶", "description": "反感、嫌弃的语气", "category": "basic", "color": "#84cc16"},

    # ========== 积极情绪 ==========
    "excited": {"name": "激动", "description": "兴奋、热情的语气", "category": "positive", "color": "#f472b6"},
    "joyful": {"name": "喜悦", "description": "发自内心的喜悦", "category": "positive", "color": "#fde047"},
    "proud": {"name": "骄傲", "description": "自豪、得意的语气", "category": "positive", "color": "#fb923c"},
    "grateful": {"name": "感激", "description": "感谢、感恩的语气", "category": "positive", "color": "#4ade80"},
    "hopeful": {"name": "期待", "description": "充满希望、期待", "category": "positive", "color": "#22d3ee"},
    "confident": {"name": "自信", "description": "自信、坚定的语气", "category": "positive", "color": "#f59e0b"},
    "playful": {"name": "调皮", "description": "俏皮、玩笑的语气", "category": "positive", "color": "#a78bfa"},
    "loving": {"name": "温馨", "description": "充满爱意、温暖", "category": "positive", "color": "#fb7185"},

    # ========== 消极情绪 ==========
    "anxious": {"name": "焦虑", "description": "紧张、不安的语气", "category": "negative", "color": "#fca5a5"},
    "frustrated": {"name": "沮丧", "description": "挫败、失望的语气", "category": "negative", "color": "#9ca3af"},
    "lonely": {"name": "孤独", "description": "寂寞、孤单的语气", "category": "negative", "color": "#6b7280"},
    "jealous": {"name": "嫉妒", "description": "羡慕、嫉妒的语气", "category": "negative", "color": "#a3e635"},
    "guilty": {"name": "愧疚", "description": "内疚、自责的语气", "category": "negative", "color": "#d4d4d8"},
    "bored": {"name": "无聊", "description": "厌倦、提不起劲", "category": "negative", "color": "#a1a1aa"},
    "tired": {"name": "疲惫", "description": "疲劳、无力的语气", "category": "negative", "color": "#78716c"},
    "annoyed": {"name": "烦躁", "description": "烦闘、不耐烦", "category": "negative", "color": "#f87171"},

    # ========== 说话风格 ==========
    "serious": {"name": "严肃", "description": "认真、正式的语气", "category": "style", "color": "#475569"},
    "gentle": {"name": "温柔", "description": "柔和、亲切的语气", "category": "style", "color": "#f9a8d4"},
    "firm": {"name": "坚定", "description": "果断、有力的语气", "category": "style", "color": "#0ea5e9"},
    "hesitant": {"name": "犹豫", "description": "迟疑、不确定", "category": "style", "color": "#c4b5fd"},
    "sarcastic": {"name": "讽刺", "description": "挖苦、嘲讽的语气", "category": "style", "color": "#fcd34d"},
    "dramatic": {"name": "夸张", "description": "戏剧化、夸张表达", "category": "style", "color": "#e879f9"},
    "casual": {"name": "随意", "description": "轻松、随意的语气", "category": "style", "color": "#86efac"},
    "formal": {"name": "正式", "description": "庄重、正式的语气", "category": "style", "color": "#60a5fa"},

    # ========== 特殊场景 ==========
    "curious": {"name": "好奇", "description": "疑问、探索的语气", "category": "special", "color": "#38bdf8"},
    "mysterious": {"name": "神秘", "description": "神秘、悬疑的语气", "category": "special", "color": "#818cf8"},
    "storytelling": {"name": "讲故事", "description": "娓娓道来的叙述", "category": "special", "color": "#c084fc"},
    "explaining": {"name": "讲解", "description": "解释说明的语气", "category": "special", "color": "#2dd4bf"},
    "persuading": {"name": "劝说", "description": "说服、劝导的语气", "category": "special", "color": "#34d399"},
    "comforting": {"name": "安慰", "description": "安慰、抚慰的语气", "category": "special", "color": "#fda4af"},
    "encouraging": {"name": "鼓励", "description": "鼓励、打气的语气", "category": "special", "color": "#a3e635"},
    "warning": {"name": "警告", "description": "警示、提醒的语气", "category": "special", "color": "#fca5a5"},

    # ========== 互动类 ==========
    "greeting": {"name": "打招呼", "description": "问候、寒暄", "category": "interaction", "color": "#5eead4"},
    "thanking": {"name": "感谢", "description": "表达谢意", "category": "interaction", "color": "#bef264"},
    "apologizing": {"name": "道歉", "description": "表示歉意", "category": "interaction", "color": "#fca5a5"},
    "asking": {"name": "提问", "description": "询问、请求", "category": "interaction", "color": "#93c5fd"},
    "answering": {"name": "回答", "description": "回应、解答", "category": "interaction", "color": "#86efac"},
    "agreeing": {"name": "赞同", "description": "同意、认可", "category": "interaction", "color": "#4ade80"},
    "disagreeing": {"name": "反对", "description": "不同意、反驳", "category": "interaction", "color": "#f87171"},
    "ending": {"name": "结束语", "description": "结尾、告别", "category": "interaction", "color": "#d8b4fe"},
}

# 情绪分类
EMOTION_CATEGORIES = {
    "basic": {"name": "基础情绪", "description": "人类基本情绪"},
    "positive": {"name": "积极情绪", "description": "正向、积极的情绪"},
    "negative": {"name": "消极情绪", "description": "负向、消极的情绪"},
    "style": {"name": "说话风格", "description": "不同的说话方式"},
    "special": {"name": "特殊场景", "description": "特定场景下的语气"},
    "interaction": {"name": "互动场景", "description": "人际交互场景"},
}


def get_emotions_file(blogger_name: str) -> Path:
    """获取博主的情绪标注文件路径"""
    return config.DATASETS_DIR / blogger_name / "emotions.json"


def load_emotions(blogger_name: str) -> Dict[str, str]:
    """
    加载博主的情绪标注数据

    Returns:
        Dict[audio_filename, emotion_key]
    """
    emotions_file = get_emotions_file(blogger_name)
    if emotions_file.exists():
        try:
            with open(emotions_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载情绪文件失败: {e}")
    return {}


def save_emotions(blogger_name: str, emotions: Dict[str, str]) -> bool:
    """保存情绪标注数据"""
    emotions_file = get_emotions_file(blogger_name)
    try:
        emotions_file.parent.mkdir(parents=True, exist_ok=True)
        with open(emotions_file, "w", encoding="utf-8") as f:
            json.dump(emotions, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存情绪文件失败: {e}")
        return False


def get_emotion_types() -> Dict[str, Any]:
    """获取所有情绪类型"""
    return EMOTION_TYPES


def get_reference_audios(blogger_name: str) -> List[Dict[str, Any]]:
    """
    获取博主的所有参考音频及其情绪标签

    Returns:
        List of {filename, text, duration, emotion, emotion_name}
    """
    dataset_dir = config.DATASETS_DIR / blogger_name
    list_file = dataset_dir / f"{blogger_name}.list"
    audio_dir = dataset_dir / "audio"

    if not list_file.exists():
        return []

    # 加载情绪标注
    emotions = load_emotions(blogger_name)

    audios = []

    try:
        with open(list_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split("|")
                if len(parts) < 4:
                    continue

                audio_path = parts[0]  # e.g., "audio/0001.wav"
                text = parts[3]

                # 获取完整路径
                if not Path(audio_path).is_absolute():
                    full_path = dataset_dir / audio_path
                else:
                    full_path = Path(audio_path)

                if not full_path.exists():
                    continue

                # 获取音频时长
                try:
                    data, sr = sf.read(str(full_path))
                    duration = len(data) / sr
                except:
                    duration = 0

                # 只返回时长在 3-10 秒内的音频作为参考选项
                if duration < 3 or duration > 10:
                    continue

                filename = Path(audio_path).name
                emotion_key = emotions.get(filename, "neutral")
                emotion_info = EMOTION_TYPES.get(emotion_key, EMOTION_TYPES["neutral"])

                audios.append({
                    "filename": filename,
                    "path": str(full_path),
                    "text": text,
                    "duration": round(duration, 2),
                    "emotion": emotion_key,
                    "emotion_name": emotion_info["name"],
                })

    except Exception as e:
        logger.error(f"读取参考音频列表失败: {e}")

    return audios


def tag_emotion(blogger_name: str, filename: str, emotion: str) -> bool:
    """
    为音频文件设置情绪标签

    Args:
        blogger_name: 博主名称
        filename: 音频文件名 (如 "0001.wav")
        emotion: 情绪类型 (如 "happy")

    Returns:
        是否成功
    """
    if emotion not in EMOTION_TYPES:
        logger.error(f"无效的情绪类型: {emotion}")
        return False

    emotions = load_emotions(blogger_name)
    emotions[filename] = emotion
    return save_emotions(blogger_name, emotions)


def get_audio_by_emotion(blogger_name: str, emotion: str) -> Optional[Dict[str, Any]]:
    """
    获取指定情绪的参考音频

    Args:
        blogger_name: 博主名称
        emotion: 情绪类型

    Returns:
        音频信息，或 None
    """
    audios = get_reference_audios(blogger_name)

    # 首先尝试找到精确匹配的情绪
    for audio in audios:
        if audio["emotion"] == emotion:
            return audio

    # 如果没有找到，返回第一个可用的（作为 fallback）
    if audios:
        logger.warning(f"未找到情绪 '{emotion}' 的参考音频，使用默认")
        return audios[0]

    return None


def get_emotion_statistics(blogger_name: str) -> Dict[str, int]:
    """获取各情绪类型的音频数量统计"""
    audios = get_reference_audios(blogger_name)

    stats = {key: 0 for key in EMOTION_TYPES.keys()}

    for audio in audios:
        emotion = audio.get("emotion", "neutral")
        if emotion in stats:
            stats[emotion] += 1

    return stats
