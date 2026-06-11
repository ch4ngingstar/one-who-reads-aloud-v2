'use client'
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { useSSE } from '@/hooks/useSSE'
import type { SSEEvent, PipelineStatusResponse } from '@/lib/types'
import type { Toast, ToastTone } from '@/components/Toasts'

export type PipeStatus = PipelineStatusResponse['status']
export type Stage = 'diarize' | 'synthesize' | 'assemble'

export interface LiveLine { text: string; speaker: string; emotion: string }

export interface PipelineUIState {
  pipeStatus: PipeStatus
  events: SSEEvent[]
  activeChId: number | null
  activeStage: Stage | null
  ttsProgress: Record<number, { done: number; total: number }>
  liveLine: LiveLine | null
  startedAt: number | null
  connected: boolean
  vramMb: number | null
  toasts: Toast[]
  nextToastId: number
  /** Bumped on chapter/pipeline boundaries — the hook refetches snapshots. */
  refreshNonce: number
}

export type PipelineAction =
  | { kind: 'sse'; event: SSEEvent; now: number }
  | { kind: 'set-status'; status: PipeStatus }
  | { kind: 'connection'; connected: boolean }
  | { kind: 'toast'; tone: ToastTone; message: string }
  | { kind: 'dismiss-toast'; id: number }
  | { kind: 'clear-log' }

export const initialPipelineState: PipelineUIState = {
  pipeStatus: 'idle',
  events: [],
  activeChId: null,
  activeStage: null,
  ttsProgress: {},
  liveLine: null,
  startedAt: null,
  connected: true,
  vramMb: null,
  toasts: [],
  nextToastId: 1,
  refreshNonce: 0,
}

const MAX_EVENTS = 500
const MAX_TOASTS = 5

function withToast(s: PipelineUIState, tone: ToastTone, message: string): PipelineUIState {
  const toast: Toast = { id: s.nextToastId, tone, message }
  return {
    ...s,
    toasts: [...s.toasts.slice(-(MAX_TOASTS - 1)), toast],
    nextToastId: s.nextToastId + 1,
  }
}

function clearActive(s: PipelineUIState): PipelineUIState {
  return { ...s, activeChId: null, activeStage: null, liveLine: null }
}

export function pipelineReducer(s: PipelineUIState, a: PipelineAction): PipelineUIState {
  switch (a.kind) {
    case 'set-status':   return { ...s, pipeStatus: a.status }
    case 'connection':   return { ...s, connected: a.connected }
    case 'toast':        return withToast(s, a.tone, a.message)
    case 'dismiss-toast': return { ...s, toasts: s.toasts.filter(t => t.id !== a.id) }
    case 'clear-log':    return { ...s, events: [] }
    case 'sse': {
      const e = a.event
      let next: PipelineUIState = { ...s, events: [...s.events.slice(-(MAX_EVENTS - 1)), e] }
      switch (e.type) {
        case 'pipeline_start':
          return { ...next, startedAt: a.now, ttsProgress: {}, liveLine: null }
        case 'chapter_start':
          return { ...next, activeChId: e.chapter_id ?? null, activeStage: null, liveLine: null }
        case 'stage_start':
          if (typeof e.stage !== 'string') return next
          return {
            ...next,
            activeStage: e.stage as Stage,
            liveLine: e.stage === 'synthesize' ? next.liveLine : null,
          }
        case 'tts_progress': {
          if (e.chapter_id == null) return next
          const liveLine = typeof e.text === 'string'
            ? { text: e.text, speaker: String(e.speaker ?? ''), emotion: String(e.emotion ?? '') }
            : next.liveLine
          return {
            ...next,
            activeChId: e.chapter_id,
            liveLine,
            ttsProgress: {
              ...next.ttsProgress,
              [e.chapter_id]: { done: e.lines_done ?? 0, total: e.lines_total ?? 0 },
            },
          }
        }
        case 'chapter_done':
          return { ...clearActive(next), refreshNonce: next.refreshNonce + 1 }
        case 'chapter_error':
          next = withToast(next, 'crimson',
            `Chapter ${e.chapter_id ?? '?'} has fallen — ${String(e.error ?? 'unknown error').slice(0, 120)}`)
          return { ...clearActive(next), refreshNonce: next.refreshNonce + 1 }
        case 'pipeline_done':
          next = withToast(next, 'chrome',
            `Congratulations, Sleeper. ${e.success ?? 0} chapters transcribed.`)
          return { ...clearActive(next), pipeStatus: 'complete', refreshNonce: next.refreshNonce + 1 }
        case 'pipeline_stopped':
          return { ...clearActive(next), pipeStatus: 'stopped', refreshNonce: next.refreshNonce + 1 }
        case 'pipeline_error':
          next = withToast(next, 'crimson',
            `The Nightmare collapsed: ${String(e.error ?? 'unknown error').slice(0, 120)}`)
          return { ...next, pipeStatus: 'error' }
        case 'vram_warning':
          next = withToast(next, 'warn',
            `The Spell warns: VRAM ${e.used_mb} MB exceeds the ${e.threshold_mb} MB barrier.`)
          return { ...next, vramMb: typeof e.used_mb === 'number' ? e.used_mb : next.vramMb }
        default:
          return next
      }
    }
  }
}

/**
 * State of record for the pipeline UI. Pure reducer over SSE events;
 * `onRefresh` fires after chapter/pipeline boundaries so the page can
 * refetch chapter + progress snapshots (the self-heal sync model).
 */
export function usePipelineState(onRefresh: () => void) {
  const [state, dispatch] = useReducer(pipelineReducer, initialPipelineState)
  const onRefreshRef = useRef(onRefresh)
  onRefreshRef.current = onRefresh

  useEffect(() => {
    if (state.refreshNonce > 0) onRefreshRef.current()
  }, [state.refreshNonce])

  const handleSSE = useCallback(
    (e: SSEEvent) => dispatch({ kind: 'sse', event: e, now: Date.now() }), [])
  const handleConnection = useCallback(
    (connected: boolean) => dispatch({ kind: 'connection', connected }), [])

  useSSE(state.pipeStatus === 'running' || state.pipeStatus === 'paused', handleSSE, handleConnection)

  return { state, dispatch }
}
