import type {
  Chapter, Line, Progress, Project, PipelineStatusResponse, Voice,
  SfxAsset, SfxCategory, Cue,
} from './types'

const BASE = '/api'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

// ── Project ───────────────────────────────────────────────────────────────────

export async function createProject(params: {
  epub_path: string
  llm_model_path: string
  tts_model_dir: string
  speakers?: string[]
}): Promise<{ project_id: number; project: Project; progress: Progress }> {
  return req('/project', { method: 'POST', body: JSON.stringify(params) })
}

export async function getProject(
  name: string,
): Promise<{ project: Project; progress: Progress }> {
  return req(`/project/${encodeURIComponent(name)}`)
}

export async function listProjects(): Promise<{
  projects: (Project & { progress: Progress })[]
}> {
  return req('/projects')
}

// ── Chapters ──────────────────────────────────────────────────────────────────

export async function getChapters(
  projectId: number,
): Promise<{ chapters: Chapter[]; total: number }> {
  return req(`/chapters/${projectId}`)
}

export async function getLines(
  chapterId: number,
): Promise<{ lines: Line[]; total: number }> {
  return req(`/chapters/${chapterId}/lines`)
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

export async function startPipeline(params: {
  project_name: string
  llm_model_path: string
  tts_model_dir: string
  speakers?: string[]
  chapter_range?: [number, number] | null
  output_format?: string
  vram_check_enabled?: boolean
  sfx_enabled?: boolean
}): Promise<{ status: string }> {
  return req('/pipeline/start', { method: 'POST', body: JSON.stringify(params) })
}

export async function pausePipeline(): Promise<{ status: string }> {
  return req('/pipeline/pause', { method: 'POST' })
}

export async function resumePipeline(): Promise<{ status: string }> {
  return req('/pipeline/resume', { method: 'POST' })
}

export async function stopPipeline(): Promise<{ status: string }> {
  return req('/pipeline/stop', { method: 'POST' })
}

export async function getPipelineStatus(): Promise<PipelineStatusResponse> {
  return req('/pipeline/status')
}

// ── Voices ────────────────────────────────────────────────────────────────────

export async function getVoices(): Promise<{ voices: Voice[] }> {
  return req('/voices')
}

export async function uploadVoice(
  speaker: string,
  file: File,
): Promise<Voice> {
  const form = new FormData()
  form.append('speaker', speaker)
  form.append('file', file)
  const res = await fetch(`${BASE}/voices/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `${res.status}`)
  }
  return res.json()
}

export async function deleteVoice(speaker: string): Promise<void> {
  await req(`/voices/${encodeURIComponent(speaker)}`, { method: 'DELETE' })
}

// ── Audio ─────────────────────────────────────────────────────────────────────

export function audioUrl(chapterId: number): string {
  return `${BASE}/audio/${chapterId}`
}

export function voiceAudioUrl(speaker: string): string {
  return `${BASE}/voices/${encodeURIComponent(speaker)}/audio`
}

export async function deleteChapterAudio(
  chapterId: number,
): Promise<{ deleted: number; file: string | null }> {
  return req(`/chapters/${chapterId}/audio`, { method: 'DELETE' })
}

export async function resetChapter(chapterId: number): Promise<{ reset: number }> {
  return req(`/chapters/${chapterId}/reset`, { method: 'POST' })
}

// ── External diarization import ────────────────────────────────────────────────

export interface LabelsPayload {
  chapter_id?: number
  labels: { i: number; speaker: string; emotion: string }[]
}

/** Download URL for a chapter's deterministic segments (external diarization). */
export function chapterSegmentsUrl(chapterId: number): string {
  return `${BASE}/chapters/${chapterId}/segments`
}

/** Import externally-produced speaker/emotion labels → status 'diarized'. */
export async function importChapterLabels(
  chapterId: number,
  body: LabelsPayload,
  force = false,
): Promise<{ chapter_id: number; lines: number; status: string }> {
  return req(`/chapters/${chapterId}/labels${force ? '?force=true' : ''}`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export type DiarizeProvider = 'claude' | 'openai' | 'gemini'

/** One-click cloud diarization: server exports segments, calls the chosen cloud
 *  LLM (claude/openai/gemini), and imports the labels → status 'diarized'.
 *  `apiKey` is sent per request and never persisted server-side. */
export async function diarizeChapterCloud(
  chapterId: number,
  params: { provider: DiarizeProvider; apiKey: string; model?: string; force?: boolean },
): Promise<{ chapter_id: number; lines: number; status: string }> {
  return req(`/chapters/${chapterId}/diarize-cloud`, {
    method: 'POST',
    body: JSON.stringify({
      provider: params.provider,
      api_key: params.apiKey,
      model: params.model,
      force: params.force ?? false,
    }),
  })
}

export async function resetChapters(params: {
  project_id: number
  status_filter?: string[] | null
  chapter_range?: [number, number] | null
}): Promise<{ reset: number[]; count: number }> {
  return req('/chapters/reset-range', { method: 'POST', body: JSON.stringify(params) })
}

// ── Sound design: library (sfx assets) ──────────────────────────────────────

export async function getSfx(): Promise<{ sfx: SfxAsset[] }> {
  return req('/sfx')
}

export async function uploadSfx(
  tag: string,
  category: SfxCategory,
  file: File,
  opts?: { loopable?: boolean; displayName?: string },
): Promise<{ tag: string; category: string; audio_path: string; loopable: boolean }> {
  const form = new FormData()
  form.append('tag', tag)
  form.append('category', category)
  form.append('loopable', String(opts?.loopable ?? category !== 'sfx'))
  if (opts?.displayName) form.append('display_name', opts.displayName)
  form.append('file', file)
  const res = await fetch(`${BASE}/sfx/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `${res.status}`)
  }
  return res.json()
}

export async function deleteSfx(tag: string): Promise<void> {
  await req(`/sfx/${encodeURIComponent(tag)}`, { method: 'DELETE' })
}

export function sfxAudioUrl(tag: string): string {
  return `${BASE}/sfx/${encodeURIComponent(tag)}/audio`
}

// ── Sound design: per-chapter cues ──────────────────────────────────────────

export async function getCues(
  chapterId: number,
): Promise<{ chapter_id: number; cues: Cue[]; reviewed: boolean }> {
  return req(`/chapters/${chapterId}/cues`)
}

/** Replace a chapter's cues with a hand-edited set; marks it reviewed. */
export async function putCues(
  chapterId: number,
  cues: Cue[],
): Promise<{ chapter_id: number; cues: number; reviewed: boolean }> {
  return req(`/chapters/${chapterId}/cues`, {
    method: 'PUT',
    body: JSON.stringify({ cues }),
  })
}

/** One-click cloud sound design: server exports segments, calls the chosen
 *  cloud LLM, and imports the cue plan. Key sent per request, never persisted. */
export async function generateCuesCloud(
  chapterId: number,
  params: { provider: DiarizeProvider; apiKey: string; model?: string; force?: boolean },
): Promise<{ chapter_id: number; cues: number }> {
  return req(`/chapters/${chapterId}/cues-cloud`, {
    method: 'POST',
    body: JSON.stringify({
      provider: params.provider,
      api_key: params.apiKey,
      model: params.model,
      force: params.force ?? false,
    }),
  })
}

/** Import a raw {"sound_design": {...}} cue plan (e.g. pasted from Claude). */
export async function importCues(
  chapterId: number,
  payload: unknown,
  force = false,
): Promise<{ chapter_id: number; cues: number }> {
  return req(`/chapters/${chapterId}/cues/import${force ? '?force=true' : ''}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function cuesExportUrl(chapterId: number): string {
  return `${BASE}/chapters/${chapterId}/cues-export`
}
