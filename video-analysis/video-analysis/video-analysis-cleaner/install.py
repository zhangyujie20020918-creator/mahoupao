"""
智能安装脚本 - 自动检测 GPU 并安装对应版本的 PyTorch
"""

import subprocess
import sys


def check_nvidia_gpu():
    """检测是否有 NVIDIA GPU"""
    try:
        result = subprocess.run(
            ["nvidia-smi"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def install_requirements():
    """安装基础依赖"""
    print("=" * 60)
    print("安装基础依赖...")
    print("=" * 60)

    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "fastapi>=0.104.0",
        "uvicorn>=0.24.0",
        "pydub>=0.25.1",
        "faster-whisper>=0.10.0",
        "huggingface-hub>=0.20.0",
        "python-multipart>=0.0.6",
    ], check=True)


def install_torch(has_gpu: bool):
    """安装 PyTorch"""
    print("=" * 60)
    if has_gpu:
        print("检测到 NVIDIA GPU，安装 PyTorch CUDA 版本...")
        print("=" * 60)
        subprocess.run([
            sys.executable, "-m", "pip", "install",
            "torch",
            "--index-url", "https://download.pytorch.org/whl/cu121",
        ], check=True)

        # 安装 CUDA 支持库
        print("\n安装 CUDA 支持库...")
        subprocess.run([
            sys.executable, "-m", "pip", "install",
            "nvidia-cublas-cu12",
            "nvidia-cudnn-cu12",
        ], check=True)
    else:
        print("未检测到 NVIDIA GPU，安装 PyTorch CPU 版本...")
        print("=" * 60)
        subprocess.run([
            sys.executable, "-m", "pip", "install",
            "torch",
            "--index-url", "https://download.pytorch.org/whl/cpu",
        ], check=True)


def main():
    print("=" * 60)
    print("数据清洗项目 - 智能安装")
    print("=" * 60)
    print(f"Python: {sys.executable}")
    print()

    # 检测 GPU
    has_gpu = check_nvidia_gpu()
    if has_gpu:
        print("检测结果: 发现 NVIDIA GPU")
    else:
        print("检测结果: 未发现 NVIDIA GPU")
    print()

    # 安装依赖
    install_requirements()
    install_torch(has_gpu)

    print()
    print("=" * 60)
    print("安装完成！")
    print("运行服务: python run_server.py")
    print("=" * 60)


if __name__ == "__main__":
    main()
