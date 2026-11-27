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
  /** The book's own chapter number (1994) — positions (chapter_index) are EPUB order only. */
  chapter_number?: number | null
  /** "Chapter 1994: Call to Arms", cleaned from the EPUB heading. */
  display_title?: string | null
  /** 'front' = synopsis page, 'back' = contents/credits page (never narrated). */
  kind?: 'chapter' | 'front' | 'back' | null
}

/** Extra generation options chosen in the Setup panel, forwarded to startPipeline. */
export interface GenOptions {
  /** 0-based [start, end] chapter_index range, inclusive — or null for the whole book. */
  chapterRange: [number, number] | null
  /** Real chapter numbers [first, last] as printed in the book; wins over chapterRange. */
  chapterNumbers?: [number, number] | null
  outputFormat: string
  vramCheck: boolean
  /** Master switch — layer reviewed cues under the voice at assembly time. */
  sfxEnabled: boolean
  /** Which of the three layers to render when enabled. Empty => none (off). */
  sfxCategories: SfxCategory[]
}

export interface Voice {
  id: number
  speaker: string
  ref_audio_path: string
  updated_at: string
}

export interface Line {
  spoken_text?: string
  review_reason?: string | null
  attribution?: {
    /** Legacy diarizer methods, 'manual', or '<labeller>:<how>' e.g. 'qwen-v1:agree'. */
    method: 'explicit' | 'inferred' | 'exchange' | 'vocative' | 'fallback' | 'manual' | string
    cue_indices: number[]
    votes?: (string | null)[]
    gender?: string
    /** Stand-in voice for a speaker without a cast voice of their own. */
    voice_as?: string
  } | null
  speaker_locked?: number
  spoken_override?: string | null
  id: number
  line_index: number
  speaker: string
  text: string
  emotion: string
  status: 'pending' | 'tts_done' | 'failed'
  audio_path: string | null
  error_message: string | null
  performance?: {
    start_ms: number; end_ms: number; renderer: string; fallback: boolean
    audit: { status?: string; review?: boolean; heard?: string; reason?: string }
  }
}

export type SfxCategory = 'ambience' | 'sfx' | 'music'

export interface SfxAsset {
  id: number
  tag: string
  category: SfxCategory
  audio_path: string
  display_name: string | null
  loopable: number
  created_at: string
  updated_at: string
}

export type CueType = 'scene' | 'sfx' | 'music'

export interface Cue {
  id?: number
  chapter_id?: number
  cue_type: CueType
  tag: string
  line_start: number
  line_end: number | null
  at_anchor: 'start' | 'end' | null
  gain_db: number
  duration_s: number | null
  source?: string
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
  speech_eta_s?: number | null
  /** Live line being synthesised (truncated server-side to ~200 chars). */
  text?: string
  speaker?: string
  emotion?: string
  [key: string]: unknown
}
