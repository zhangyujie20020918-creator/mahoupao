"""
训练服务
GPT-SoVITS 模型微调训练

这个模块集成了真正的 GPT-SoVITS 训练流程
"""

import json
import logging
from pathlib import Path
from typing import Generator, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime

import config
from services.gpt_sovits_trainer import (
    full_training_pipeline,
    check_training_data,
    get_exp_dir,
)

logger = logging.getLogger(__name__)


@dataclass
class TrainingConfig:
    """训练配置"""
    blogger_name: str
    epochs_gpt: int = config.DEFAULT_EPOCHS_GPT
    epochs_sovits: int = config.DEFAULT_EPOCHS_SOVITS
    batch_size: int = config.DEFAULT_BATCH_SIZE
    save_every: int = config.DEFAULT_SAVE_EVERY
    learning_rate: float = 0.0001


def get_trained_model_info(blogger_name: str) -> Dict[str, Any]:
    """获取已训练模型的信息"""
    model_dir = config.TRAINED_DIR / blogger_name

    if not model_dir.exists():
        return {"exists": False, "ready": False}

    result = {
        "exists": True,
        "blogger_name": blogger_name,
        "model_dir": str(model_dir),
        "models": {},
    }

    # 检查 GPT 模型
    gpt_model = model_dir / "gpt.ckpt"
    if gpt_model.exists():
        result["models"]["gpt"] = {
            "exists": True,
            "path": str(gpt_model),
            "size_mb": round(gpt_model.stat().st_size / 1e6, 1),
        }
    else:
        result["models"]["gpt"] = {"exists": False}

    # 检查 SoVITS 模型
    sovits_model = model_dir / "sovits.pth"
    if sovits_model.exists():
        result["models"]["sovits"] = {
            "exists": True,
            "path": str(sovits_model),
            "size_mb": round(sovits_model.stat().st_size / 1e6, 1),
        }
    else:
        result["models"]["sovits"] = {"exists": False}

    # 检查训练日志
    log_file = model_dir / "training_log.json"
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            result["training_log"] = json.load(f)

    result["ready"] = (
        result["models"].get("gpt", {}).get("exists", False) and
        result["models"].get("sovits", {}).get("exists", False)
    )

    return result


def train_model_stream(
    blogger_name: str,
    epochs_gpt: int = None,
    epochs_sovits: int = None,
    batch_size: int = None,
) -> Generator[Dict[str, Any], None, None]:
    """
    训练模型 (流式输出进度和loss)

    使用真正的 GPT-SoVITS 训练流程

    Args:
        blogger_name: 博主名称
        epochs_gpt: GPT 训练轮数
        epochs_sovits: SoVITS 训练轮数
        batch_size: 批次大小

    Yields:
        进度信息字典 (包含 loss 数据用于绘制曲线)
    """
    cfg = TrainingConfig(
        blogger_name=blogger_name,
        epochs_gpt=epochs_gpt or config.DEFAULT_EPOCHS_GPT,
        epochs_sovits=epochs_sovits or config.DEFAULT_EPOCHS_SOVITS,
        batch_size=batch_size or config.DEFAULT_BATCH_SIZE,
    )

    # 检查数据集
    dataset_dir = config.DATASETS_DIR / blogger_name
    list_file = dataset_dir / f"{blogger_name}.list"

    if not list_file.exists():
        yield {"type": "error", "message": "训练数据不存在，请先准备数据"}
        return

    # 检查训练数据
    data_check = check_training_data(blogger_name)
    if not data_check["ready"]:
        for error in data_check.get("errors", []):
            yield {"type": "error", "message": error}
        return

    # 创建模型输出目录
    model_dir = config.TRAINED_DIR / blogger_name
    model_dir.mkdir(parents=True, exist_ok=True)

    # 训练日志
    training_log = {
        "blogger_name": blogger_name,
        "config": asdict(cfg),
        "started_at": datetime.now().isoformat(),
        "gpt_losses": [],
        "sovits_losses": [],
        "device": config.DEVICE,
        "gpu": config.GPU_NAME,
    }

    # 运行真正的 GPT-SoVITS 训练
    for progress in full_training_pipeline(
        blogger_name=blogger_name,
        epochs_gpt=cfg.epochs_gpt,
        epochs_sovits=cfg.epochs_sovits,
        batch_size=cfg.batch_size,
        skip_prepare=False,  # 总是运行预处理
    ):
        # 记录 loss
        if progress.get("type") == "progress":
            phase = progress.get("phase")
            loss = progress.get("loss")
            epoch = progress.get("epoch")

            if loss is not None and epoch is not None:
                loss_entry = {"epoch": epoch, "loss": round(loss, 4)}

                if phase == "gpt":
                    # 避免重复记录同一 epoch
                    if not training_log["gpt_losses"] or training_log["gpt_losses"][-1]["epoch"] != epoch:
                        training_log["gpt_losses"].append(loss_entry)
                elif phase == "sovits":
                    if not training_log["sovits_losses"] or training_log["sovits_losses"][-1]["epoch"] != epoch:
                        training_log["sovits_losses"].append(loss_entry)

        # 转发进度
        yield progress

        # 检查是否完成或出错
        if progress.get("type") == "done":
            # 保存训练日志
            training_log["finished_at"] = datetime.now().isoformat()
            training_log["total_seconds"] = progress.get("total_seconds", 0)
            training_log["gpt_final_loss"] = training_log["gpt_losses"][-1]["loss"] if training_log["gpt_losses"] else None
            training_log["sovits_final_loss"] = training_log["sovits_losses"][-1]["loss"] if training_log["sovits_losses"] else None

            log_file = model_dir / "training_log.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(training_log, f, ensure_ascii=False, indent=2)

            # 添加最终 loss 信息到完成消息
            yield {
                "type": "done",
                "message": "训练完成！",
                "model_dir": str(model_dir),
                "gpt_model": str(model_dir / "gpt.ckpt"),
                "sovits_model": str(model_dir / "sovits.pth"),
                "total_seconds": progress.get("total_seconds", 0),
                "gpt_final_loss": training_log["gpt_final_loss"],
                "sovits_final_loss": training_log["sovits_final_loss"],
            }
            return

        if progress.get("type") == "error":
            # 保存部分日志
            training_log["error"] = progress.get("message")
            training_log["finished_at"] = datetime.now().isoformat()

            log_file = model_dir / "training_log.json"
            with open(log_file, "w", encoding="utf-8") as f:
                json.dump(training_log, f, ensure_ascii=False, indent=2)
            return
