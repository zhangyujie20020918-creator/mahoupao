<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { getPlatforms, getDefaultDir, downloadVideo, downloadUserVideosStream } from './api'
import type { Platform, DownloadResponse, DownloadStatus, StreamEvent } from './types/api'

// 表单状态
const platforms = ref<Platform[]>([])
const selectedPlatform = ref<string>('')
const videoUrl = ref<string>('')
const quality = ref<'best' | '1080p' | '720p' | '480p'>('best')
const outputDir = ref<string>('')
const folderName = ref<string>('')

const status = ref<DownloadStatus>('idle')
const result = ref<DownloadResponse | null>(null)
const errorMessage = ref<string>('')

// 流式下载状态
const streamEvents = ref<StreamEvent[]>([])
const streamPhase = ref<string>('')
const streamTotal = ref(0)
const streamSucceeded = ref(0)
const streamFailed = ref(0)
const streamRemaining = ref(0)
const streamElapsed = ref(0)
const streamFolderPath = ref('')
const streamSkippedVideos = ref<Array<{ url: string; title: string; error: string }>>([])
const streamAbort = ref<AbortController | null>(null)
const progressListEl = ref<HTMLElement | null>(null)

// 是否为用户主页URL
const isUserProfileUrl = computed(() => videoUrl.value.includes('/user/'))

// 最终保存路径预览
const resolvedPath = computed(() => {
  let p = outputDir.value || '(默认目录)'
  if (folderName.value.trim()) {
    p += '/' + folderName.value.trim()
  }
  return p
})

// 下载进度列表（只显示已完成的）
const downloadedItems = computed(() =>
  streamEvents.value.filter(e => e.type === 'downloaded')
)

// 当前正在下载的视频序号
const currentDownloading = computed(() => {
  const ev = streamEvents.value.filter(e => e.type === 'downloading')
  return ev.length > 0 ? ev[ev.length - 1] : null
})

// 画质选项
const qualityOptions = [
  { value: 'best', label: '最佳画质' },
  { value: '1080p', label: '1080P' },
  { value: '720p', label: '720P' },
  { value: '480p', label: '480P' },
] as const

// 初始化
onMounted(async () => {
  try {
    const [platformList, defaultDir] = await Promise.all([
      getPlatforms(),
      getDefaultDir(),
    ])
    platforms.value = platformList
    outputDir.value = defaultDir
    if (platformList.length > 0) {
      selectedPlatform.value = platformList[0].value
    }
  } catch (e) {
    console.error('初始化失败:', e)
    errorMessage.value = '无法连接后端服务，请确认已启动 python run_server.py'
  }
})

function scrollProgressToBottom() {
  nextTick(() => {
    if (progressListEl.value) {
      progressListEl.value.scrollTop = progressListEl.value.scrollHeight
    }
  })
}

function resetStreamState() {
  streamEvents.value = []
  streamPhase.value = ''
  streamTotal.value = 0
  streamSucceeded.value = 0
  streamFailed.value = 0
  streamRemaining.value = 0
  streamElapsed.value = 0
  streamFolderPath.value = ''
  streamSkippedVideos.value = []
  if (streamAbort.value) {
    streamAbort.value.abort()
    streamAbort.value = null
  }
}

// 构建请求对象
function buildRequest() {
  return {
    url: videoUrl.value.trim(),
    platform: selectedPlatform.value,
    quality: quality.value as 'best' | '1080p' | '720p' | '480p',
    audio_only: false,
    output_dir: outputDir.value.trim() || undefined,
    folder_name: folderName.value.trim() || undefined,
  }
}

// 提交下载
async function handleSubmit() {
  if (!videoUrl.value.trim()) {
    errorMessage.value = '请输入视频URL'
    return
  }

  status.value = 'loading'
  result.value = null
  errorMessage.value = ''
  resetStreamState()

  const request = buildRequest()

  // 用户主页URL → 流式下载
  if (isUserProfileUrl.value) {
    streamPhase.value = 'starting'
    const controller = downloadUserVideosStream(
      request,
      (event: StreamEvent) => {
        streamEvents.value.push(event)
        switch (event.type) {
          case 'extracting':
            streamPhase.value = 'extracting'
            break
          case 'extracted':
            streamPhase.value = 'downloading'
            streamTotal.value = event.total || 0
            streamRemaining.value = event.total || 0
            break
          case 'downloading':
            if (event.succeeded_so_far !== undefined) {
              streamSucceeded.value = event.succeeded_so_far
            }
            if (event.remaining !== undefined) {
              streamRemaining.value = event.remaining
            }
            break
          case 'downloaded':
            if (event.success) {
              streamSucceeded.value = event.succeeded_so_far ?? (streamSucceeded.value + 1)
              streamRemaining.value = event.remaining ?? streamRemaining.value
            } else if (event.permanently_failed) {
              streamFailed.value++
              streamRemaining.value = event.remaining ?? streamRemaining.value
            }
            scrollProgressToBottom()
            break
          case 'done':
            streamPhase.value = 'done'
            streamSucceeded.value = event.succeeded || 0
            streamFailed.value = event.failed || 0
            streamElapsed.value = event.elapsed_time || 0
            streamFolderPath.value = event.folder_path || ''
            streamSkippedVideos.value = event.skipped_videos || []
            status.value = (event.succeeded || 0) > 0 ? 'success' : 'error'
            streamAbort.value = null
            break
          case 'error':
            streamPhase.value = 'error'
            errorMessage.value = event.message || '未知错误'
            status.value = 'error'
            streamAbort.value = null
            break
        }
      },
      (error: string) => {
        errorMessage.value = error
        status.value = 'error'
        streamPhase.value = 'error'
        streamAbort.value = null
      },
    )
    streamAbort.value = controller
    return
  }

  // 单个视频下载
  try {
    const response = await downloadVideo(request)
    if ('total' in response) {
      status.value = (response as any).success ? 'success' : 'error'
    } else {
      result.value = response
      status.value = response.success ? 'success' : 'error'
      if (!response.success) errorMessage.value = response.message
    }
  } catch (e: any) {
    status.value = 'error'
    errorMessage.value = e.response?.data?.detail || e.message || '下载失败'
  }
}
</script>

<template>
  <div class="app-layout">
    <!-- 左侧：下载管理面板 -->
    <aside class="progress-panel">
      <h2 class="panel-title">下载管理</h2>

      <!-- 下载目录配置 -->
      <div class="dm-section">
        <label class="dm-label">下载位置</label>
        <input
          v-model="outputDir"
          type="text"
          class="dm-input"
          placeholder="输入下载目录路径..."
          :disabled="status === 'loading'"
        />
      </div>
      <div class="dm-section">
        <label class="dm-label">文件夹名称</label>
        <input
          v-model="folderName"
          type="text"
          class="dm-input"
          placeholder="新建文件夹（可选）"
          :disabled="status === 'loading'"
        />
      </div>
      <div v-if="folderName.trim()" class="dm-path-preview">
        {{ resolvedPath }}
      </div>

      <div class="dm-divider"></div>

      <!-- 空状态 -->
      <div v-if="streamEvents.length === 0 && !result && status !== 'error'" class="panel-empty">
        <p>尚无下载任务</p>
      </div>

      <!-- 流式进度 -->
      <div v-if="streamPhase === 'extracting' || streamPhase === 'starting'" class="phase-banner phase-extracting">
        <span class="spinner spinner-sm"></span>
        正在提取视频链接...
      </div>
      <div v-if="streamPhase === 'downloading' || streamPhase === 'done'" class="phase-banner phase-downloading">
        已提取 {{ streamTotal }} 个视频 | 已下载 {{ streamSucceeded }}/{{ streamTotal }}
      </div>

      <div v-if="currentDownloading && streamPhase === 'downloading'" class="current-download">
        <span class="spinner spinner-sm"></span>
        正在下载第 {{ currentDownloading.index }} 个
        <span v-if="currentDownloading.attempt && currentDownloading.attempt > 1" class="retry-badge">
          第{{ currentDownloading.attempt }}次尝试
        </span>
        <span class="current-download-remaining">剩余 {{ streamRemaining }}</span>
      </div>

      <!-- 下载列表 -->
      <div v-if="downloadedItems.length > 0" ref="progressListEl" class="progress-list">
        <div
          v-for="(item, idx) in downloadedItems"
          :key="idx"
          class="progress-item"
          :class="[
            item.success ? 'progress-item-ok' : 'progress-item-fail',
            item.permanently_failed ? 'progress-item-skipped' : ''
          ]"
        >
          <span class="progress-item-idx">{{ item.index }}</span>
          <span class="progress-item-icon">{{ item.success ? '\u2713' : (item.permanently_failed ? '\u2716' : '\u21BB') }}</span>
          <div class="progress-item-body">
            <div class="progress-item-title">{{ item.title || '未知' }}</div>
            <div v-if="item.file_path" class="progress-item-path">{{ item.file_path }}</div>
            <div v-if="item.file_size_human" class="progress-item-size">{{ item.file_size_human }}</div>
            <div v-if="!item.success && item.error" class="progress-item-error">{{ item.error }}</div>
          </div>
        </div>
      </div>

      <!-- 完成汇总 -->
      <div v-if="streamPhase === 'done'" class="phase-summary">
        <div class="summary-row">
          <span>成功</span>
          <strong class="text-success">{{ streamSucceeded }}</strong>
        </div>
        <div class="summary-row">
          <span>失败</span>
          <strong class="text-error">{{ streamFailed }}</strong>
        </div>
        <div class="summary-row">
          <span>耗时</span>
          <strong>{{ streamElapsed }}s</strong>
        </div>
        <div v-if="streamFolderPath" class="summary-folder">
          {{ streamFolderPath }}
        </div>
      </div>

      <!-- 需要手动确认的失败视频 -->
      <div v-if="streamSkippedVideos.length > 0" class="skipped-section">
        <h3 class="skipped-title">需要手动确认 ({{ streamSkippedVideos.length }})</h3>
        <div
          v-for="(video, idx) in streamSkippedVideos"
          :key="idx"
          class="skipped-item"
        >
          <div class="skipped-item-title">{{ video.title || '未知' }}</div>
          <div class="skipped-item-url">{{ video.url }}</div>
          <div class="skipped-item-error">{{ video.error }}</div>
        </div>
      </div>

      <!-- 单视频结果 -->
      <div v-if="result" class="single-result">
        <div class="progress-item" :class="result.success ? 'progress-item-ok' : 'progress-item-fail'">
          <span class="progress-item-icon">{{ result.success ? '\u2713' : '\u2717' }}</span>
          <div class="progress-item-body">
            <div class="progress-item-title">{{ result.video_info?.title || result.message }}</div>
            <div v-if="result.video_info?.author" class="progress-item-size">{{ result.video_info.author }}</div>
            <div v-if="result.file_size_human" class="progress-item-size">{{ result.file_size_human }}</div>
            <div v-if="result.file_path" class="progress-item-path">{{ result.file_path }}</div>
            <div v-if="result.elapsed_time" class="progress-item-size">{{ result.elapsed_time.toFixed(1) }}s</div>
            <div v-if="!result.success" class="progress-item-error">{{ result.message }}</div>
          </div>
        </div>
      </div>

      <!-- 错误 -->
      <div v-if="status === 'error' && errorMessage && !result && (streamPhase === 'error' || streamPhase === '')" class="phase-banner phase-error">
        {{ errorMessage }}
      </div>
    </aside>

    <!-- 右侧：下载表单 -->
    <main class="form-panel">
      <header>
        <h1 class="title">Video Downloader</h1>
        <p class="subtitle">支持 YouTube / TikTok / Bilibili / 小红书 / 抖音</p>
      </header>

      <div class="card">
        <form @submit.prevent="handleSubmit">
          <!-- 平台选择 -->
          <div class="form-group">
            <label class="form-label">选择平台</label>
            <select v-model="selectedPlatform" class="form-select">
              <option value="" disabled>请选择平台</option>
              <option v-for="p in platforms" :key="p.value" :value="p.value">
                {{ p.name }}
              </option>
            </select>
          </div>

          <!-- URL输入 -->
          <div class="form-group">
            <label class="form-label">视频链接</label>
            <input
              v-model="videoUrl"
              type="text"
              class="form-input"
              placeholder="粘贴视频URL 或 用户主页URL..."
              :disabled="status === 'loading'"
            />
            <p v-if="isUserProfileUrl" class="input-hint">检测到用户主页链接，将批量下载所有视频</p>
          </div>

          <!-- 画质选择 -->
          <div class="form-group">
            <label class="form-label">画质</label>
            <div class="quality-options">
              <button
                v-for="q in qualityOptions"
                :key="q.value"
                type="button"
                class="quality-option"
                :class="{ active: quality === q.value }"
                @click="quality = q.value"
              >
                {{ q.label }}
              </button>
            </div>
          </div>

          <!-- 提交按钮 -->
          <button type="submit" class="btn btn-primary" :disabled="status === 'loading'">
            <span v-if="status === 'loading'" class="spinner"></span>
            {{ status === 'loading' ? (isUserProfileUrl ? '批量下载中...' : '下载中...') : '开始下载' }}
          </button>
        </form>
      </div>

      <!-- 错误（非流式且非左侧已显示时） -->
      <div v-if="status === 'error' && errorMessage && !result && streamPhase !== 'error' && streamPhase !== ''" class="card result-card result-error">
        <h3 class="result-title">&cross; 错误</h3>
        <p>{{ errorMessage }}</p>
      </div>
    </main>
  </div>
</template>
