'use client'
import { useEffect, useRef, useState } from 'react'
import type { SSEEvent } from '@/lib/types'

const EV_STYLE: Record<string, [string, string]> = {
  pipeline_start:   ['▶', 'text-ink-secondary'],
  pipeline_done:    ['✓', 'text-[#D4D4D8]'],
  pipeline_stopped: ['■', 'text-[#52525B]'],
  pipeline_error:   ['✗', 'text-[#991B1B]'],
  chapter_start:    ['→', 'text-ink-muted'],
  chapter_done:     ['✓', 'text-[#D4D4D8]'],
  chapter_error:    ['✗', 'text-[#991B1B]'],
  chapter_skip:     ['↷', 'text-ink-ghost'],
  stage_start:      ['·', 'text-ink-ghost'],
  stage_done:       ['·', 'text-ink-ghost'],
  tts_progress:     ['▬', 'text-[#71717A]'],
  vram_warning:     ['!', 'text-[#FBBF24]'],
}

const ERROR_TYPES = new Set(['pipeline_error', 'chapter_error', 'vram_warning'])

function formatEvent(e: SSEEvent): string {
  const t    = new Date(e.ts * 1000).toLocaleTimeString('en', { hour12: false })
  const type = e.type.padEnd(16)
  switch (e.type) {
    case 'pipeline_start':
      return `${t}  ${type}  project="${e.project}"  chapters=${e.total}`
    case 'pipeline_done':
      return `${t}  ${type}  done=${e.success}  err=${e.error}  skip=${e.skipped}  ${e.elapsed_s}s`
    case 'pipeline_stopped':
      return `${t}  ${type}  stopped after ${e.elapsed_s}s  done=${e.success}  err=${e.error}`
    case 'chapter_start':
      return `${t}  ${type}  [${String((e.chapter_index ?? 0) + 1).padStart(3,'0')}] "${String(e.title ?? '').slice(0,40)}"`
    case 'chapter_done':
      return `${t}  ${type}  id=${e.chapter_id}  ${e.elapsed_s}s  ${String(e.audio_path ?? '').split(/[\\/]/).pop()}`
    case 'chapter_error':
      return `${t}  ${type}  id=${e.chapter_id}  stage=${e.stage}  ${e.error}`
    case 'stage_start':
      return `${t}  ${type}  id=${e.chapter_id} >> ${e.stage}`
    case 'stage_done':
      return `${t}  ${type}  id=${e.chapter_id} << ${e.stage}  ${e.elapsed_s}s`
    case 'tts_progress': {
      const done = e.lines_done ?? 0, total = e.lines_total ?? 0
      const pct  = total > 0 ? Math.round((done / total) * 100) : 0
      const fill = Math.round(pct / 5)
      return `${t}  ${type}  id=${e.chapter_id}  ${'█'.repeat(fill)}${'░'.repeat(20 - fill)}  ${done}/${total} (${pct}%)`
    }
    case 'vram_warning':
      return `${t}  ${type}  VRAM ${e.used_mb}MB > ${e.threshold_mb}MB`
    default:
      return `${t}  ${type}  ${JSON.stringify(e).slice(0, 80)}`
  }
}

export default function LiveLog({ events, open, onToggle, onClear, embedded = false }: {
  events: SSEEvent[]; open: boolean; onToggle: () => void; onClear?: () => void
  /** Fill the parent instead of docking as a collapsible bottom drawer. */
  embedded?: boolean
}) {
  const scrollRef  = useRef<HTMLDivElement>(null)
  const [follow,     setFollow]     = useState(true)
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [copied,     setCopied]     = useState(false)

  const shown = errorsOnly ? events.filter(e => ERROR_TYPES.has(e.type)) : events

  // Autoscroll only while pinned to the bottom — scrolling up to read history
  // disengages follow; the Follow button re-pins.
  useEffect(() => {
    if ((open || embedded) && follow && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [shown.length, open, embedded, follow])

  function handleScroll() {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    setFollow(atBottom)
  }

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(shown.map(formatEvent).join('\n'))
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* clipboard unavailable (http / permissions) */ }
  }

  const last = events[events.length - 1]
  const [, lastColor] = last ? (EV_STYLE[last.type] ?? ['·', 'text-ink-ghost']) : ['', 'text-ink-ghost']

  return (
    <div
      className={embedded
        ? 'flex flex-col h-full'
        : `flex flex-col transition-all duration-200 ${open ? 'h-52' : 'h-10'}`}
      style={embedded ? undefined : { borderTop: '1px solid #232323', background: '#000000' }}
    >
      {/* Toggle bar + log actions (siblings — buttons must not nest) */}
      <div className="flex items-center h-10 flex-shrink-0">
        {embedded ? (
          <div className="flex items-center px-5 h-10 flex-1 min-w-0 text-xs text-ink-muted">
            <div className="flex items-center gap-3 min-w-0">
              <span className="label flex-shrink-0">Live Log</span>
              {events.length > 0 && (
                <span className="text-[10px] text-ink-ghost font-mono flex-shrink-0">{events.length} events</span>
              )}
            </div>
          </div>
        ) : (
          <button
            className="flex items-center justify-between px-5 h-10 flex-1 min-w-0 text-left
                       text-xs text-ink-muted hover:text-ink-secondary transition-colors duration-100"
            onClick={onToggle}
          >
            <div className="flex items-center gap-3 min-w-0">
              <span className="label flex-shrink-0">Live Log</span>
              {events.length > 0 && (
                <span className="text-[10px] text-ink-ghost font-mono flex-shrink-0">{events.length} events</span>
              )}
              {!open && last && (
                <span className={`text-[10px] font-mono truncate ${lastColor}`}>
                  {formatEvent(last).slice(8)}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 flex-shrink-0 ml-3">
              {open && <span className="text-white/12 animate-twinkle text-[8px] select-none" aria-hidden>✦</span>}
              <span className="text-[9px] text-ink-ghost">{open ? '▼' : '▲'}</span>
            </div>
          </button>
        )}

        {(open || embedded) && (
          <div className="flex items-center gap-1 px-3 flex-shrink-0">
            {!follow && (
              <button
                className="btn-filter !text-[11px] !py-0.5"
                onClick={() => setFollow(true)}
                title="Re-pin autoscroll to the newest events"
              >
                ↓ Follow
              </button>
            )}
            <button
              className={`btn-filter !text-[11px] !py-0.5 ${errorsOnly ? 'btn-filter-active' : ''}`}
              onClick={() => setErrorsOnly(v => !v)}
              aria-pressed={errorsOnly}
              title="Show only errors and warnings"
            >
              Errors
            </button>
            <button
              className="btn-filter !text-[11px] !py-0.5"
              onClick={handleCopy}
              disabled={shown.length === 0}
              title="Copy visible log lines"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
            {onClear && (
              <button
                className="btn-filter !text-[11px] !py-0.5"
                onClick={onClear}
                disabled={events.length === 0}
                title="Clear the log"
              >
                Clear
              </button>
            )}
          </div>
        )}
      </div>

      {/* Log content */}
      {(open || embedded) && (
        <div ref={scrollRef} onScroll={handleScroll} className="flex-1 overflow-y-auto log-scanlines">
          <div className="px-5 py-3 font-mono text-[11px] leading-[1.8]">
            {shown.length === 0 ? (
              <span className="text-ink-ghost">
                {errorsOnly && events.length > 0
                  ? 'No errors — the Nightmare holds.'
                  : 'Waiting for pipeline to start…'}
              </span>
            ) : (
              shown.map((e, i) => {
                const [icon, colorClass] = EV_STYLE[e.type] ?? ['·', 'text-ink-ghost']
                return (
                  <div key={i} className={`flex gap-2 min-w-0 ${colorClass}`}>
                    <span className="flex-shrink-0 w-3 text-center opacity-40 select-none">{icon}</span>
                    <span className="min-w-0 flex-1 whitespace-pre-wrap break-words">{formatEvent(e)}</span>
                  </div>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
