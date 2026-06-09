export type ChapterStatus =
  | 'pending' | 'diarized' | 'tts_done'
  | 'assembled' | 'complete' | 'error'

export interface Project {
  id: number
  name: string
  source_epub: string
  total_chapters: number
  created_at: string
}

export interface Progress {
  total: number
  pending: number
  diarized: number
  tts_done: number
  assembled: number
  complete: number
  error: number
  pct_complete: number
}

export interface Chapter {
  id: number
  project_id: number
  chapter_index: number
  title: string
  status: ChapterStatus
  total_chunks: number
  total_lines: number
  output_audio_path: string | null
  output_file_size_bytes: number | null
  processing_seconds: number | null
  error_message: string | null
  updated_at: string
}

export interface Voice {
  id: number
  speaker: string
  ref_audio_path: string
  ref_text: string
  updated_at: string
}

export interface PipelineStatusResponse {
  status: 'idle' | 'running' | 'paused' | 'complete' | 'error' | 'stopped'
  last_results: { success: number; error: number; skipped: number } | null
  event_count: number
  last_event: SSEEvent | null
}

export interface SSEEvent {
  type: string
  ts: number
  chapter_id?: number
  chapter_index?: number
  title?: string
  stage?: string
  elapsed_s?: number
  audio_path?: string
  error?: string | number
  success?: number
  skipped?: number
  total?: number
  project?: string
  stages?: string[]
  used_mb?: number
  threshold_mb?: number
  // tts_progress fields
  lines_done?: number
  lines_total?: number
  [key: string]: unknown
}
