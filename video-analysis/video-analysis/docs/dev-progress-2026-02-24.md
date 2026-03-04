# 开发进度 - 2026-02-24

## 今日完成

### Voice Cloning 项目 - GPT-SoVITS 真实训练集成

#### 1. 项目结构创建 ✅
- `video-analysis-voice-cloning/` 项目骨架
- `config.py` - 配置文件 (端口 8003, GPU 检测)
- `api.py` - FastAPI 服务
- `run_server.py` - 启动脚本
- `requirements.txt` - 依赖

#### 2. 前端页面 ✅
- `video-analysis-web/voice.html` - 声音克隆页面
  - 计算设备显示 (GPU/CPU)
  - 预训练模型下载
  - 选择
  - 数据准备
  - 训练界面 (Loss 曲线 + 进度条)
  - 语音合成测试
- 更新导航链接 (index.html, cleaner.html, maker.html)

#### 3. 预训练模型下载 ✅
- GPT 模型 (s1_pretrained.ckpt) - 已下载
- SoVITS 模型 (s2G_pretrained.pth) - 已下载
- Chinese HuBERT (chinese-hubert-base) - 已下载
- G2PW 拼音模型 (G2PWModel) - 已下载

#### 4. GPT-SoVITS 真实训练集成 ✅
- 克隆 GPT-SoVITS 到 `GPT_SoVITS_src/`
- 创建 `services/gpt_sovits_trainer.py`:
  - `prepare_training_data()` - 数据预处理
    - 1-get-text.py → BERT 特征
    - 2-get-hubert-wav32k.py → HuBERT 特征
    - 3-get-semantic.py → 语义 tokens
  - `train_gpt_model()` - GPT 模型训练 (Stage 1)
  - `train_sovits_model()` - SoVITS 模型训练 (Stage 2)
  - `full_training_pipeline()` - 完整训练流程
- 更新 `services/trainer.py` - 调用真实训练
- 更新 `services/synthesizer.py` - 调用真实推理

#### 5. PyTorch CUDA 修复 ✅
- 安装 `torch==2.6.0+cu124` (GPU 版本)
- GPU: NVIDIA GeForce RTX 4090
- 显存: 25.8 GB

---

### 6. 情绪参考音频系统 ✅
**文件**: `services/emotion_manager.py`

实现丰富的情绪分类系统，用于选择不同情绪风格的参考音频：

| 分类 | 情绪数量 | 示例 |
|------|---------|------|
| 基础情绪 | 7 | 平静、开心、伤感、生气、害怕、惊讶、厌恶 |
| 积极情绪 | 8 | 激动、喜悦、骄傲、感激、期待、自信、调皮、温馨 |
| 消极情绪 | 8 | 焦虑、沮丧、孤独、嫉妒、愧疚、无聊、疲惫、烦躁 |
| 说话风格 | 8 | 严肃、温柔、坚定、犹豫、讽刺、夸张、随意、正式 |
| 特殊场景 | 8 | 好奇、神秘、讲故事、讲解、劝说、安慰、鼓励、警告 |
| 互动场景 | 8 | 打招呼、感谢、道歉、提问、回答、赞同、反对、结束语 |

**API**: `/api/voice/emotions`, `/api/voice/emotions/{soul}/audios`, `/api/voice/emotions/{soul}/tag`

---

### 7. 表情/语气词音频库系统 ✅
**文件**: `services/expression_library.py`

核心设计：**不是移除语气词，而是用真实录音替换**

| 分类 | 类型数量 | 触发词示例 |
|------|---------|-----------|
| 笑声 | 5 | 哈哈、嘻嘻、嘿嘿、呵呵 |
| 思考 | 4 | 嗯、额、呃、emmm |
| 叹气 | 3 | 唉、哎、呼 |
| 惊讶 | 4 | 哇、哦、啊、啊？ |
| 语气词 | 4 | 这个、那个、然后、就是 |
| 情绪 | 5 | 耶、哼、呜、嘛、切 |
| 回应 | 3 | 对对对、不是、好的 |
| 拟声 | 3 | 吃东西声、喝水声、呼吸声 |
| 口头禅 | 3 | 自定义口头禅 |

**合成逻辑**:
```
输入: "哈哈，这个真的太棒了！"
  ↓ 检测表情词
"哈哈" → 有真实录音? 用录音 : TTS合成
"这个" → 有真实录音? 用录音 : TTS合成
  ↓ 拼接输出
```

**API**: `/api/voice/expressions/types`, `/api/voice/expressions/{soul}`, `/api/voice/expressions/{soul}/extract`

---

### 8. 文本预处理模块（可选）✅
**文件**: `services/text_processor.py`

提供可选的文本预处理功能（默认关闭）：
- 移除笑声词汇
- 简化语气词
- 移除拟声词
- 简化停顿符号
- 移除网络用语

预设: strict / moderate / minimal / none

---

### 9. 前端功能更新 ✅
**文件**: `voice.html`

- **情绪标注 Tab**: 为参考音频标注情绪，支持试听
- **表情库 Tab**: 查看已收集的表情片段统计
- **情绪选择**: 合成时可选择情绪风格
- **删除功能**: 删除准备数据、删除已训练模型

---

### 10. Bug 修复 ✅

| 问题 | 解决方案 |
|------|---------|
| 音频播放失败 | 添加 CORS 头、crossorigin 属性 |
| 合成最后一个字被截断 | 确保文本以标点结尾 |
| 参考音频路径错误 | 相对路径转绝对路径 |
| 参考音频时长不合适 | 自动选择 3-10 秒的音频 |

---

## 待完成

### Voice Cloning 测试
- [x] 准备训练数据 (.list 文件格式)
- [x] 测试数据预处理流程
- [x] 测试 GPT 模型训练
- [x] 测试 SoVITS 模型训练
- [x] 测试语音合成

### 高级功能（产品精华）
- [ ] 可视化波形编辑器 - 精确选择音频片段
- [ ] 自动检测 - 从训练数据识别笑声/语气词
- [ ] 表情强度控制 - 轻笑 vs 大笑
- [ ] 批量提取工具 - 一键提取所有表情片段
- [ ] 口头禅学习 - 自动学习特有口头禅

---

## 项目状态

| 项目 | 状态 | 备注 |
|------|------|------|
| video-analysis-python | ✅ 完成 | 视频下载服务 |
| video-analysis-web | ✅ 完成 | 前端页面 |
| video-analysis-cleaner | ✅ 完成 | 数据清洗服务 |
| video-analysis-maker | ✅ 完成 | AI 人格训练 |
| video-analysis-voice-cloning | ✅ 核心完成 | 训练+合成+情绪+表情库 |

---

## 文件清单

### 新增文件
```
video-analysis-voice-cloning/
├── GPT_SoVITS_src/          # GPT-SoVITS 源码 (git clone)
├── models/
│   ├── pretrained/          # 预训练模型 (~2.5GB)
│   │   ├── s1_pretrained.ckpt
│   │   ├── s2G_pretrained.pth
│   │   ├── chinese-hubert-base/
│   │   ├── chinese-roberta-wwm-ext-large/
│   │   └── G2PWModel/
│   └── trained/             # 训练后的模型
│       └── {名}/
│           ├── gpt.ckpt
│           └── sovits.pth
├── datasets/                # 训练数据集
│   └── {名}/
│       ├── audio/           # WAV 音频片段
│       ├── {名}.list    # 训练标注文件
│       ├── metadata.json    # 元数据
│       ├── emotions.json    # 情绪标注
│       └── expressions/     # 表情音频库
├── services/
│   ├── data_preparer.py     # 数据准备 + 降噪
│   ├── model_downloader.py  # 模型下载
│   ├── trainer.py           # 训练服务
│   ├── gpt_sovits_trainer.py # GPT-SoVITS 训练集成
│   ├── synthesizer.py       # 语音合成
│   ├── emotion_manager.py   # 情绪管理 (新增)
│   ├── expression_library.py # 表情库 (新增)
│   └── text_processor.py    # 文本预处理 (新增)
├── config.py
├── api.py
├── run_server.py
└── requirements.txt

video-analysis-web/
└── voice.html               # 声音克隆前端页面 (更新)
```

---

## 启动命令

```bash
# 激活环境
conda activate video-analysis

# 启动 voice-cloning 服务
cd video-analysis-voice-cloning
python run_server.py  # 端口 8003

# 访问页面
http://localhost:5173/voice.html
```

---

## 产品设计要点

> 这些功能是产品的精华部分

| 原则 | 说明 |
|------|------|
| **不移除，而是增强** | 语气词、笑声让声音更有人味 |
| **真实录音替换** | TTS 模拟效果差的部分用真实录音 |
| **情绪多样化** | 同一可以有多种情绪风格 |
| **持续扩展** | 分类设计便于后续补充新类型 |
