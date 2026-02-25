"""
模型下载服务
下载 GPT-SoVITS 预训练模型
"""

import logging
import zipfile
from pathlib import Path
from typing import Generator, Dict, Any

from huggingface_hub import hf_hub_download, snapshot_download

import config

logger = logging.getLogger(__name__)


def check_pretrained_models() -> Dict[str, Any]:
    """检查预训练模型状态"""
    result = {
        "all_ready": True,
        "gpt": False,
        "sovits": False,
        "bert": False,  # cnhubert
        "roberta": False,  # chinese-roberta-wwm-ext-large (文本处理必需)
        "g2pw": False,
        "models": {},
    }

    for key, info in config.PRETRAINED_FILES.items():
        local_path = config.PRETRAINED_DIR / info["local_name"]

        if info.get("is_folder"):
            exists = local_path.exists() and local_path.is_dir()
        else:
            exists = local_path.exists() and local_path.is_file()

        result["models"][key] = {
            "name": info["local_name"],
            "exists": exists,
            "size_mb": info["size_mb"],
            "path": str(local_path),
        }

        # 设置顶层布尔值
        if key == "gpt":
            result["gpt"] = exists
        elif key == "sovits":
            result["sovits"] = exists
        elif key == "cnhubert":
            result["bert"] = exists

        if not exists:
            result["all_ready"] = False

    # 检查 G2PW
    g2pw_exists = config.G2PW_DIR.exists() and any(config.G2PW_DIR.iterdir()) if config.G2PW_DIR.exists() else False
    result["models"]["g2pw"] = {
        "name": "G2PWModel",
        "exists": g2pw_exists,
        "size_mb": 200,
        "path": str(config.G2PW_DIR),
    }
    result["g2pw"] = g2pw_exists

    if not g2pw_exists:
        result["all_ready"] = False

    # 检查 BERT (chinese-roberta-wwm-ext-large) - 文本处理必需
    bert_dir = config.BERT_DIR
    bert_exists = bert_dir.exists() and any(bert_dir.iterdir()) if bert_dir.exists() else False
    result["models"]["roberta"] = {
        "name": "chinese-roberta-wwm-ext-large",
        "exists": bert_exists,
        "size_mb": 1300,
        "path": str(bert_dir),
    }
    result["roberta"] = bert_exists

    if not bert_exists:
        result["all_ready"] = False

    return result


def download_pretrained_stream() -> Generator[Dict[str, Any], None, None]:
    """
    下载预训练模型 (流式输出进度)

    Yields:
        进度信息字典
    """
    yield {"type": "start", "message": "开始下载预训练模型"}

    total_models = len(config.PRETRAINED_FILES) + 1  # +1 for G2PW
    current = 0

    # 下载 GPT-SoVITS 预训练模型
    for key, info in config.PRETRAINED_FILES.items():
        current += 1
        local_path = config.PRETRAINED_DIR / info["local_name"]

        # 跳过已存在的
        if info.get("is_folder"):
            if local_path.exists() and local_path.is_dir():
                yield {
                    "type": "progress",
                    "current": current,
                    "total": total_models,
                    "model": info["local_name"],
                    "status": "skipped",
                    "message": f"{info['local_name']} 已存在，跳过",
                }
                continue
        else:
            if local_path.exists():
                yield {
                    "type": "progress",
                    "current": current,
                    "total": total_models,
                    "model": info["local_name"],
                    "status": "skipped",
                    "message": f"{info['local_name']} 已存在，跳过",
                }
                continue

        yield {
            "type": "progress",
            "current": current,
            "total": total_models,
            "model": info["local_name"],
            "status": "downloading",
            "message": f"正在下载 {info['local_name']} (~{info['size_mb']}MB)",
        }

        try:
            if info.get("is_folder"):
                # 下载整个文件夹
                snapshot_download(
                    repo_id=config.PRETRAINED_REPO,
                    allow_patterns=f"{info['filename']}/*",
                    local_dir=config.PRETRAINED_DIR,
                    local_dir_use_symlinks=False,
                )
            else:
                # 下载单个文件
                downloaded_path = hf_hub_download(
                    repo_id=config.PRETRAINED_REPO,
                    filename=info["filename"],
                    local_dir=config.PRETRAINED_DIR,
                    local_dir_use_symlinks=False,
                )

                # 重命名到目标位置
                downloaded = Path(downloaded_path)
                if downloaded.exists() and downloaded != local_path:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    downloaded.rename(local_path)

            yield {
                "type": "progress",
                "current": current,
                "total": total_models,
                "model": info["local_name"],
                "status": "done",
                "message": f"{info['local_name']} 下载完成",
            }

        except Exception as e:
            logger.error(f"下载 {info['local_name']} 失败: {e}")
            yield {
                "type": "error",
                "model": info["local_name"],
                "message": f"下载失败: {str(e)}",
            }

    # 下载 G2PW 模型 (中文多音字处理)
    current += 1

    # 检查 G2PW 是否已存在且有内容
    g2pw_ready = config.G2PW_DIR.exists() and any(config.G2PW_DIR.iterdir()) if config.G2PW_DIR.exists() else False

    if g2pw_ready:
        yield {
            "type": "progress",
            "current": current,
            "total": total_models,
            "model": "G2PWModel",
            "status": "skipped",
            "message": "G2PWModel 已存在，跳过",
        }
    else:
        yield {
            "type": "progress",
            "current": current,
            "total": total_models,
            "model": "G2PWModel",
            "status": "downloading",
            "message": "正在下载 G2PWModel (~200MB)",
        }

        try:
            # 下载 G2PWModel.zip
            zip_path = hf_hub_download(
                repo_id=config.G2PW_REPO,
                filename=config.G2PW_FILENAME,
                local_dir=config.PRETRAINED_DIR,
                local_dir_use_symlinks=False,
            )

            yield {
                "type": "progress",
                "current": current,
                "total": total_models,
                "model": "G2PWModel",
                "status": "extracting",
                "message": "正在解压 G2PWModel...",
            }

            # 解压到目标目录
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(config.PRETRAINED_DIR)

            # 删除 zip 文件
            Path(zip_path).unlink(missing_ok=True)

            yield {
                "type": "progress",
                "current": current,
                "total": total_models,
                "model": "G2PWModel",
                "status": "done",
                "message": "G2PWModel 下载完成",
            }

        except Exception as e:
            logger.error(f"下载 G2PWModel 失败: {e}")
            if getattr(config, 'G2PW_OPTIONAL', False):
                yield {
                    "type": "warning",
                    "model": "G2PWModel",
                    "message": f"G2PWModel 下载失败 (可选): {str(e)}",
                }
            else:
                yield {
                    "type": "error",
                    "model": "G2PWModel",
                    "message": f"下载失败: {str(e)}",
                }

    # 下载 BERT 模型 (chinese-roberta-wwm-ext-large) - 文本处理必需
    current += 1

    bert_dir = config.BERT_DIR
    bert_ready = bert_dir.exists() and any(bert_dir.iterdir()) if bert_dir.exists() else False

    if bert_ready:
        yield {
            "type": "progress",
            "current": current,
            "total": total_models + 1,  # +1 for BERT
            "model": "chinese-roberta-wwm-ext-large",
            "status": "skipped",
            "message": "chinese-roberta-wwm-ext-large 已存在，跳过",
        }
    else:
        yield {
            "type": "progress",
            "current": current,
            "total": total_models + 1,
            "model": "chinese-roberta-wwm-ext-large",
            "status": "downloading",
            "message": "正在下载 chinese-roberta-wwm-ext-large (~1.3GB)",
        }

        try:
            # 下载 BERT 模型
            snapshot_download(
                repo_id=config.BERT_REPO,
                local_dir=bert_dir,
                local_dir_use_symlinks=False,
            )

            yield {
                "type": "progress",
                "current": current,
                "total": total_models + 1,
                "model": "chinese-roberta-wwm-ext-large",
                "status": "done",
                "message": "chinese-roberta-wwm-ext-large 下载完成",
            }

        except Exception as e:
            logger.error(f"下载 chinese-roberta-wwm-ext-large 失败: {e}")
            yield {
                "type": "error",
                "model": "chinese-roberta-wwm-ext-large",
                "message": f"下载失败: {str(e)}",
            }

    yield {
        "type": "done",
        "message": "模型下载完成",
    }


def download_single_model_stream(model_key: str) -> Generator[Dict[str, Any], None, None]:
    """
    下载单个模型 (流式输出进度)

    Args:
        model_key: 模型标识 (gpt, sovits, cnhubert, g2pw, roberta)

    Yields:
        进度信息字典
    """
    yield {"type": "start", "message": f"开始下载 {model_key}"}

    # GPT-SoVITS 预训练模型
    if model_key in config.PRETRAINED_FILES:
        info = config.PRETRAINED_FILES[model_key]
        local_path = config.PRETRAINED_DIR / info["local_name"]

        # 检查是否已存在
        if info.get("is_folder"):
            if local_path.exists() and local_path.is_dir():
                yield {"type": "done", "message": f"{info['local_name']} 已存在"}
                return
        else:
            if local_path.exists():
                yield {"type": "done", "message": f"{info['local_name']} 已存在"}
                return

        yield {
            "type": "progress",
            "percent": 10,
            "model": info["local_name"],
            "message": f"正在下载 {info['local_name']} (~{info['size_mb']}MB)",
        }

        try:
            if info.get("is_folder"):
                snapshot_download(
                    repo_id=config.PRETRAINED_REPO,
                    allow_patterns=f"{info['filename']}/*",
                    local_dir=config.PRETRAINED_DIR,
                    local_dir_use_symlinks=False,
                )
            else:
                downloaded_path = hf_hub_download(
                    repo_id=config.PRETRAINED_REPO,
                    filename=info["filename"],
                    local_dir=config.PRETRAINED_DIR,
                    local_dir_use_symlinks=False,
                )
                downloaded = Path(downloaded_path)
                if downloaded.exists() and downloaded != local_path:
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    downloaded.rename(local_path)

            yield {"type": "done", "percent": 100, "message": f"{info['local_name']} 下载完成"}

        except Exception as e:
            logger.error(f"下载 {info['local_name']} 失败: {e}")
            yield {"type": "error", "message": f"下载失败: {str(e)}"}

    # G2PW 模型
    elif model_key == "g2pw":
        g2pw_ready = config.G2PW_DIR.exists() and any(config.G2PW_DIR.iterdir()) if config.G2PW_DIR.exists() else False

        if g2pw_ready:
            yield {"type": "done", "message": "G2PWModel 已存在"}
            return

        yield {
            "type": "progress",
            "percent": 10,
            "model": "G2PWModel",
            "message": "正在下载 G2PWModel (~200MB)",
        }

        try:
            zip_path = hf_hub_download(
                repo_id=config.G2PW_REPO,
                filename=config.G2PW_FILENAME,
                local_dir=config.PRETRAINED_DIR,
                local_dir_use_symlinks=False,
            )

            yield {
                "type": "progress",
                "percent": 80,
                "model": "G2PWModel",
                "message": "正在解压 G2PWModel...",
            }

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(config.PRETRAINED_DIR)

            Path(zip_path).unlink(missing_ok=True)

            yield {"type": "done", "percent": 100, "message": "G2PWModel 下载完成"}

        except Exception as e:
            logger.error(f"下载 G2PWModel 失败: {e}")
            yield {"type": "error", "message": f"下载失败: {str(e)}"}

    # RoBERTa BERT 模型
    elif model_key == "roberta":
        bert_dir = config.BERT_DIR
        bert_ready = bert_dir.exists() and any(bert_dir.iterdir()) if bert_dir.exists() else False

        if bert_ready:
            yield {"type": "done", "message": "chinese-roberta-wwm-ext-large 已存在"}
            return

        yield {
            "type": "progress",
            "percent": 10,
            "model": "chinese-roberta-wwm-ext-large",
            "message": "正在下载 chinese-roberta-wwm-ext-large (~1.3GB)",
        }

        try:
            snapshot_download(
                repo_id=config.BERT_REPO,
                local_dir=bert_dir,
                local_dir_use_symlinks=False,
            )

            yield {"type": "done", "percent": 100, "message": "chinese-roberta-wwm-ext-large 下载完成"}

        except Exception as e:
            logger.error(f"下载 chinese-roberta-wwm-ext-large 失败: {e}")
            yield {"type": "error", "message": f"下载失败: {str(e)}"}

    else:
        yield {"type": "error", "message": f"未知的模型: {model_key}"}
