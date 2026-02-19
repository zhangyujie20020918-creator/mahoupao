/**
 * API 类型定义
 */

export interface Platform {
  name: string
  value: string
  domains: string[]
}

export interface VideoInfo {
  url: string
  platform: string
  video_id: string
  title: string
  author?: string
  duration?: number
  thumbnail?: string
  description?: string
  view_count?: number
  like_count?: number
  available_qualities: string[]
}

export interface DownloadResponse {
  success: boolean
  message: string
  video_info?: VideoInfo
  file_path?: string
  file_size?: number
  file_size_human?: string
  elapsed_time?: number
}

export interface DownloadRequest {
  url: string
  platform?: string
  quality: 'best' | '1080p' | '720p' | '480p'
  audio_only: boolean
  output_dir?: string
  folder_name?: string
}

export interface BatchDownloadItem {
  title: string
  success: boolean
  file_path?: string
  file_size_human?: string
  error?: string
}

export interface BatchDownloadResponse {
  success: boolean
  message: string
  total: number
  succeeded: number
  failed: number
  results: BatchDownloadItem[]
  elapsed_time?: number
}

/** SSE 流式下载事件 */
export interface StreamEvent {
  type: 'extracting' | 'extracted' | 'downloading' | 'downloaded' | 'done' | 'error'
  message?: string
  index?: number
  total?: number
  url?: string
  title?: string
  success?: boolean
  file_path?: string
  file_size_human?: string
  error?: string
  succeeded?: number
  failed?: number
  elapsed_time?: number
  folder_path?: string
  // 重试相关字段
  attempt?: number
  permanently_failed?: boolean
  succeeded_so_far?: number
  remaining?: number
  skipped_videos?: Array<{ url: string; title: string; error: string }>
}

export type DownloadStatus = 'idle' | 'loading' | 'success' | 'error'
