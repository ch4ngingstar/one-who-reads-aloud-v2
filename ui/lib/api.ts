import type { Chapter, Progress, Project, PipelineStatusResponse, Voice } from './types'

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
  fish_speech_dir: string
  speakers?: string[]
}): Promise<{ project_id: number; project: Project; progress: Progress }> {
  return req('/project', { method: 'POST', body: JSON.stringify(params) })
}

export async function getProject(
  name: string,
): Promise<{ project: Project; progress: Progress }> {
  return req(`/project/${encodeURIComponent(name)}`)
}

// ── Chapters ──────────────────────────────────────────────────────────────────

export async function getChapters(
  projectId: number,
): Promise<{ chapters: Chapter[]; total: number }> {
  return req(`/chapters/${projectId}`)
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

export async function startPipeline(params: {
  project_name: string
  llm_model_path: string
  fish_speech_dir: string
  speakers?: string[]
  chapter_range?: [number, number] | null
  output_format?: string
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

export async function setVoicePath(
  speaker: string,
  ref_audio_path: string,
  ref_text = '',
): Promise<Voice> {
  return req('/voices', {
    method: 'POST',
    body: JSON.stringify({ speaker, ref_audio_path, ref_text }),
  })
}

export async function uploadVoice(
  speaker: string,
  file: File,
  ref_text = '',
): Promise<Voice> {
  const form = new FormData()
  form.append('speaker', speaker)
  form.append('file', file)
  form.append('ref_text', ref_text)
  const res = await fetch(`${BASE}/voices/upload`, { method: 'POST', body: form })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body?.detail ?? `${res.status}`)
  }
  return res.json()
}

export async function updateVoiceRefText(
  speaker: string,
  ref_text: string,
): Promise<{ speaker: string; ref_text: string }> {
  return req(`/voices/${encodeURIComponent(speaker)}/ref_text`, {
    method: 'PATCH',
    body: JSON.stringify({ ref_text }),
  })
}

export async function deleteVoice(speaker: string): Promise<void> {
  await req(`/voices/${encodeURIComponent(speaker)}`, { method: 'DELETE' })
}

// ── Audio ─────────────────────────────────────────────────────────────────────

export function audioUrl(chapterId: number): string {
  return `${BASE}/audio/${chapterId}`
}

export async function deleteChapterAudio(
  chapterId: number,
): Promise<{ deleted: number; file: string | null }> {
  return req(`/chapters/${chapterId}/audio`, { method: 'DELETE' })
}

export async function resetChapter(chapterId: number): Promise<{ reset: number }> {
  return req(`/chapters/${chapterId}/reset`, { method: 'POST' })
}
