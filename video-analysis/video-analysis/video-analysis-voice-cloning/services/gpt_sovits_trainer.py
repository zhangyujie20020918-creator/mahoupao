"""
GPT-SoVITS 训练集成
真正调用 GPT-SoVITS 进行训练
"""

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
import yaml
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Generator, Dict, Any, Optional

import config

logger = logging.getLogger(__name__)

# GPT-SoVITS 源码路径
GPT_SOVITS_ROOT = config.BASE_DIR / "GPT_SoVITS_src"
GPT_SOVITS_DIR = GPT_SOVITS_ROOT / "GPT_SoVITS"

# Python 可执行文件
PYTHON_EXEC = sys.executable


@dataclass
class TrainConfig:
    """训练配置"""
    blogger_name: str
    exp_name: str
    epochs_gpt: int = 15
    epochs_sovits: int = 8
    batch_size: int = 4
    version: str = "v2"


def setup_environment():
    """设置 GPT-SoVITS 环境变量"""
    os.environ["is_half"] = "True" if config.GPU_AVAILABLE else "False"
    os.environ["version"] = "v2"

    # 添加 GPT-SoVITS 到 Python 路径
    gpt_sovits_path = str(GPT_SOVITS_ROOT)
    if gpt_sovits_path not in sys.path:
        sys.path.insert(0, gpt_sovits_path)


def get_ascii_safe_name(name: str) -> str:
    """
    将中文名称转换为 ASCII 安全的标识符
    用于避免 Windows subprocess 中的编码问题
    """
    # 使用 MD5 哈希的前 12 位作为唯一标识符
    hash_part = hashlib.md5(name.encode('utf-8')).hexdigest()[:12]
    return f"exp_{hash_part}"


def get_exp_dir(blogger_name: str) -> Path:
    """获取实验目录"""
    return config.DATASETS_DIR / blogger_name


def get_list_file(blogger_name: str) -> Path:
    """获取 .list 文件路径"""
    return get_exp_dir(blogger_name) / f"{blogger_name}.list"


def check_training_data(blogger_name: str) -> Dict[str, Any]:
    """检查训练数据是否就绪"""
    exp_dir = get_exp_dir(blogger_name)
    list_file = get_list_file(blogger_name)

    result = {
        "ready": False,
        "list_file_exists": list_file.exists(),
        "audio_count": 0,
        "errors": [],
    }

    if not list_file.exists():
        result["errors"].append(f"训练列表文件不存在: {list_file}")
        return result

    # 统计音频数量
    with open(list_file, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
        result["audio_count"] = len(lines)

    if result["audio_count"] < 10:
        result["errors"].append(f"训练数据太少: {result['audio_count']} 条 (建议至少 10 条)")
        return result

    result["ready"] = True
    return result


def run_prepare_step(
    step_name: str,
    script_path: str,
    env_config: Dict[str, str],
    cwd: Path,
) -> Generator[Dict[str, Any], None, bool]:
    """
    运行数据准备步骤

    Args:
        step_name: 步骤名称
        script_path: 脚本路径
        env_config: 环境变量配置
        cwd: 工作目录

    Yields:
        进度信息

    Returns:
        是否成功
    """
    yield {
        "type": "step_start",
        "step": step_name,
        "message": f"开始 {step_name}...",
    }

    # 设置环境变量
    env = os.environ.copy()
    env.update(env_config)

    # 设置正确的编码以支持中文路径
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # 设置 PYTHONPATH 以包含 GPT-SoVITS 模块
    python_path = os.pathsep.join([
        str(GPT_SOVITS_ROOT),
        str(GPT_SOVITS_DIR),
        env.get("PYTHONPATH", ""),
    ])
    env["PYTHONPATH"] = python_path

    cmd = [PYTHON_EXEC, script_path]

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8',
            errors='replace',
        )

        for line in process.stdout:
            line = line.strip()
            if line:
                yield {
                    "type": "log",
                    "step": step_name,
                    "message": line,
                }

        process.wait()

        if process.returncode == 0:
            yield {
                "type": "step_done",
                "step": step_name,
                "message": f"{step_name} 完成",
            }
            return True
        else:
            yield {
                "type": "step_error",
                "step": step_name,
                "message": f"{step_name} 失败 (返回码: {process.returncode})",
            }
            return False

    except Exception as e:
        yield {
            "type": "step_error",
            "step": step_name,
            "message": f"{step_name} 异常: {str(e)}",
        }
        return False


def prepare_training_data(
    blogger_name: str,
) -> Generator[Dict[str, Any], None, bool]:
    """
    准备训练数据 (运行 GPT-SoVITS 的预处理脚本)

    1. 1-get-text.py - 获取 BERT 特征
    2. 2-get-hubert-wav32k.py - 获取 HuBERT 特征
    3. 3-get-semantic.py - 获取语义 tokens
    """
    setup_environment()

    exp_dir = get_exp_dir(blogger_name)
    list_file = get_list_file(blogger_name)

    if not list_file.exists():
        yield {"type": "error", "message": f"训练数据文件不存在: {list_file}"}
        return False

    # 音频目录 (从 datasets 中获取，list 文件使用相对路径 audio/xxxx.wav)
    wav_dir = exp_dir
    audio_dir = exp_dir / "audio"
    if not audio_dir.exists():
        yield {"type": "error", "message": f"音频目录不存在: {audio_dir}"}
        return False

    # 清理旧的中间文件（强制重新生成）
    yield {"type": "phase", "phase": "prepare", "message": "清理旧的训练数据..."}
    import shutil
    for pattern in ["2-name2text*.txt", "6-name2semantic*.tsv"]:
        for f in exp_dir.glob(pattern):
            f.unlink()
    for subdir in ["3-bert", "4-cnhubert", "5-wav32k", "logs_s1", "logs_s2"]:
        subdir_path = exp_dir / subdir
        if subdir_path.exists():
            shutil.rmtree(subdir_path)

    # 基础配置
    # inp_wav_dir 指向 audio 目录，因为 GPT-SoVITS 会用 os.path.basename 处理 list 中的路径
    base_config = {
        "inp_text": str(list_file),
        "inp_wav_dir": str(audio_dir),
        "exp_name": blogger_name,
        "opt_dir": str(exp_dir),
        "is_half": "True" if config.GPU_AVAILABLE else "False",
        "version": "v2",
        "i_part": "0",
        "all_parts": "1",
        "_CUDA_VISIBLE_DEVICES": "0" if config.GPU_AVAILABLE else "",
    }

    # 预训练模型路径
    bert_dir = config.PRETRAINED_DIR / "chinese-roberta-wwm-ext-large"  # 文本处理用 RoBERTa
    cnhubert_dir = config.PRETRAINED_DIR / "chinese-hubert-base"  # 音频处理用 HuBERT
    g2pw_dir = config.PRETRAINED_DIR / "G2PWModel"  # G2PW 拼音模型

    # Step 1: 获取文本特征 (BERT)
    yield {"type": "phase", "phase": "prepare", "message": "Step 1/3: 提取文本特征"}

    step1_config = base_config.copy()
    step1_config["bert_pretrained_dir"] = str(bert_dir)
    step1_config["cnhubert_base_dir"] = str(cnhubert_dir)
    # G2PW 需要的路径
    step1_config["bert_path"] = str(bert_dir)
    step1_config["g2pw_path"] = str(g2pw_dir)

    script1 = str(GPT_SOVITS_DIR / "prepare_datasets" / "1-get-text.py")

    success = True
    for progress in run_prepare_step("文本特征提取", script1, step1_config, GPT_SOVITS_ROOT):
        yield progress
        if progress.get("type") == "step_error":
            success = False

    if not success:
        return False

    # Step 2: 获取 HuBERT 特征
    yield {"type": "phase", "phase": "prepare", "message": "Step 2/3: 提取音频特征 (HuBERT)"}

    step2_config = base_config.copy()
    step2_config["cnhubert_base_dir"] = str(cnhubert_dir)

    script2 = str(GPT_SOVITS_DIR / "prepare_datasets" / "2-get-hubert-wav32k.py")

    for progress in run_prepare_step("音频特征提取", script2, step2_config, GPT_SOVITS_ROOT):
        yield progress
        if progress.get("type") == "step_error":
            success = False

    if not success:
        return False

    # Step 3: 获取语义 tokens
    yield {"type": "phase", "phase": "prepare", "message": "Step 3/3: 生成语义表示"}

    step3_config = base_config.copy()
    step3_config["s2config_path"] = str(GPT_SOVITS_DIR / "configs" / "s2.json")

    # 需要预训练的 SoVITS 模型
    sovits_pretrained = config.PRETRAINED_DIR / "s2G_pretrained.pth"
    step3_config["pretrained_s2G"] = str(sovits_pretrained)

    script3 = str(GPT_SOVITS_DIR / "prepare_datasets" / "3-get-semantic.py")

    for progress in run_prepare_step("语义表示生成", script3, step3_config, GPT_SOVITS_ROOT):
        yield progress
        if progress.get("type") == "step_error":
            success = False

    if not success:
        return False

    # Step 4: 合并分片文件
    yield {"type": "phase", "phase": "prepare", "message": "合并数据文件..."}

    # 合并 2-name2text-*.txt -> 2-name2text.txt
    text_files = sorted(exp_dir.glob("2-name2text-*.txt"))
    if text_files:
        with open(exp_dir / "2-name2text.txt", "w", encoding="utf-8") as out_f:
            for f in text_files:
                with open(f, "r", encoding="utf-8") as in_f:
                    content = in_f.read().strip()
                    if content:
                        out_f.write(content + "\n")

    # 合并 6-name2semantic-*.tsv -> 6-name2semantic.tsv
    semantic_files = sorted(exp_dir.glob("6-name2semantic-*.tsv"))
    if semantic_files:
        with open(exp_dir / "6-name2semantic.tsv", "w", encoding="utf-8") as out_f:
            for f in semantic_files:
                with open(f, "r", encoding="utf-8") as in_f:
                    content = in_f.read().strip()
                    if content:
                        out_f.write(content + "\n")

    yield {"type": "step_done", "step": "合并文件", "message": "数据文件合并完成"}

    return success


def parse_training_output(line: str) -> Optional[Dict[str, Any]]:
    """解析训练输出，提取 loss 和进度信息"""
    # PyTorch Lightning 输出格式
    # Epoch 1: 100%|██████████| 100/100 [00:30<00:00, loss=0.123]

    # 匹配 epoch
    epoch_match = re.search(r"Epoch\s+(\d+)", line)

    # 匹配 loss
    loss_match = re.search(r"loss[=:]\s*([\d.]+)", line, re.IGNORECASE)

    # 匹配进度百分比
    progress_match = re.search(r"(\d+)%", line)

    # 匹配 step
    step_match = re.search(r"(\d+)/(\d+)", line)

    result = {}

    if epoch_match:
        result["epoch"] = int(epoch_match.group(1))

    if loss_match:
        result["loss"] = float(loss_match.group(1))

    if progress_match:
        result["percent"] = int(progress_match.group(1))

    if step_match:
        result["step"] = int(step_match.group(1))
        result["total_steps"] = int(step_match.group(2))

    return result if result else None


def train_gpt_model(
    blogger_name: str,
    epochs: int = 15,
    batch_size: int = 4,
) -> Generator[Dict[str, Any], None, bool]:
    """
    训练 GPT 模型 (Stage 1)
    """
    setup_environment()

    exp_dir = get_exp_dir(blogger_name)
    output_dir = exp_dir / "logs_s1"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 使用 ASCII 安全的名称，避免 Windows 子进程编码问题
    ascii_safe_name = get_ascii_safe_name(blogger_name)

    # 使用 ASCII 安全路径保存权重（在 BASE_DIR 下，避免中文路径）
    weights_dir = config.BASE_DIR / "weights_temp" / ascii_safe_name / "s1"
    weights_dir.mkdir(parents=True, exist_ok=True)

    # 生成训练配置
    config_data = {
        "train": {
            "seed": 1234,
            "epochs": epochs,
            "batch_size": batch_size,
            "save_every_n_epoch": max(1, epochs // 5),
            "precision": "16-mixed" if config.GPU_AVAILABLE else "32",
            "gradient_clip": 1.0,
            "if_save_latest": True,
            "if_save_every_weights": True,
            "half_weights_save_dir": str(weights_dir),
            "exp_name": ascii_safe_name,
        },
        "optimizer": {
            "lr": 0.01,
            "lr_init": 0.00001,
            "lr_end": 0.0001,
            "warmup_steps": 2000,
            "decay_steps": 40000,
        },
        "data": {
            "max_eval_sample": 8,
            "max_sec": 54,
            "num_workers": 2,
            "pad_val": 1024,
        },
        "model": {
            "vocab_size": 1025,
            "phoneme_vocab_size": 732,  # v2 版本使用 732
            "embedding_dim": 512,
            "hidden_dim": 512,
            "head": 16,
            "linear_units": 2048,
            "n_layer": 24,
            "dropout": 0,
            "EOS": 1024,
            "random_bert": 0,
        },
        "inference": {
            "top_k": 5,
        },
        # GPT-SoVITS 需要的额外配置
        "train_semantic_path": str(exp_dir / "6-name2semantic.tsv"),
        "train_phoneme_path": str(exp_dir / "2-name2text.txt"),
        "output_dir": str(output_dir),
        "pretrained_s1": str(config.PRETRAINED_DIR / "s1_pretrained.ckpt"),
    }

    # 保存配置
    config_path = exp_dir / "s1_config.yaml"
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, default_flow_style=False)

    yield {
        "type": "phase",
        "phase": "gpt",
        "message": "Phase 1: GPT 模型训练",
    }

    # 设置环境变量
    env = os.environ.copy()
    env["_CUDA_VISIBLE_DEVICES"] = "0" if config.GPU_AVAILABLE else ""
    env["hz"] = "25hz"

    # 设置 UTF-8 编码，避免 Windows 控制台编码问题
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    # 禁用 rich 进度条的特殊字符，避免 Unicode 错误
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"

    # 设置 PYTHONPATH
    python_path = os.pathsep.join([
        str(GPT_SOVITS_ROOT),
        str(GPT_SOVITS_DIR),
        env.get("PYTHONPATH", ""),
    ])
    env["PYTHONPATH"] = python_path

    cmd = [PYTHON_EXEC, str(GPT_SOVITS_DIR / "s1_train.py"), "--config_file", str(config_path)]

    start_time = time.time()
    current_epoch = 0
    losses = []

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(GPT_SOVITS_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8',
            errors='replace',
        )

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            # 解析训练输出
            parsed = parse_training_output(line)

            if parsed:
                if "epoch" in parsed:
                    current_epoch = parsed["epoch"]

                if "loss" in parsed:
                    losses.append(parsed["loss"])

                elapsed = time.time() - start_time

                yield {
                    "type": "progress",
                    "phase": "gpt",
                    "epoch": current_epoch,
                    "total_epochs": epochs,
                    "step": parsed.get("step", 0),
                    "total_steps": parsed.get("total_steps", 0),
                    "loss": parsed.get("loss", losses[-1] if losses else 0),
                    "avg_loss": sum(losses[-10:]) / len(losses[-10:]) if losses else 0,
                    "elapsed_seconds": round(elapsed, 1),
                    "percent": round(current_epoch / epochs * 50, 1),  # GPT 占 50%
                }
            else:
                # 发送原始日志
                yield {
                    "type": "log",
                    "phase": "gpt",
                    "message": line,
                }

        process.wait()

        if process.returncode == 0:
            # 查找生成的模型
            model_files = list(output_dir.glob("*.ckpt"))

            yield {
                "type": "phase_done",
                "phase": "gpt",
                "message": "GPT 训练完成",
                "model_path": str(model_files[0]) if model_files else None,
                "final_loss": losses[-1] if losses else None,
            }
            return True
        else:
            yield {
                "type": "error",
                "phase": "gpt",
                "message": f"GPT 训练失败 (返回码: {process.returncode})",
            }
            return False

    except Exception as e:
        yield {
            "type": "error",
            "phase": "gpt",
            "message": f"GPT 训练异常: {str(e)}",
        }
        return False


def train_sovits_model(
    blogger_name: str,
    epochs: int = 8,
    batch_size: int = 4,
) -> Generator[Dict[str, Any], None, bool]:
    """
    训练 SoVITS 模型 (Stage 2)
    """
    setup_environment()

    exp_dir = get_exp_dir(blogger_name)
    output_dir = exp_dir / "logs_s2"
    output_dir.mkdir(parents=True, exist_ok=True)

    # 使用 ASCII 安全的名称，避免 Windows 子进程编码问题
    ascii_safe_name = get_ascii_safe_name(blogger_name)

    # 使用 ASCII 安全路径保存检查点（在 BASE_DIR 下，避免中文路径）
    s2_ckpt_dir = config.BASE_DIR / "weights_temp" / ascii_safe_name / "s2"
    s2_ckpt_dir.mkdir(parents=True, exist_ok=True)

    # SoVITS 训练脚本会尝试保存到 exp_dir/logs_s2_v2/，需要预先创建
    logs_s2_v2_dir = exp_dir / "logs_s2_v2"
    logs_s2_v2_dir.mkdir(parents=True, exist_ok=True)

    # 读取基础 SoVITS 配置
    base_config_path = GPT_SOVITS_DIR / "configs" / "s2.json"
    with open(base_config_path, "r", encoding="utf-8") as f:
        config_data = json.load(f)

    # 使用 ASCII 安全路径保存最终权重（含 config 和 weight 的正确格式）
    save_weight_dir = config.BASE_DIR / "weights_temp" / ascii_safe_name / "sovits_weights"
    save_weight_dir.mkdir(parents=True, exist_ok=True)

    # 更新配置
    config_data["train"]["epochs"] = epochs
    config_data["train"]["batch_size"] = batch_size
    config_data["train"]["save_every_epoch"] = max(1, epochs // 4)
    config_data["train"]["gpu_numbers"] = "0" if config.GPU_AVAILABLE else ""
    config_data["train"]["if_save_latest"] = 1  # 保存最新模型
    config_data["train"]["if_save_every_weights"] = True  # 每个epoch保存权重
    config_data["data"]["exp_dir"] = str(exp_dir)
    config_data["s2_ckpt_dir"] = str(s2_ckpt_dir)
    config_data["name"] = ascii_safe_name
    # save_weight_dir 是保存最终推理用模型的目录（含 config 和 weight）
    config_data["save_weight_dir"] = str(save_weight_dir)
    # pretrained 模型路径需要在 train 部分
    config_data["train"]["pretrained_s2G"] = str(config.PRETRAINED_DIR / "s2G_pretrained.pth")
    config_data["train"]["pretrained_s2D"] = str(config.PRETRAINED_DIR / "s2D_pretrained.pth") if (config.PRETRAINED_DIR / "s2D_pretrained.pth").exists() else ""
    # version 需要放在 model 部分
    config_data["model"]["version"] = "v2"

    # 保存配置
    config_path = exp_dir / "s2_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    yield {
        "type": "phase",
        "phase": "sovits",
        "message": "Phase 2: SoVITS 模型训练",
    }

    # 设置环境变量
    env = os.environ.copy()
    env["_CUDA_VISIBLE_DEVICES"] = "0" if config.GPU_AVAILABLE else ""

    # 设置 UTF-8 编码，避免 Windows 控制台编码问题
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"

    # 设置 PYTHONPATH
    python_path = os.pathsep.join([
        str(GPT_SOVITS_ROOT),
        str(GPT_SOVITS_DIR),
        env.get("PYTHONPATH", ""),
    ])
    env["PYTHONPATH"] = python_path

    cmd = [PYTHON_EXEC, str(GPT_SOVITS_DIR / "s2_train.py"), "--config", str(config_path)]

    start_time = time.time()
    current_epoch = 0
    losses = []

    try:
        process = subprocess.Popen(
            cmd,
            cwd=str(GPT_SOVITS_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding='utf-8',
            errors='replace',
        )

        for line in process.stdout:
            line = line.strip()
            if not line:
                continue

            parsed = parse_training_output(line)

            if parsed:
                if "epoch" in parsed:
                    current_epoch = parsed["epoch"]

                if "loss" in parsed:
                    losses.append(parsed["loss"])

                elapsed = time.time() - start_time

                yield {
                    "type": "progress",
                    "phase": "sovits",
                    "epoch": current_epoch,
                    "total_epochs": epochs,
                    "loss": parsed.get("loss", losses[-1] if losses else 0),
                    "avg_loss": sum(losses[-10:]) / len(losses[-10:]) if losses else 0,
                    "elapsed_seconds": round(elapsed, 1),
                    "percent": round(50 + current_epoch / epochs * 50, 1),  # SoVITS 占后 50%
                    "raw_output": line,
                }
            else:
                yield {
                    "type": "log",
                    "phase": "sovits",
                    "message": line,
                }

        process.wait()

        if process.returncode == 0:
            model_files = list(output_dir.glob("*.pth"))

            yield {
                "type": "phase_done",
                "phase": "sovits",
                "message": "SoVITS 训练完成",
                "model_path": str(model_files[0]) if model_files else None,
                "final_loss": losses[-1] if losses else None,
            }
            return True
        else:
            yield {
                "type": "error",
                "phase": "sovits",
                "message": f"SoVITS 训练失败 (返回码: {process.returncode})",
            }
            return False

    except Exception as e:
        yield {
            "type": "error",
            "phase": "sovits",
            "message": f"SoVITS 训练异常: {str(e)}",
        }
        return False


def full_training_pipeline(
    blogger_name: str,
    epochs_gpt: int = 15,
    epochs_sovits: int = 8,
    batch_size: int = 4,
    skip_prepare: bool = False,
) -> Generator[Dict[str, Any], None, None]:
    """
    完整训练流程

    1. 数据预处理
    2. GPT 模型训练
    3. SoVITS 模型训练
    4. 保存最终模型
    """
    start_time = time.time()

    yield {
        "type": "start",
        "message": f"开始训练 {blogger_name}",
        "config": {
            "blogger_name": blogger_name,
            "epochs_gpt": epochs_gpt,
            "epochs_sovits": epochs_sovits,
            "batch_size": batch_size,
            "device": config.DEVICE,
            "gpu": config.GPU_NAME,
        },
    }

    # Step 1: 数据预处理
    if not skip_prepare:
        yield {"type": "phase", "phase": "prepare", "message": "数据预处理..."}

        success = False
        for progress in prepare_training_data(blogger_name):
            yield progress
            if progress.get("type") == "error":
                return
            if progress.get("type") == "step_done" and "语义" in progress.get("step", ""):
                success = True

        if not success:
            yield {"type": "error", "message": "数据预处理失败"}
            return

    # Step 2: GPT 训练
    gpt_success = False
    for progress in train_gpt_model(blogger_name, epochs_gpt, batch_size):
        yield progress
        if progress.get("type") == "error":
            return
        if progress.get("type") == "phase_done":
            gpt_success = True

    if not gpt_success:
        yield {"type": "error", "message": "GPT 训练失败"}
        return

    # Step 3: SoVITS 训练
    sovits_success = False
    for progress in train_sovits_model(blogger_name, epochs_sovits, batch_size):
        yield progress
        if progress.get("type") == "error":
            return
        if progress.get("type") == "phase_done":
            sovits_success = True

    if not sovits_success:
        yield {"type": "error", "message": "SoVITS 训练失败"}
        return

    # Step 4: 复制最终模型到 trained 目录
    exp_dir = get_exp_dir(blogger_name)
    output_dir = config.TRAINED_DIR / blogger_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # ASCII 安全路径下的模型
    ascii_safe_name = get_ascii_safe_name(blogger_name)
    weights_temp_dir = config.BASE_DIR / "weights_temp" / ascii_safe_name

    import shutil

    # 复制 GPT 模型 (优先从 ASCII 安全路径，然后尝试原路径)
    gpt_models = list((weights_temp_dir / "s1").glob("*.ckpt")) if (weights_temp_dir / "s1").exists() else []
    if not gpt_models:
        gpt_models = list((exp_dir / "logs_s1").glob("*.ckpt"))
    if gpt_models:
        gpt_models.sort()
        shutil.copy2(gpt_models[-1], output_dir / "gpt.ckpt")

    # 复制 SoVITS 模型
    # 优先使用 sovits_weights 目录下的模型（含正确格式 config + weight）
    # 文件名格式: {name}_e{epoch}.pth
    sovits_weights_dir = weights_temp_dir / "sovits_weights"
    sovits_models = []

    # 1. 优先从 sovits_weights 目录（正确格式的推理模型）
    if sovits_weights_dir.exists():
        sovits_models = list(sovits_weights_dir.glob("*.pth"))

    # 2. 然后从 logs_s2_v2 目录（训练检查点，需要转换）
    if not sovits_models and (exp_dir / "logs_s2_v2").exists():
        sovits_models = list((exp_dir / "logs_s2_v2").glob("G_*.pth"))

    # 3. 最后从其他目录
    if not sovits_models and (weights_temp_dir / "s2").exists():
        sovits_models = list((weights_temp_dir / "s2").glob("G_*.pth"))

    if sovits_models:
        # 找最新的 (最高 epoch / 最大数字)
        sovits_models.sort()
        shutil.copy2(sovits_models[-1], output_dir / "sovits.pth")

    # 清理临时权重目录
    if weights_temp_dir.exists():
        try:
            shutil.rmtree(weights_temp_dir)
        except Exception as e:
            logger.warning(f"清理临时目录失败: {e}")

    total_time = time.time() - start_time

    yield {
        "type": "done",
        "message": "训练完成！",
        "model_dir": str(output_dir),
        "gpt_model": str(output_dir / "gpt.ckpt"),
        "sovits_model": str(output_dir / "sovits.pth"),
        "total_seconds": round(total_time, 1),
    }
