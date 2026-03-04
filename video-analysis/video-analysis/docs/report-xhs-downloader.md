# 技术报告：小红书视频下载器开发全记录

**时间**: 2026-02-26 ～ 2026-03-04
**作者**: 开发团队
**状态**: ✅ 核心功能已上线

---

## 一、项目背景与目标

### 1.1 整体项目背景

`video-analysis` 是一套从视频到"数字分身"的完整 AI 流水线，目前已覆盖以下模块：

| 模块 | 功能 | 状态 |
|------|------|------|
| `video-analysis-loader` | 多平台视频批量下载（抖音、YouTube 等）| ✅ 完成 |
| `video-analysis-cleaner` | MP4 转 MP3 + ASR 语音转文字 | ✅ 完成 |
| `video-analysis-maker` | ASR 文本优化 + 向量数据库 + 人格画像 | ✅ 完成 |
| `video-analysis-voice-cloning` | GPT-SoVITS 声音克隆训练与合成 | ✅ 核心完成 |
| `video-analysis-soul` | 多用户 RAG 对话系统（数字分身） | ✅ 完成 |

本次工作的目标：**为 loader 添加小红书（XHS）平台的视频下载能力**，要求支持：
1. 单视频下载（通过笔记链接）
2. 用户主页批量下载（抓取用户所有视频）

### 1.2 为什么小红书难做

与抖音相比，小红书的技术挑战更大：

- **无公开 API**：没有任何官方或稳定的第三方 API 可用
- **强反爬措施**：URL 携带 `xsec_token` 鉴权参数，未携带直接 404
- **CDN 特殊要求**：下载视频文件需要 `Range: bytes=0-` 请求头，否则只返回片段
- **浏览器登录态**：必须用已登录的浏览器才能访问内容，无法纯 HTTP 模拟

---

## 二、技术探索过程

### 2.1 第一阶段：调研可用方案

初始评估了三种方案：

| 方案 | 描述 | 结论 |
|------|------|------|
| `yt-dlp` | 已集成的下载工具 | 对 XHS 支持不完整，提取器频繁失效 |
| `XHS-Downloader` 库 | GitHub 第三方库 | 仅支持 Python 3.12+，不可 pip 安装，依赖混乱 |
| Playwright 浏览器拦截 | 用浏览器渲染页面，拦截视频请求 | **选定方案**，登录态稳定，可复用 |

**决策**：自行实现基于 Playwright 的下载器，与现有 `BrowserManager` 架构无缝整合。

### 2.2 第二阶段：单视频下载

#### 问题 1：VIDEO_CDN_PATTERNS 过宽

**现象**：拦截到的"视频 URL"其实是一个 148KB 的 JavaScript 文件，最终保存文件无法播放。

**根因**：CDN 过滤规则使用了 `"xhscdn.com"` 作为匹配条件，而小红书的静态资源域名 `fe-static.xhscdn.com` 同样包含这个字符串，导致 JS 文件被误判为视频。

**修复**：
```python
# 错误：过于宽泛
VIDEO_CDN_PATTERNS = ["sns-video", "xhs-video", "xhscdn.com"]

# 正确：仅匹配视频专用域名
VIDEO_CDN_PATTERNS = ["sns-video", "xhs-video"]
# 对应域名：sns-video-zl.xhscdn.com、sns-video-ak.xhscdn.com
```

#### 问题 2：视频只下载到 148KB（文件不完整）

**现象**：下载完成但文件大小异常小（~148KB），实际视频应有 10+ MB。

**根因**：XHS CDN 服务器对未携带 `Range` 请求头的请求只返回初始片段，而非完整文件。

**修复**：
```python
headers = {
    "Referer": "https://www.xiaohongshu.com/",
    "User-Agent": "Mozilla/5.0 ...",
    "Range": "bytes=0-",  # 关键：告知 CDN 要完整文件
}
# 同时接受 HTTP 200 和 206 Partial Content 作为成功响应
if response.status not in (200, 206):
    raise DownloadFailedError(...)
```

**验证**：加上 `Range` 头后，同一 URL 返回 HTTP 206，`Content-Length: 12487539`（约 12 MB）。

### 2.3 第三阶段：批量下载

#### 问题 3：所有 71 个视频全部下载失败

**现象**：成功从用户主页提取到 71 条笔记链接，但下载全部以 404 失败告终。

**排查过程**：

1. 写诊断脚本 `test_user_profile.py`，逐个测试提取到的 URL
2. 诊断脚本本身崩溃，报错 `TargetClosedError`
3. 定位到根因：uvicorn 服务进程的 `BrowserManager` 持有了 `xhs-profile` 目录锁，诊断脚本无法再打开同一 Profile 的第二个浏览器实例

4. 停止 uvicorn 后重新运行诊断脚本，结果清晰：

```
--- 笔记 1: https://www.xiaohongshu.com/explore/69a597a5...
  实际URL: https://www.xiaohongshu.com/404?source=/404/sec_axEjtsXj?...
  → 404/错误页面

--- 笔记 2: https://www.xiaohongshu.com/explore/697428210...
  实际URL: https://www.xiaohongshu.com/404?source=/404/...
  → 404/错误页面
```

**所有 5 条测试链接全部 404。**

#### 问题 4：URL 缺少 xsec_token

**根因分析**：

旧的提取逻辑使用 `document.querySelectorAll('a[href]')` 从 DOM 中采集链接：

```javascript
const href = a.getAttribute('href');  // 返回: /explore/69a597a5...
// 构造: https://www.xiaohongshu.com/explore/69a597a5...
```

XHS 页面中 `<a>` 标签的 `href` 属性只有裸路径，不含安全 token。`xsec_token` 是通过 JavaScript 在用户点击时动态注入的。

**正确做法**：拦截 XHS 加载笔记列表时调用的后端 API：

```
GET https://edith.xiaohongshu.com/api/sns/web/v1/user_posted?user_id=...
```

API 响应结构：
```json
{
  "data": {
    "notes": [
      {
        "note_id": "6990809b000000002800ba82",
        "xsec_token": "ABO9fO6T0-WL48-JgHCQwnfFy7Y8nz0_95m1StHALbGYY=",
        "type": "video",   // 或 "normal"（图片笔记）
        "display_title": "..."
      }
    ]
  }
}
```

**构造正确 URL**：
```
https://www.xiaohongshu.com/explore/{note_id}?xsec_token={token}&xsec_source=pc_user
```

#### 问题 5：批量下载时浏览器 Profile 锁冲突

**现象**：修复 URL 问题后，服务端报错：

```
BrowserType.launch_persistent_context: Target page, context or browser has been closed
[Chrome] 无法打开配置文件。已在此会话中打开。
```

**根因**：`extract_user_video_urls` 方法使用了独立的 `async with async_playwright() as p` 上下文，试图以相同的 `xhs-profile` 目录启动一个新的 Chrome 实例。但 `BrowserManager` 单例已持有该 Profile 的锁，Chrome 拒绝二次打开。

**修复策略**：放弃在提取阶段新建浏览器实例，改为复用 `BrowserManager` 已有的 persistent context，在其中开一个新的 Page：

```python
# 旧方案（冲突）
async with async_playwright() as p:
    context = await p.chromium.launch_persistent_context(
        user_data_dir=str(self.PROFILE_DIR), ...
    )

# 新方案（复用）
browser_manager = await BrowserManager.get_instance()
await browser_manager.get_page(self.PROFILE_DIR)  # 确保浏览器已启动
context = browser_manager._context
extraction_page = await context.new_page()         # 新 Page，不新建 Context
```

同时，提取完成后只关闭临时 Page，不关闭整个 Context，BrowserManager 仍可正常服务后续的单视频下载请求。

---

## 三、最终解决方案

### 3.1 整体架构

```
POST /api/download (用户主页 URL)
        │
        ▼
routes.py: 检测到 /user/profile/ → 调用 XHS 流式下载
        │
        ▼
download_service.py: download_xhs_user_videos_stream()
        │
        ├─ [1] 调用 RedNoteDownloader.extract_user_video_urls()
        │       │
        │       ├─ 复用 BrowserManager 浏览器
        │       ├─ 新建 Page，导航到用户主页
        │       ├─ 拦截 user_posted API 响应
        │       ├─ 从 API 获取 note_id + xsec_token + type
        │       ├─ 过滤 type==video（跳过图片笔记）
        │       └─ 构造带 token 的完整 URL
        │
        └─ [2] 逐个下载视频（复用同一浏览器）
                │
                ├─ BrowserManager.get_page() → 导航到笔记页
                ├─ 拦截 response 事件捕获视频 CDN URL
                ├─ aiohttp 下载（带 Range: bytes=0-）
                └─ 跳过已有文件（by note_id）
```

### 3.2 关键技术点总结

| 技术点 | 实现方式 |
|--------|----------|
| 登录态保持 | Playwright persistent context（`xhs-profile` 目录） |
| 视频 URL 获取 | 拦截 `sns-video*.xhscdn.com` 响应 |
| 批量 URL 提取 | 拦截 `user_posted` API，获取 `xsec_token` |
| 图片笔记过滤 | API 响应中 `type` 字段，仅处理 `video` 类型 |
| 完整文件下载 | HTTP `Range: bytes=0-`，接受 206 响应 |
| Profile 锁管理 | 所有操作共用 BrowserManager 单例，新建 Page 而非新建 Context |
| 断点续传 | 检查下载目录中是否已有含 `note_id` 的文件名 |
| 反限流 | 每次下载间随机延迟 1.0 ～ 2.5 秒 |

---

## 四、当前功能状态

### 4.1 已验证可用

| 功能 | 测试结果 |
|------|----------|
| 单视频下载（笔记链接） | ✅ 正常，下载约 12 MB 视频 ~6 秒 |
| 用户主页批量下载 | ✅ 正常，32 个视频，0 失败，用时 ~352 秒 |
| 图片笔记自动跳过 | ✅ 正常，API 中 `type=normal` 的笔记被过滤 |
| 已下载文件跳过 | ✅ 正常，重复运行只下载新增视频 |
| 用户名文件夹自动创建 | ✅ 正常，`downloads/{用户名}/` |

### 4.2 已知限制

| 限制 | 说明 |
|------|------|
| 需要浏览器登录 | 必须用 Playwright 打开 `xhs-profile` 并手动完成小红书登录，一次登录后 Cookie 长期有效 |
| `xsec_token` 时效性 | API 返回的 token 理论上有时效，但实测同次 session 内有效 |
| 非视频笔记（含混合图文+视频） | `type=normal` 的笔记会被完全跳过，无法识别其中嵌入的视频 |
| 并发限制 | 当前批量下载为串行，不支持并发，单用户下载速度约 2 视频/分钟 |
| Profile 单进程限制 | 同一时间只能运行一个使用该 Profile 的进程 |

### 4.3 服务信息

- **服务目录**: `video-analysis-loader-xhs-wip/`（原 plan-a，已重命名）
- **端口**: `8001`
- **启动命令**:
  ```bash
  cd video-analysis-loader-xhs-wip
  python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8001
  ```
- **主要 API**:
  ```
  POST /api/download   # 单视频或用户主页批量下载
  GET  /api/platforms  # 支持的平台列表
  ```

---

## 五、下一步建议

### 5.1 优先级高（影响可用性）

**① XHS 登录流程文档化**

目前需要开发者手动操作浏览器完成登录。建议：
- 增加 `POST /api/xhs/login-status` 接口，检测当前 Profile 的登录状态
- 在前端 UI 增加"登录状态"指示灯，未登录时引导用户操作

**② 进度实时推送**

当前批量下载（如 32 个视频需 6 分钟）走同步接口，前端无法知道进度。已有 Douyin 的 `/api/download/user-stream` SSE 实现作为参考，建议为 XHS 也增加 SSE 流式接口：
```
POST /api/download/xhs-user-stream → SSE 事件流
```

**③ 混合笔记（图文+视频）支持**

`type=normal` 中部分笔记实际包含视频。改进方法：对 `type=normal` 的笔记也尝试拦截视频响应，有则下载，无则跳过，消除现有的漏下载问题。

### 5.2 优先级中（提升健壮性）

**④ Token 失效重试**

`xsec_token` 可能在 session 刷新后失效。建议：遇到 404 时自动重新打开用户主页刷新 token 列表，最多重试 1 次。

**⑤ 视频去重优化**

现有去重逻辑依赖文件名含 `note_id`，但视频标题中含 `note_id` 的情况并不可靠。建议改为维护 `downloaded_ids.json` 文件，精确记录已下载的 note_id 集合。

**⑥ 并发下载支持**

目前串行下载，约 2 个视频/分钟。可以改为有限并发（如同时下载 3 个），预计速度提升 2-3 倍。注意限流策略，避免账号被封。

### 5.3 优先级低（架构整合）

**⑦ 合并到主 Loader**

目前 XHS 下载器在独立的 `xhs-wip` 项目中运行。待稳定后，建议将 `RedNoteDownloader` 合并回 `video-analysis-loader`（端口 8000），统一前端入口。

**⑧ 接入下游流水线**

XHS 下载完成后，视频文件可自动送入 `video-analysis-cleaner` 进行 ASR 转写，再进入 `video-analysis-maker` 生成人格画像，打通完整流水线。

---

## 附录：关键文件路径

```
video-analysis-loader-xhs-wip/
├── src/
│   ├── downloaders/
│   │   └── rednote.py              # XHS 下载器主逻辑
│   ├── services/
│   │   ├── download_service.py     # download_xhs_user_videos_stream()
│   │   └── browser_manager.py      # 浏览器单例管理
│   └── api/
│       └── routes.py               # /api/download 路由
└── test_token_url.py               # 验证 xsec_token URL 可用性
```

浏览器 Profile 目录（含登录 Cookie）：
```
%LocalAppData%\video-analysis\xhs-profile\
```
