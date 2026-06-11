import { describe, it, expect } from 'vitest'
import {
  pipelineReducer, initialPipelineState, type PipelineUIState,
} from '@/hooks/usePipelineState'
import type { SSEEvent } from '@/lib/types'

const ev = (partial: Partial<SSEEvent> & { type: string }): SSEEvent =>
  ({ ts: 0, ...partial })

const sse = (s: PipelineUIState, e: SSEEvent) =>
  pipelineReducer(s, { kind: 'sse', event: e, now: 1000 })

describe('pipelineReducer', () => {
  it('tracks a chapter through synthesis and exposes the live line', () => {
    let s = sse(initialPipelineState, ev({ type: 'pipeline_start' }))
    expect(s.startedAt).toBe(1000)
    s = sse(s, ev({ type: 'chapter_start', chapter_id: 7 }))
    s = sse(s, ev({ type: 'stage_start', chapter_id: 7, stage: 'synthesize' }))
    s = sse(s, ev({
      type: 'tts_progress', chapter_id: 7, lines_done: 3, lines_total: 44,
      text: 'Sunny frowned.', speaker: 'Sunny', emotion: 'tense',
    }))
    expect(s.activeChId).toBe(7)
    expect(s.activeStage).toBe('synthesize')
    expect(s.ttsProgress[7]).toEqual({ done: 3, total: 44 })
    expect(s.liveLine).toEqual({ text: 'Sunny frowned.', speaker: 'Sunny', emotion: 'tense' })

    s = sse(s, ev({ type: 'chapter_done', chapter_id: 7 }))
    expect(s.activeChId).toBeNull()
    expect(s.liveLine).toBeNull()
    expect(s.refreshNonce).toBe(1)
  })

  it('keeps the previous live line when a tts_progress event has no text', () => {
    let s = sse(initialPipelineState, ev({
      type: 'tts_progress', chapter_id: 1, lines_done: 1, lines_total: 9,
      text: 'First.', speaker: 'Narrator', emotion: 'neutral',
    }))
    s = sse(s, ev({ type: 'tts_progress', chapter_id: 1, lines_done: 2, lines_total: 9 }))
    expect(s.liveLine?.text).toBe('First.')
    expect(s.ttsProgress[1]).toEqual({ done: 2, total: 9 })
  })

  it('chapter_error raises a crimson toast and bumps refreshNonce', () => {
    const s = sse(initialPipelineState, ev({ type: 'chapter_error', chapter_id: 3, error: 'CUDA OOM' }))
    expect(s.toasts).toHaveLength(1)
    expect(s.toasts[0].tone).toBe('crimson')
    expect(s.toasts[0].message).toContain('CUDA OOM')
    expect(s.refreshNonce).toBe(1)
  })

  it('pipeline_done sets status complete with a chrome toast', () => {
    const s = sse(initialPipelineState, ev({ type: 'pipeline_done', success: 12 }))
    expect(s.pipeStatus).toBe('complete')
    expect(s.toasts[0].tone).toBe('chrome')
  })

  it('vram_warning raises a warn toast and records vramMb', () => {
    const s = sse(initialPipelineState, ev({ type: 'vram_warning', used_mb: 7900, threshold_mb: 1500 }))
    expect(s.toasts[0].tone).toBe('warn')
    expect(s.vramMb).toBe(7900)
  })

  it('caps the event log at 500 entries', () => {
    let s = initialPipelineState
    for (let i = 0; i < 510; i++) s = sse(s, ev({ type: 'stage_done', ts: i }))
    expect(s.events).toHaveLength(500)
  })

  it('supports manual toasts and dismissal', () => {
    let s = pipelineReducer(initialPipelineState, { kind: 'toast', tone: 'crimson', message: 'Failed to stop' })
    const id = s.toasts[0].id
    s = pipelineReducer(s, { kind: 'dismiss-toast', id })
    expect(s.toasts).toHaveLength(0)
  })

  it('stage_start seeds activeChId when reconnecting mid-run (no prior chapter_start)', () => {
    // Simulates page reload while pipeline is running — last_event is a stage_start.
    const s = sse(initialPipelineState, ev({ type: 'stage_start', chapter_id: 256, stage: 'diarize' }))
    expect(s.activeChId).toBe(256)
    expect(s.activeStage).toBe('diarize')
  })

  it('tracks connection and explicit status changes', () => {
    let s = pipelineReducer(initialPipelineState, { kind: 'connection', connected: false })
    expect(s.connected).toBe(false)
    s = pipelineReducer(s, { kind: 'set-status', status: 'running' })
    expect(s.pipeStatus).toBe('running')
  })
})
