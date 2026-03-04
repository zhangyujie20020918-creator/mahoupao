# 开发进度 - 2026-02-26

## 真实流式输出 + 多气泡 + 句子级 TTS（续）

延续 2026-02-25 的流式改造工作，今天主要修复了断句、音频播放、气泡对齐三大核心问题。

---

### 1. 前端多气泡 UI 完成

**文件**: `video-analysis-web/soul.html`

完成了前端 SSE 多气泡处理的剩余工作：

- **`handleSSEEvent` 全面重写** — 支持新的事件协议：
  - `message_start`: 按 `groupId + sentenceId` 创建新气泡
  - `token`: 追加内容到对应 `sentenceId` 的气泡（含 fallback 自动创建）
  - `sentence_end`: 标记单个气泡完成
  - `audio`: 将音频绑定到对应 `sentenceId` 的气泡
  - `done`: 收尾所有气泡，将 sources 附加到第一个气泡
  - `error`: 创建错误气泡

- **`findSentenceMessage(groupId, sentenceId)`** — 新增 helper 方法

- **HTML 模板更新** — 分组 assistant 消息：
  - 头像/昵称/时间戳仅在组内第一条显示
  - 非首条使用 `message-avatar-placeholder` 占位 + `message-grouped` CSS（间距缩小）
  - `v-show` 改为 `msg.content || msg.isStreaming`（正确显示正在接收的空气泡）

---

### 2. TTS 服务优化

**文件**: `video-analysis-soul/services/tts_service.py`

- 用持久 `httpx.AsyncClient` 替换每次请求创建的临时 client
- 新增 `_get_client()` 懒初始化 + `close()` 方法（由 `engine.stop()` 调用）
- 消除了每次 TTS 调用的 TCP 连接建立开销

**文件**: `video-analysis-soul/core/engine.py`

- 新增 `asyncio.Semaphore(1)` 串行化 TTS 请求
- GPT-SoVITS 是单 GPU 服务，并发请求会导致后面的全部超时
- Semaphore 保证客户端排队，每个请求有独立的 30s 超时窗口

---

### 3. 断句算法大幅改进

**文件**: `video-analysis-soul/common/utils/text.py`

#### 问题
原始断句有三个严重问题：
1. **后向扫描** — 找最后一个断点，导致多个句子合并到一个气泡
2. **所有标点同等对待** — `！` 在强调句式中频繁错误断句（如 "AI是主线！AI是主线！AI是主线！"）
3. **不识别编号列表** — `1. 2. 3.` 应该是最高优先级断点

#### 解决方案：前向扫描 + 分层阈值

```
断点优先级（从高到低）:
1. 编号列表 (\n + 数字.)  → min_length 即可（~8字符）
2. 段落换行 (\n\n)        → min_length 即可
3. 句号 (。/ 英文.)       → >= 20 字符
4. 分号/省略号 (；…)      → >= 30 字符
5. 感叹/问号 (！？/ !?)   → >= 80 字符（保护强调句式）
6. 单独换行 (\n)          → >= 20 字符
7. 逗号兜底 (，、：)      → >= 80 字符
```

- `_LIST_PATTERN = re.compile(r"\n(?=\s*\d+[.、)）]\s*)")` 识别编号列表
- 感叹号/问号阈值 80 字符，避免 "AI是主线！AI是主线！" 被切碎
- 逗号仅在超长无标点文本中兜底

#### 气泡数量上限

**文件**: `video-analysis-soul/common/config.py`

`StreamingConfig` 新增 `max_bubbles: int = 4`。达到上限后停止断句，剩余内容全部追加到最后一个气泡。

---

### 4. 修复音频不显示的根因

**文件**: `video-analysis-web/soul.html`

#### Bug: SSE `currentEvent` 变量在每次 `processLines()` 调用时重置

```javascript
// 旧代码 — BUG
function processLines(text) {
    var currentEvent = '';  // ← 每次调用都重置！
    ...
}

// 修复 — currentEvent 移到外部作用域
var buffer = '';
var currentEvent = '';  // ← 跨调用持久
function processLines(text) {
    ...
}
```

**原理**：音频 base64 数据量大（1~2MB），浏览器 `reader.read()` 会分多个 chunk 接收：
- Chunk 1: `event: audio\n` → `currentEvent = 'audio'` ✓
- Chunk 2-N: base64 数据（buffer 积累中）
- 最终 Chunk: `data: {...}\n\n` → 此时 `currentEvent` 已被重置为 `''` ✗

小事件（token、thinking）不受影响，因为它们小到能在一个 chunk 里完整接收。

#### 改进: Data URI → Blob URL

```javascript
// 旧代码 — data URI 可能超过浏览器限制
msg.audioSrc = 'data:audio/wav;base64,' + data.audio_base64;

// 新代码 — Blob URL 无大小限制
var raw = atob(data.audio_base64);
var bytes = new Uint8Array(raw.length);
for (var bi = 0; bi < raw.length; bi++) bytes[bi] = raw.charCodeAt(bi);
var blob = new Blob([bytes], { type: 'audio/' + fmt });
msg.audioSrc = URL.createObjectURL(blob);
```

---

### 5. 修复气泡内容与断句/TTS 不对齐

**文件**: `video-analysis-soul/core/engine.py`

#### Bug: Token 先推送再检查断句

旧流程：
```
token 到达 → 立即推送给前端 (sid=0) → 检查断句 → 发现断点 → 切换到 sid=1
```

如果 token = `"步！\n\n今天"`，整个 token 已推给气泡0，但 `"今天"` 应该在气泡1。

#### 修复：先检查断句，再按正确 sentence_id 推送

```python
# 新流程
old_len = len(current_sentence)
current_sentence += token

boundary = find_sentence_boundary(current_sentence, min_len)

if boundary < 0:
    # 无断点，整个 token 推送
    yield token → sid=当前
else:
    # 有断点，拆分 token
    split_pos = boundary + 1 - old_len
    token_before = token[:split_pos]   # → 当前气泡
    token_after  = token[split_pos:]   # → 下一个气泡

    yield token_before → sid=当前
    yield sentence_end(当前)
    yield message_start(下一个)
    yield token_after → sid=下一个
```

这样前端气泡内容和 TTS 合成文本完全一致，`sentence_id` 精确匹配。

---

### 6. 诊断日志

**后端** (`engine.py`):
- TTS yield 前后添加日志：`"Awaiting N TTS tasks for sentences: [0, 1, 2]"`
- 每个音频事件：`"Yielding audio event: sentence=0, base64_bytes=476220, duration=5.6s"`
- TTS 无结果：`"No audio for sentence 0 (result=None/empty)"`

**前端** (`soul.html`):
- `console.log('[SSE] audio event: ...')` — 确认音频事件到达
- `console.error('[SSE] JSON parse failed ...')` — 不再静默吞掉解析错误
- `console.log('[SSE] done event received')` — 确认事件序列

---

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `video-analysis-web/soul.html` | handleSSEEvent 重写、findSentenceMessage、分组模板、currentEvent 修复、Blob URL、诊断日志 |
| `video-analysis-soul/common/utils/text.py` | 断句算法：前向扫描 + 分层阈值 + 编号列表检测 |
| `video-analysis-soul/common/config.py` | StreamingConfig 新增 max_bubbles=4 |
| `video-analysis-soul/core/engine.py` | Token 拆分对齐、TTS semaphore、TTS yield 日志 |
| `video-analysis-soul/services/tts_service.py` | 持久 httpx client + close() |
