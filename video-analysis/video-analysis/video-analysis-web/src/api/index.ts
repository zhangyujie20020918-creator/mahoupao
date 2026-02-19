/**
 * API 服务
 */

import axios from 'axios'
import type { Platform, VideoInfo, DownloadResponse, DownloadRequest, StreamEvent } from '../types/api'

const api = axios.create({
  baseURL: '/api',
  timeout: 300000, // 5分钟超时（视频下载可能较慢）
})

/**
 * 获取支持的平台列表
 */
export async function getPlatforms(): Promise<Platform[]> {
  const { data } = await api.get<{ platforms: Platform[] }>('/platforms')
  return data.platforms
}

/**
 * 获取默认下载目录
 */
export async function getDefaultDir(): Promise<string> {
  const { data } = await api.get<{ path: string }>('/download/default-dir')
  return data.path
}

/**
 * 获取视频信息
 */
export async function getVideoInfo(url: string): Promise<VideoInfo> {
  const { data } = await api.post<VideoInfo>('/info', { url })
  return data
}

/**
 * 下载视频
 */
export async function downloadVideo(request: DownloadRequest): Promise<DownloadResponse> {
  const { data } = await api.post<DownloadResponse>('/download', request)
  return data
}

/**
 * 流式下载用户主页视频（SSE）
 * 返回一个 AbortController 用于取消，通过 onEvent 回调接收事件
 */
export function downloadUserVideosStream(
  request: DownloadRequest,
  onEvent: (event: StreamEvent) => void,
  onError: (error: string) => void,
): AbortController {
  const controller = new AbortController()

  fetch('/api/download/user-stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: '请求失败' }))
        onError(err.detail || `HTTP ${response.status}`)
        return
      }

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        // 解析 SSE: "data: {...}\n\n"
        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          const line = part.trim()
          if (line.startsWith('data: ')) {
            try {
              const event: StreamEvent = JSON.parse(line.slice(6))
              onEvent(event)
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        onError(err.message || '连接失败')
      }
    })

  return controller
}

/**
 * 验证URL是否支持
 */
export async function validateUrl(url: string): Promise<boolean> {
  const { data } = await api.post<{ supported: boolean }>('/validate', { url })
  return data.supported
}

export default api
