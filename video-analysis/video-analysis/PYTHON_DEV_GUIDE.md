# Python 开发手册

## 环境配置

### Conda 环境

**必须使用正确的 conda 环境进行开发和运行！**

- **环境名称**: `video-analysis`
- **Python 路径**: `D:/ProgramData/anaconda3/envs/video-analysis/python.exe`

### 激活环境

```bash
conda activate video-analysis
```

### 运行 Python 脚本

```bash
# 方式 1: 激活环境后运行
conda activate video-analysis
python script.py

# 方式 2: 直接使用完整路径
"D:/ProgramData/anaconda3/envs/video-analysis/python.exe" script.py
```

### 安装依赖

```bash
# 必须在 video-analysis 环境中安装
conda activate video-analysis
pip install package_name

# 或使用完整路径
"D:/ProgramData/anaconda3/envs/video-analysis/python.exe" -m pip install package_name
```

---

## 项目结构

| 项目 | 说明 | 端口 |
|------|------|------|
| video-analysis-python | 视频下载后端服务 | 8000 |
| video-analysis-web | 前端界面 | 5173 |
| video-analysis-cleaner | 数据清洗 (MP4→MP3, ASR) | 8001 |
| video-analysis-maker | ASR优化 + 向量数据库 + 人格画像 | 8002 |

---

## 启动命令

### 后端服务
```bash
conda activate video-analysis
cd video-analysis-python
python run_server.py
```

### 前端服务
```bash
cd video-analysis-web
npm run dev
```

### 数据清洗服务
```bash
conda activate video-analysis
cd video-analysis-cleaner
python run_server.py
```

### Maker 服务
```bash
conda activate video-analysis
cd video-analysis-maker
python run_server.py                   # 启动 API 服务 (端口 8002)

# 或者命令行处理
python main.py --list-bloggers        # 查看可用博主
python main.py --blogger "博主名"      # 处理指定博主
```
