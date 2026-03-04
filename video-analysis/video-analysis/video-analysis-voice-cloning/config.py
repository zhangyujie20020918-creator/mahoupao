"""
Voice Cloning 项目配置
"""

import os
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR.parent / "downloads"
DATASETS_DIR = BASE_DIR / "datasets"
MODELS_DIR = BASE_DIR / "models"
PRETRAINED_DIR = MODELS_DIR / "pretrained"
TRAINED_DIR = MODELS_DIR / "trained"
OUTPUT_DIR = BASE_DIR / "output"

# 确保目录存在
for d in [DATASETS_DIR, MODELS_DIR, PRETRAINED_DIR, TRAINED_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# Hugging Face 镜像配置 (国内加速)
# ============================================================
HF_MIRROR = "https://hf-mirror.com"
os.environ["HF_ENDPOINT"] = HF_MIRROR
os.environ["HF_HOME"] = str(MODELS_DIR / "hf_cache")
os.environ["HUGGINGFACE_HUB_CACHE"] = str(MODELS_DIR / "hf_cache")

# ============================================================
# GPT-SoVITS 模型配置
# ============================================================
# 预训练模型 (HuggingFace)
PRETRAINED_REPO = "lj1995/GPT-SoVITS"

# 需要下载的预训练文件
PRETRAINED_FILES = {
    "gpt": {
        "filename": "gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt",
        "local_name": "s1_pretrained.ckpt",
        "size_mb": 1500,
    },
    "sovits": {
        "filename": "gsv-v2final-pretrained/s2G2333k.pth",
        "local_name": "s2G_pretrained.pth",
        "size_mb": 800,
    },
    "cnhubert": {
        "filename": "chinese-hubert-base",
        "local_name": "chinese-hubert-base",
        "size_mb": 400,
        "is_folder": True,
    },
}

# BERT 模型配置 (文本处理必需)
BERT_REPO = "hfl/chinese-roberta-wwm-ext-large"
BERT_DIR = PRETRAINED_DIR / "chinese-roberta-wwm-ext-large"

# G2PW 模型 (中文拼音) - 中文多音字处理，提升合成质量
G2PW_REPO = "XXXXRT/GPT-SoVITS-Pretrained"
G2PW_FILENAME = "G2PWModel.zip"
G2PW_DIR = PRETRAINED_DIR / "G2PWModel"
G2PW_OPTIONAL = False  # G2PW 用于提升中文合成质量

# ============================================================
# 数据准备配置
# ============================================================
# 音频切片参数
MIN_DURATION = 3.0      # 最小时长(秒)
MAX_DURATION = 15.0     # 最大时长(秒)
SAMPLE_RATE = 32000     # 采样率 (GPT-SoVITS 推荐)

# ============================================================
# 训练配置
# ============================================================
DEFAULT_EPOCHS_GPT = 15
DEFAULT_EPOCHS_SOVITS = 8
DEFAULT_BATCH_SIZE = 4
DEFAULT_SAVE_EVERY = 4  # 每N个epoch保存一次

# ============================================================
# GPU 检测
# ============================================================
def check_gpu_available() -> dict:
    """检测 GPU 是否可用"""
    result = {
        "available": False,
        "name": None,
        "memory_gb": None,
        "error": None,
    }

    try:
        import torch
        if torch.cuda.is_available():
            result["available"] = True
            result["name"] = torch.cuda.get_device_name(0)
            result["memory_gb"] = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
    except Exception as e:
        result["error"] = str(e)

    return result


# 初始化时检测
_gpu_info = check_gpu_available()
GPU_AVAILABLE = _gpu_info["available"]
GPU_NAME = _gpu_info.get("name")
GPU_MEMORY = _gpu_info.get("memory_gb")

# 设备配置
DEVICE = "cuda" if GPU_AVAILABLE else "cpu"

# ============================================================
# API 配置
# ============================================================
API_PORT = 8003
