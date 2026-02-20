# 开发进度总结 (2026-02-21)

## 已解决的问题

### 1. 前端超时错误
- **问题**: 下载完成后显示 "timeout of 300000ms exceeded" 而不是汇总报告
- **原因**: Vite 代理默认超时5分钟
- **修复**: `vite.config.ts` 添加代理超时配置 (2小时)

### 2. 浏览器自动关闭
- **问题**: 下载完成后浏览器关闭，无法复用登录状态
- **修复**: 创建 `browser_manager.py` 单例管理器，浏览器保持打开

### 3. 作品数 vs 视频数
- **问题**: 页面显示39个作品，但只有38个视频（1个是图文）
- **修复**: 区分统计 work_count / video_count / non_video_count

### 4. 自动创建用户文件夹
- **修复**: 自动提取用户名，创建 `downloads/用户名/` 文件夹
- 保存 `_metadata.json` (元数据)
- 保存 `_video_urls.txt` (URL列表)

### 5. 跳过已下载视频
- **修复**: 检查元数据和文件是否存在，跳过已下载的视频
- 只下载新增视频，支持增量更新

---

## 修改的文件

| 文件 | 修改内容 |
|------|----------|
| `video-analysis-python/src/services/browser_manager.py` | **新建** - 浏览器单例管理器 |
| `video-analysis-python/src/services/download_service.py` | 重写主下载逻辑 |
| `video-analysis-web/vite.config.ts` | 添加代理超时配置 |
| `video-analysis-web/src/types/api.ts` | 添加新字段类型 |
| `video-analysis-web/src/App.vue` | 添加新状态变量和显示逻辑 |
| `video-analysis-web/src/style.css` | 添加新样式 |

---

## 新增功能详情

### browser_manager.py
```python
# 单例模式浏览器管理器
# 保持浏览器实例在多次下载间复用
# 主要方法:
# - get_page(profile_dir, chrome_path) - 获取页面
# - keep_alive() - 标记保持打开
# - close() - 手动关闭
```

### 用户文件夹结构
```
downloads/
└── 用户名/
    ├── 视频1.mp4
    ├── 视频2.mp4
    ├── _metadata.json      # 元数据
    └── _video_urls.txt     # URL列表
```

### _metadata.json 格式
```json
{
  "user_url": "https://www.douyin.com/user/xxx",
  "username": "用户名",
  "work_count": 39,
  "video_count": 38,
  "non_video_count": 1,
  "last_updated": "2026-02-21T...",
  "downloaded_videos": [
    {"url": "...", "title": "...", "success": true, "file_path": "..."}
  ]
}
```

---

## 明日待测试

1. **验证浏览器保持打开** - 下载完成后浏览器应保持打开
2. **验证用户文件夹创建** - 检查 `downloads/用户名/` 目录结构
3. **验证跳过逻辑** - 重新输入相同用户URL，应跳过已下载视频
4. **验证前端显示** - 确认汇总报告正确显示（不再超时）

---

## 启动命令

```bash
# 后端
cd video-analysis-python
python run_server.py

# 前端
cd video-analysis-web
npm run dev
```

---

## 待修复的问题

### 1. 失败视频重试逻辑 (2026-02-21 已修复)
- **问题**: 代码中有 `max_retries: int = 3` 和 `max_retry_rounds = 3` 变量定义，但从未使用（重构时丢失）
- **修复**: 在 `download_service.py` 第722行后添加重试逻辑
- **实现行为**:
  1. 第一轮下载完成后，检查 `failed_list` 是否有失败的视频
  2. 如果有失败，回到用户首页重新滚动获取视频链接
  3. 遍历失败列表，重新获取视频信息并下载
  4. 最多重试 3 轮 (`max_retry_rounds = 3`)
  5. 每轮重试会发送 `type: "retrying"` 事件通知前端
- **状态**: 已修复

### 2. 前端 axios 超时 (2026-02-21 修复)
- **问题**: `index.html` 中 axios 请求 `timeout: 300000` (5分钟) 太短
- **修复**: 改为 `timeout: 7200000` (2小时)

---

## 相关上下文

- 测试用户主页有39个作品，其中38个视频，1个图文
- 抖音需要登录才能获取全部视频
- 验证码/登录检测逻辑已实现，等待用户手动完成
- 日志保存在 `video-analysis/logs/` 目录
