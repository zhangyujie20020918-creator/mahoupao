"""
文本预处理服务
处理 TTS 难以合成的文本元素：笑声、语气词、拟声词等
"""

import re
import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# 笑声词汇 - 通常合成效果差，建议移除或替换
LAUGH_PATTERNS = [
    (r'[哈嘿呵嘻]+[哈嘿呵嘻]+', ''),  # 哈哈、嘿嘿、呵呵、嘻嘻 等
    (r'[Hh]+[Aa]+[Hh]*[Aa]*', ''),    # haha, HAHA 等
    (r'[Ll][Oo][Ll]+', ''),            # lol, LOL
    (r'233+', ''),                      # 233333
]

# 思考/犹豫的语气词 - 可以保留简化版本或移除
FILLER_PATTERNS = [
    (r'嗯+', '嗯'),         # 多个"嗯"简化为一个
    (r'啊+', '啊'),         # 多个"啊"简化为一个
    (r'呃+', ''),           # "呃"通常移除效果更好
    (r'额+', ''),           # "额"通常移除效果更好
    (r'唔+', ''),           # "唔"
    (r'emm+', '', re.I),    # emm
    (r'emmm*', '', re.I),   # em, emm, emmm
    (r'hmm+', '', re.I),    # hmm
    (r'umm+', '', re.I),    # umm
]

# 拟声词 - 这些通常合成效果不好
ONOMATOPOEIA_PATTERNS = [
    (r'噗+', ''),           # 噗
    (r'切+', ''),           # 切
    (r'啧+', ''),           # 啧
    (r'嘶+', ''),           # 嘶
    (r'哼+', ''),           # 哼 (可选保留)
    (r'唉+', '唉'),         # 唉 简化
    (r'哎+', '哎'),         # 哎 简化
    (r'呀+', '呀'),         # 呀 简化
    (r'哇+', '哇'),         # 哇 简化
    (r'喔+', ''),           # 喔
    (r'噢+', ''),           # 噢
]

# 省略号和停顿 - 可以简化或移除
PAUSE_PATTERNS = [
    (r'\.{3,}', '，'),      # ... 转为逗号停顿
    (r'。{2,}', '。'),      # 多个句号简化
    (r'，{2,}', '，'),      # 多个逗号简化
    (r'~+', ''),            # 波浪号
    (r'——+', '，'),         # 破折号转逗号
    (r'…+', '，'),          # 省略号转逗号
]

# 网络用语/表情文字 - 移除
INTERNET_SLANG_PATTERNS = [
    (r'\[.+?\]', ''),       # [笑哭] [doge] 等表情
    (r'【.+?】', ''),       # 【】包裹的内容
    (r'→+', ''),            # 箭头
    (r'←+', ''),
    (r'↑+', ''),
    (r'↓+', ''),
    (r'☆+', ''),            # 星号
    (r'★+', ''),
    (r'●+', ''),
    (r'○+', ''),
]


class TextProcessor:
    """文本预处理器"""

    def __init__(self):
        self.remove_laughs = True       # 移除笑声
        self.simplify_fillers = True    # 简化语气词
        self.remove_onomatopoeia = True # 移除拟声词
        self.simplify_pauses = True     # 简化停顿
        self.remove_slang = True        # 移除网络用语

    def process(self, text: str) -> Tuple[str, List[str]]:
        """
        处理文本

        Args:
            text: 原始文本

        Returns:
            (处理后的文本, 处理日志列表)
        """
        original = text
        logs = []

        # 移除笑声
        if self.remove_laughs:
            for pattern, replacement, *flags in self._normalize_patterns(LAUGH_PATTERNS):
                flag = flags[0] if flags else 0
                new_text = re.sub(pattern, replacement, text, flags=flag)
                if new_text != text:
                    logs.append(f"移除笑声: {pattern}")
                    text = new_text

        # 简化语气词
        if self.simplify_fillers:
            for pattern, replacement, *flags in self._normalize_patterns(FILLER_PATTERNS):
                flag = flags[0] if flags else 0
                new_text = re.sub(pattern, replacement, text, flags=flag)
                if new_text != text:
                    logs.append(f"简化语气词: {pattern} -> {replacement or '(移除)'}")
                    text = new_text

        # 移除拟声词
        if self.remove_onomatopoeia:
            for pattern, replacement, *flags in self._normalize_patterns(ONOMATOPOEIA_PATTERNS):
                flag = flags[0] if flags else 0
                new_text = re.sub(pattern, replacement, text, flags=flag)
                if new_text != text:
                    logs.append(f"处理拟声词: {pattern}")
                    text = new_text

        # 简化停顿
        if self.simplify_pauses:
            for pattern, replacement, *flags in self._normalize_patterns(PAUSE_PATTERNS):
                flag = flags[0] if flags else 0
                new_text = re.sub(pattern, replacement, text, flags=flag)
                if new_text != text:
                    logs.append(f"简化停顿: {pattern} -> {replacement}")
                    text = new_text

        # 移除网络用语
        if self.remove_slang:
            for pattern, replacement, *flags in self._normalize_patterns(INTERNET_SLANG_PATTERNS):
                flag = flags[0] if flags else 0
                new_text = re.sub(pattern, replacement, text, flags=flag)
                if new_text != text:
                    logs.append(f"移除网络用语: {pattern}")
                    text = new_text

        # 清理多余空格
        text = re.sub(r'\s+', ' ', text).strip()

        # 清理连续标点
        text = re.sub(r'([，。！？、；：])\1+', r'\1', text)

        # 移除开头的标点
        text = re.sub(r'^[，。！？、；：\s]+', '', text)

        if text != original:
            logger.info(f"文本预处理: '{original[:50]}...' -> '{text[:50]}...'")

        return text, logs

    def _normalize_patterns(self, patterns):
        """标准化模式列表"""
        result = []
        for item in patterns:
            if len(item) == 2:
                result.append((item[0], item[1], 0))
            else:
                result.append(item)
        return result


# 全局处理器实例
_processor = None


def get_text_processor() -> TextProcessor:
    """获取文本处理器单例"""
    global _processor
    if _processor is None:
        _processor = TextProcessor()
    return _processor


def preprocess_text(text: str) -> str:
    """
    预处理文本的便捷函数

    Args:
        text: 原始文本

    Returns:
        处理后的文本
    """
    processor = get_text_processor()
    processed, _ = processor.process(text)
    return processed


# 预设配置
PRESETS = {
    "strict": {
        "remove_laughs": True,
        "simplify_fillers": True,
        "remove_onomatopoeia": True,
        "simplify_pauses": True,
        "remove_slang": True,
    },
    "moderate": {
        "remove_laughs": True,
        "simplify_fillers": True,
        "remove_onomatopoeia": False,  # 保留部分拟声词
        "simplify_pauses": True,
        "remove_slang": True,
    },
    "minimal": {
        "remove_laughs": True,
        "simplify_fillers": False,
        "remove_onomatopoeia": False,
        "simplify_pauses": False,
        "remove_slang": True,
    },
    "none": {
        "remove_laughs": False,
        "simplify_fillers": False,
        "remove_onomatopoeia": False,
        "simplify_pauses": False,
        "remove_slang": False,
    },
}


def apply_preset(preset_name: str) -> TextProcessor:
    """应用预设配置"""
    processor = get_text_processor()
    if preset_name in PRESETS:
        config = PRESETS[preset_name]
        processor.remove_laughs = config["remove_laughs"]
        processor.simplify_fillers = config["simplify_fillers"]
        processor.remove_onomatopoeia = config["remove_onomatopoeia"]
        processor.simplify_pauses = config["simplify_pauses"]
        processor.remove_slang = config["remove_slang"]
    return processor
