"""
数据清洗项目配置
"""

import os
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR.parent / "downloads"
OUTPUT_DIR = BASE_DIR / "output"
MODELS_DIR = BASE_DIR / "models"

# 确保目录存在
MODELS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# Hugging Face 镜像配置 (国内加速)
# ============================================================
HF_MIRROR = "https://hf-mirror.com"
os.environ["HF_ENDPOINT"] = HF_MIRROR

# 模型缓存目录设置为本地 models 文件夹
os.environ["HF_HOME"] = str(MODELS_DIR)
os.environ["HUGGINGFACE_HUB_CACHE"] = str(MODELS_DIR / "hub")

# ============================================================
# FFmpeg 配置
# ============================================================
FFMPEG_PATH = "ffmpeg"

# MP3 输出配置
MP3_BITRATE = "192k"

# ============================================================
# Whisper 模型配置
# ============================================================
# 可选模型: tiny, base, small, medium, large-v2, large-v3
WHISPER_MODEL = "medium"

# 模型 Repo ID (faster-whisper 格式)
WHISPER_MODEL_REPO = f"Systran/faster-whisper-{WHISPER_MODEL}"

# 模型本地路径
WHISPER_MODEL_PATH = MODELS_DIR / f"faster-whisper-{WHISPER_MODEL}"

# ============================================================
# GPU 检测 - 必须在 import torch 之前设置 DLL 路径
# ============================================================
def _add_cuda_dll_paths():
    """将 CUDA DLL 路径添加到 Windows DLL 搜索路径 (针对 pip 安装的 nvidia 包)"""
    import sys

    print(f"[GPU] Python prefix: {sys.prefix}")

    # 查找 nvidia cublas 的 bin 目录
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    cuda_paths = [
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "nvidia" / "cuda_runtime" / "bin",
    ]

    # 使用 os.add_dll_directory (Python 3.8+ Windows)
    for cuda_path in cuda_paths:
        if cuda_path.exists():
            print(f"[GPU] Adding DLL path: {cuda_path}")
            try:
                os.add_dll_directory(str(cuda_path))
            except (AttributeError, OSError) as e:
                print(f"[GPU] add_dll_directory failed: {e}, using PATH")
                # 非 Windows 或旧版 Python，回退到 PATH 方式
                path_str = str(cuda_path)
                if path_str not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = path_str + os.pathsep + os.environ.get("PATH", "")
        else:
            print(f"[GPU] Path not found: {cuda_path}")


# 立即调用，在任何 torch/ctranslate2 导入之前
_add_cuda_dll_paths()


def check_gpu_available() -> dict:
    """检测 GPU 是否可用"""
    result = {
        "cuda_available": False,
        "gpu_name": None,
        "cuda_version": None,
        "error": None,
    }

    try:
        import torch
        print(f"[GPU] PyTorch CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            result["cuda_available"] = True
            result["gpu_name"] = torch.cuda.get_device_name(0)
            result["cuda_version"] = torch.version.cuda
            print(f"[GPU] Found: {result['gpu_name']}")
    except ImportError as e:
        print(f"[GPU] PyTorch not installed: {e}")
        # torch 未安装，尝试其他方式检测
        try:
            import ctranslate2
            result["cuda_available"] = "cuda" in ctranslate2.get_supported_compute_types()
        except Exception:
            pass
    except Exception as e:
        print(f"[GPU] PyTorch error: {e}")
        result["error"] = str(e)

    # 检查 cuBLAS 是否可用
    if result["cuda_available"]:
        try:
            import ctypes
            ctypes.CDLL("cublas64_12.dll")
            print("[GPU] cuBLAS loaded OK")
        except OSError as e:
            print(f"[GPU] cuBLAS failed: {e}")
            result["cuda_available"] = False
            result["error"] = "cublas64_12.dll 未找到，请安装: pip install nvidia-cublas-cu12"

    print(f"[GPU] Final result: available={result['cuda_available']}, name={result['gpu_name']}")
    return result

# 检测 GPU
_gpu_info = check_gpu_available()
GPU_AVAILABLE = _gpu_info["cuda_available"]
GPU_NAME = _gpu_info.get("gpu_name")
GPU_ERROR = _gpu_info.get("error")

# ============================================================
# 设备配置 (可通过 API 动态修改)
# ============================================================
# 默认: 如果 GPU 可用就用 GPU，否则用 CPU
DEFAULT_DEVICE = "cuda" if GPU_AVAILABLE else "cpu"
DEFAULT_COMPUTE_TYPE = "float16" if GPU_AVAILABLE else "int8"

# 当前配置 (可被 API 修改)
DEVICE = DEFAULT_DEVICE
COMPUTE_TYPE = DEFAULT_COMPUTE_TYPE

# ============================================================
# 输出格式
# ============================================================
OUTPUT_FORMAT = "all"
