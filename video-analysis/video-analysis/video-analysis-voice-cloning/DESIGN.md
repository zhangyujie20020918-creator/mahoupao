# Video Analysis Voice Cloning - 设计文档

## 项目目标

使用 GPT-SoVITS 克隆博主声音，支持：
1. 从现有数据（mp3 + ASR）准备训练数据
2. 微调训练（5-10分钟音频）
3. 语音合成推理
4. 与 soul 项目集成

---

## 技术选型

- **模型**: GPT-SoVITS v4 (最新版本，48k音频输出)
- **Python**: 3.10 (conda 环境)
- **框架**: FastAPI (API服务)
- **GPU**: CUDA 12.x

参考: [GPT-SoVITS GitHub](https://github.com/RVC-Boss/GPT-SoVITS)

---

## 项目结构

```
video-analysis-voice-cloning/
├── config.py                 # 配置文件
├── api.py                    # FastAPI 服务
├── run_server.py             # 启动脚本
├── requirements.txt          # 依赖
├── services/
│   ├── __init__.py
│   ├── data_preparer.py      # 数据准备（切片+标注）
│   ├── model_downloader.py   # 模型下载
│   ├── trainer.py            # 训练服务
│   └── synthesizer.py        # 语音合成推理
├── models/                   # 预训练模型
│   ├── pretrained/           # GPT-SoVITS 预训练
│   ├── g2pw/                 # 中文拼音模型
│   └── trained/              # 训练后的模型
│       └── {博主名}/
│           ├── gpt.ckpt      # GPT 模型
│           └── sovits.pth    # SoVITS 模型
├── datasets/                 # 训练数据集
│   └── {博主名}/
│       ├── audio/            # 切片后的音频
│       ├── {博主名}.list     # 标注文件
│       └── metadata.json     # 数据集信息
└── output/                   # 合成输出
```

---

## 核心流程

### 1. 数据准备 (data_preparer.py)

从 `downloads/{博主名}/` 读取数据：

```python
# 输入
downloads/{博主名}/
├── 视频1.mp3              # 音频
├── 视频1.json             # ASR结果（含segments时间戳）
└── 视频1.txt              # 清洗后的文本

# 处理流程
1. 遍历 mp3 + json 配对文件
2. 根据 ASR segments 切片音频
3. 过滤：
   - 时长 3-15秒 (太短或太长不适合训练)
   - 去除静音/噪音片段
4. 生成 .list 标注文件

# 输出
datasets/{博主名}/
├── audio/
│   ├── 0001.wav           # 切片音频 (转换为wav)
│   ├── 0002.wav
│   └── ...
├── {博主名}.list          # 标注文件
└── metadata.json          # 统计信息
```

**标注文件格式** (.list):
```
audio/0001.wav|博主名|zh|你好我是财经小艾
audio/0002.wav|博主名|zh|今天给大家聊一聊AI
```

### 2. 模型下载 (model_downloader.py)

需要下载的模型：

| 模型 | 大小 | 说明 |
|------|------|------|
| s1v3.ckpt | ~1.5GB | GPT 预训练 |
| s2Gv3.pth | ~800MB | SoVITS 预训练 |
| bigvgan_v2 | ~100MB | 声码器 |
| G2PWModel | ~200MB | 中文拼音转换 |

**下载源**: HuggingFace (hf-mirror.com 加速)

### 3. 训练流程 (trainer.py)

```
Step 1: 数据预处理
├── 文本到音素转换 (G2PW)
├── 语义token提取 (Hubert/w2v-bert)
└── 声学特征提取 (SSL)

Step 2: GPT 训练
├── 输入: 音素 + 语义token
├── 输出: gpt_{博主名}.ckpt
└── 时长: 约 10-30 分钟

Step 3: SoVITS 训练
├── 输入: 声学特征
├── 输出: sovits_{博主名}.pth
└── 时长: 约 20-60 分钟
```

### 4. 语音合成 (synthesizer.py)

```python
# 推理接口
def synthesize(
    text: str,              # 要合成的文本
    blogger_name: str,      # 博主名（加载对应模型）
    ref_audio: str = None,  # 参考音频（可选，用于调整语气）
    speed: float = 1.0,     # 语速
) -> bytes:                 # 返回音频数据
```

---

## API 设计

### 端口: 8003

### 端点

```
GET  /api/voice/status           # 服务状态（GPU、模型）
GET  /api/voice/bloggers         # 博主列表（含训练状态）
GET  /api/voice/blogger/{name}   # 博主详情

POST /api/voice/prepare          # 准备训练数据（流式进度）
POST /api/voice/train            # 开始训练（流式进度）
POST /api/voice/synthesize       # 语音合成

GET  /api/voice/models/status    # 预训练模型状态
POST /api/voice/models/download  # 下载预训练模型（流式进度）
```

### 请求示例

```json
// POST /api/voice/prepare
{
  "blogger_name": "小艾财经说 - 抖音",
  "min_duration": 3.0,
  "max_duration": 15.0
}

// POST /api/voice/train
{
  "blogger_name": "小艾财经说 - 抖音",
  "epochs": 10,
  "batch_size": 4
}

// POST /api/voice/synthesize
{
  "blogger_name": "小艾财经说 - 抖音",
  "text": "大家好，我是财经小艾",
  "speed": 1.0
}
```

---

## 前端页面 (voice.html)

### 页面结构

```
┌────────────────────────────────────────────────┐
│  声音克隆                      [数据清洗] [下载] │
├────────────────────────────────────────────────┤
│  系统状态                                       │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │ GPU     │  │ 预训练   │  │ 训练数   │        │
│  │ RTX4090 │  │ 已下载   │  │ 2个博主  │        │
│  └─────────┘  └─────────┘  └─────────┘        │
├────────────────────────────────────────────────┤
│  选择博主                                       │
│  ┌──────────────────────────────────────────┐ │
│  │ 小艾财经说 - 抖音                         │ │
│  │ 38个视频 | 120段音频 | [已训练]           │ │
│  ├──────────────────────────────────────────┤ │
│  │ 勇哥说财经 - 抖音                         │ │
│  │ 25个视频 | 待准备 | [未训练]              │ │
│  └──────────────────────────────────────────┘ │
├────────────────────────────────────────────────┤
│  训练流程                                       │
│  ┌─────┐ ┌─────┐ ┌─────┐                      │
│  │准备  │→│训练  │→│测试  │                      │
│  │数据  │ │模型  │ │合成  │                      │
│  └─────┘ └─────┘ └─────┘                      │
│                                                │
│  [开始准备数据]                                 │
│                                                │
│  进度: ████████░░ 80%                          │
│  正在切片: AI时代来临.mp3 (15/38)              │
├────────────────────────────────────────────────┤
│  语音合成测试                                   │
│  ┌──────────────────────────────────────────┐ │
│  │ 输入文本：                                │ │
│  │ 大家好，我是财经小艾，今天给大家聊一聊AI │ │
│  └──────────────────────────────────────────┘ │
│  语速: [1.0x]                                  │
│  [合成语音]  ▶️ 播放                            │
└────────────────────────────────────────────────┘
```

---

## 与 Soul 项目集成

Soul 项目调用方式：

```python
# soul 项目中
async def chat_with_voice(message: str, blogger: str) -> dict:
    # 1. 获取文本回复（使用 persona + RAG）
    reply_text = await generate_reply(message, blogger)

    # 2. 调用 voice-cloning API 合成语音
    audio = await voice_api.synthesize(
        text=reply_text,
        blogger_name=blogger
    )

    return {
        "text": reply_text,
        "audio": audio  # base64 或文件路径
    }
```

---

## 依赖要求

```txt
# requirements.txt
torch>=2.2.0
torchaudio>=2.2.0
transformers>=4.40.0
fastapi>=0.110.0
uvicorn>=0.29.0
pydantic>=2.0.0
pydub>=0.25.1
librosa>=0.10.0
soundfile>=0.12.0
jieba>=0.42.1
cn2an>=0.5.22
pypinyin>=0.51.0
g2p-en>=2.1.0
LangSegment>=0.3.3
tqdm>=4.66.0
huggingface-hub>=0.22.0
```

---

## 开发计划

### Phase 1: 基础架构
- [ ] 项目结构搭建
- [ ] 配置文件
- [ ] 模型下载服务

### Phase 2: 数据准备
- [ ] 音频切片服务
- [ ] 标注文件生成
- [ ] 数据质量检查

### Phase 3: 训练
- [ ] GPT 训练
- [ ] SoVITS 训练
- [ ] 训练进度监控

### Phase 4: 推理
- [ ] 语音合成 API
- [ ] 前端测试页面

### Phase 5: 集成
- [ ] Soul 项目集成
- [ ] 性能优化

---

## 注意事项

1. **音频质量**: 训练数据需要干净的人声，背景音乐会影响效果
2. **数据量**: 5-10分钟有效音频即可，质量比数量重要
3. **GPU 显存**: 训练需要至少 6GB 显存，推理需要约 4GB
4. **中文处理**: 需要 G2PW 模型处理中文拼音

---

## 参考资料

- [GPT-SoVITS GitHub](https://github.com/RVC-Boss/GPT-SoVITS)
- [GPT-SoVITS 训练教程](https://www.yuque.com/baicaigongchang1145haozai/ib3g1e)
- [HuggingFace 模型](https://huggingface.co/lj1995/GPT-SoVITS)
