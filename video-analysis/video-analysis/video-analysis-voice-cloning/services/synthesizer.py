"""
语音合成服务
使用训练好的 GPT-SoVITS 模型生成语音
"""

import io
import logging
import os
import sys
import time
import base64
from pathlib import Path
from typing import Dict, Any, Optional

import config

logger = logging.getLogger(__name__)

# GPT-SoVITS 路径
GPT_SOVITS_ROOT = config.BASE_DIR / "GPT_SoVITS_src"
GPT_SOVITS_DIR = GPT_SOVITS_ROOT / "GPT_SoVITS"


def _setup_gpt_sovits_env():
    """设置 GPT-SoVITS 环境"""
    # 保存原始工作目录
    original_cwd = os.getcwd()

    # 设置环境变量
    os.environ["is_half"] = "True" if config.GPU_AVAILABLE else "False"
    os.environ["version"] = "v2"
    # 设置 BERT 模型路径 (用于 G2PW 拼音转换)
    os.environ["bert_path"] = str(config.PRETRAINED_DIR / "chinese-roberta-wwm-ext-large")

    # 切换到 GPT_SoVITS_src 目录 (这是必须的，因为代码中有相对路径)
    os.chdir(str(GPT_SOVITS_ROOT))

    # 添加路径到 sys.path
    paths_to_add = [str(GPT_SOVITS_ROOT), str(GPT_SOVITS_DIR)]
    for p in paths_to_add:
        if p not in sys.path:
            sys.path.insert(0, p)

    return original_cwd


class VoiceSynthesizer:
    """语音合成器 - 使用 GPT-SoVITS TTS 类"""

    def __init__(self):
        self.loaded_soul: Optional[str] = None
        self.gpt_model_path: Optional[str] = None
        self.sovits_model_path: Optional[str] = None
        self.ref_audio_path: Optional[str] = None
        self.ref_text: Optional[str] = None
        self._initialized = False
        self._tts_instance = None
        self._original_cwd = None

    def _ensure_initialized(self):
        """确保 GPT-SoVITS 已初始化"""
        if self._initialized:
            return True

        try:
            logger.info("初始化 GPT-SoVITS TTS...")
            self._original_cwd = _setup_gpt_sovits_env()
            self._initialized = True
            return True

        except Exception as e:
            logger.error(f"初始化 GPT-SoVITS 失败: {e}")
            return False

    def _get_tts_instance(self):
        """获取或创建 TTS 实例"""
        if self._tts_instance is not None:
            return self._tts_instance

        try:
            from TTS_infer_pack.TTS import TTS, TTS_Config

            # 创建配置
            tts_config = TTS_Config("v2")

            # 设置设备
            tts_config.device = config.DEVICE
            tts_config.is_half = config.GPU_AVAILABLE

            # 设置预训练模型路径
            tts_config.cnhuhbert_base_path = str(config.PRETRAINED_DIR / "chinese-hubert-base")
            tts_config.bert_base_path = str(config.PRETRAINED_DIR / "chinese-roberta-wwm-ext-large")

            # 使用训练好的模型
            if self.gpt_model_path:
                tts_config.t2s_weights_path = self.gpt_model_path
            if self.sovits_model_path:
                tts_config.vits_weights_path = self.sovits_model_path

            logger.info(f"创建 TTS 实例...")
            logger.info(f"  GPT 模型: {tts_config.t2s_weights_path}")
            logger.info(f"  SoVITS 模型: {tts_config.vits_weights_path}")
            logger.info(f"  设备: {tts_config.device}")

            self._tts_instance = TTS(tts_config)
            return self._tts_instance

        except Exception as e:
            logger.error(f"创建 TTS 实例失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def load_model(self, soul_name: str) -> bool:
        """
        加载的模型

        Args:
            soul_name: 名称

        Returns:
            是否加载成功
        """
        model_dir = config.TRAINED_DIR / soul_name
        gpt_path = model_dir / "gpt.ckpt"
        sovits_path = model_dir / "sovits.pth"

        if not gpt_path.exists() or not sovits_path.exists():
            logger.error(f"模型文件不存在: {model_dir}")
            return False

        if not self._ensure_initialized():
            return False

        try:
            # 重置参考音频（确保重新选择）
            self.ref_audio_path = None
            self.ref_text = None

            # 查找参考音频 (从数据集中获取时长合适的)
            dataset_dir = config.DATASETS_DIR / soul_name
            list_file = dataset_dir / f"{soul_name}.list"

            if list_file.exists():
                with open(list_file, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    # 遍历所有行，找一个时长在 3-10 秒范围内的参考音频
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        parts = line.split("|")
                        if len(parts) >= 4:
                            audio_path = parts[0]
                            # 转换相对路径为绝对路径
                            if not os.path.isabs(audio_path):
                                audio_path = str(dataset_dir / audio_path)
                            # 检查音频时长是否在 3-10 秒范围内
                            try:
                                import soundfile as sf
                                data, sr = sf.read(audio_path)
                                duration = len(data) / sr
                                if 3 <= duration <= 10:
                                    self.ref_audio_path = audio_path
                                    self.ref_text = parts[3]
                                    logger.info(f"选择参考音频: {audio_path} (时长: {duration:.2f}s)")
                                    break
                            except Exception as e:
                                logger.warning(f"检查音频时长失败: {audio_path}, {e}")
                                continue

            # 如果没有找到参考音频,从 downloads 目录找
            if not self.ref_audio_path:
                downloads_dir = config.DOWNLOADS_DIR / soul_name
                mp3_files = list(downloads_dir.glob("*.mp3"))
                if mp3_files:
                    self.ref_audio_path = str(mp3_files[0])
                    # 查找对应的文本
                    txt_file = mp3_files[0].with_suffix(".txt")
                    if txt_file.exists():
                        with open(txt_file, "r", encoding="utf-8") as f:
                            self.ref_text = f.read().strip()[:100]  # 取前100字符

            self.gpt_model_path = str(gpt_path)
            self.sovits_model_path = str(sovits_path)
            self.loaded_soul = soul_name

            # 重置 TTS 实例以便使用新模型
            self._tts_instance = None

            logger.info(f"加载模型完成: {soul_name}")
            return True

        except Exception as e:
            logger.error(f"加载模型失败: {e}")
            return False

    def synthesize(
        self,
        text: str,
        soul_name: str,
        ref_audio: Optional[str] = None,
        speed: float = 1.0,
        output_format: str = "wav",
        emotion: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        合成语音

        Args:
            text: 要合成的文本
            soul_name: 名称
            ref_audio: 参考音频路径 (可选)
            speed: 语速 (0.5 - 2.0)
            output_format: 输出格式 (wav/mp3)
            emotion: 情绪类型 (可选，如 "happy", "sad", "excited" 等)

        Returns:
            包含音频数据的字典
        """
        # 检查并加载模型（每次都强制重新加载以确保使用最新的参考音频选择逻辑）
        if not self.load_model(soul_name):
            return {
                "success": False,
                "error": f"无法加载 {soul_name} 的模型",
            }

        # 如果指定了情绪，尝试获取对应情绪的参考音频
        if emotion and not ref_audio:
            try:
                from services.emotion_manager import get_audio_by_emotion
                emotion_audio = get_audio_by_emotion(soul_name, emotion)
                if emotion_audio:
                    ref_audio = emotion_audio["path"]
                    self.ref_text = emotion_audio["text"]
                    logger.info(f"使用情绪 '{emotion}' 的参考音频: {emotion_audio['filename']}")
            except Exception as e:
                logger.warning(f"获取情绪参考音频失败: {e}")

        # 验证参数
        if not text or len(text.strip()) == 0:
            return {
                "success": False,
                "error": "文本不能为空",
            }

        speed = max(0.5, min(2.0, speed))

        start_time = time.time()

        try:
            # 获取 TTS 实例
            tts = self._get_tts_instance()
            if tts is None:
                logger.warning("TTS 实例创建失败，使用模拟模式")
                return self._synthesize_mock(text, soul_name, speed)

            # 使用参考音频和文本
            ref_wav = ref_audio or self.ref_audio_path
            ref_text_content = self.ref_text or text[:50]

            # 确保文本以标点结尾，避免最后一个字被截断
            processed_text = text.strip()
            if processed_text and processed_text[-1] not in '。！？.!?，,、；;：:':
                processed_text += '。'

            logger.info(f"开始合成: '{processed_text[:50]}...' (参考: '{ref_text_content[:30]}...')")

            # 准备推理参数
            inputs = {
                "text": processed_text,
                "text_lang": "zh",
                "ref_audio_path": ref_wav,
                "prompt_text": ref_text_content,
                "prompt_lang": "zh",
                "top_k": 5,
                "top_p": 1,
                "temperature": 1,
                "speed_factor": speed,
            }

            # 执行推理
            result_gen = tts.run(inputs)

            # 收集结果
            audio_data = None
            sampling_rate = 32000

            for item in result_gen:
                if isinstance(item, tuple) and len(item) == 2:
                    sampling_rate, audio_data = item
                elif hasattr(item, 'shape'):
                    audio_data = item

            if audio_data is None:
                return {
                    "success": False,
                    "error": "合成失败，没有生成音频",
                }

            # 转换为 WAV 字节
            import numpy as np
            import soundfile as sf

            # 确保是 numpy array
            if not isinstance(audio_data, np.ndarray):
                audio_data = np.array(audio_data)

            wav_buffer = io.BytesIO()
            sf.write(wav_buffer, audio_data, sampling_rate, format='WAV')
            audio_bytes = wav_buffer.getvalue()

            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

            elapsed = time.time() - start_time
            duration = len(audio_data) / sampling_rate

            return {
                "success": True,
                "text": text,
                "soul_name": soul_name,
                "speed": speed,
                "duration_seconds": round(duration, 2),
                "elapsed_seconds": round(elapsed, 3),
                "format": output_format,
                "sample_rate": sampling_rate,
                "audio_base64": audio_base64,
                "audio_size_bytes": len(audio_bytes),
            }

        except ImportError as e:
            logger.error(f"导入 GPT-SoVITS 模块失败: {e}")
            import traceback
            traceback.print_exc()
            # 回退到模拟模式
            return self._synthesize_mock(text, soul_name, speed)

        except Exception as e:
            logger.error(f"合成失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": f"合成失败: {str(e)}",
            }

    def _synthesize_mock(
        self,
        text: str,
        soul_name: str,
        speed: float,
    ) -> Dict[str, Any]:
        """模拟合成 (当 GPT-SoVITS 不可用时)"""
        import struct

        start_time = time.time()

        sample_rate = 32000
        duration = len(text) * 0.15 / speed
        num_samples = int(sample_rate * duration)

        # 生成 WAV 文件头
        wav_buffer = io.BytesIO()
        wav_buffer.write(b'RIFF')
        wav_buffer.write(struct.pack('<I', 36 + num_samples * 2))
        wav_buffer.write(b'WAVE')
        wav_buffer.write(b'fmt ')
        wav_buffer.write(struct.pack('<I', 16))
        wav_buffer.write(struct.pack('<H', 1))
        wav_buffer.write(struct.pack('<H', 1))
        wav_buffer.write(struct.pack('<I', sample_rate))
        wav_buffer.write(struct.pack('<I', sample_rate * 2))
        wav_buffer.write(struct.pack('<H', 2))
        wav_buffer.write(struct.pack('<H', 16))
        wav_buffer.write(b'data')
        wav_buffer.write(struct.pack('<I', num_samples * 2))

        # 生成静音数据
        for _ in range(num_samples):
            wav_buffer.write(struct.pack('<h', 0))

        audio_data = wav_buffer.getvalue()
        audio_base64 = base64.b64encode(audio_data).decode('utf-8')

        elapsed = time.time() - start_time

        return {
            "success": True,
            "text": text,
            "soul_name": soul_name,
            "speed": speed,
            "duration_seconds": round(duration, 2),
            "elapsed_seconds": round(elapsed, 3),
            "format": "wav",
            "sample_rate": sample_rate,
            "audio_base64": audio_base64,
            "audio_size_bytes": len(audio_data),
            "mock": True,  # 标记这是模拟结果
            "warning": "GPT-SoVITS 模块未加载，返回静音音频",
        }

    def get_status(self) -> Dict[str, Any]:
        """获取合成器状态"""
        return {
            "loaded_soul": self.loaded_soul,
            "model_loaded": self.gpt_model_path is not None and self.sovits_model_path is not None,
            "gpt_model": self.gpt_model_path,
            "sovits_model": self.sovits_model_path,
            "ref_audio": self.ref_audio_path,
            "initialized": self._initialized,
        }


# 全局合成器实例
_synthesizer: Optional[VoiceSynthesizer] = None


def get_synthesizer() -> VoiceSynthesizer:
    """获取合成器单例"""
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = VoiceSynthesizer()
    return _synthesizer


def synthesize_voice(
    text: str,
    soul_name: str,
    speed: float = 1.0,
    emotion: Optional[str] = None,
) -> Dict[str, Any]:
    """
    合成语音的便捷函数

    Args:
        text: 要合成的文本
        soul_name: 名称
        speed: 语速
        emotion: 情绪类型

    Returns:
        合成结果
    """
    synthesizer = get_synthesizer()
    return synthesizer.synthesize(text, soul_name, speed=speed, emotion=emotion)
