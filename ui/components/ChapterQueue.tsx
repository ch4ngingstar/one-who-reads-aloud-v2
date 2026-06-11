'use client'
import { memo, useEffect, useMemo, useRef, useState } from 'react'
import ConfirmButton from '@/components/ConfirmButton'
import { deleteChapterAudio, resetChapter } from '@/lib/api'
import { formatMB, parseChapterError } from '@/lib/format'
import type { Chapter, ChapterStatus } from '@/lib/types'
import type { Stage } from '@/hooks/usePipelineState'

type Filter = 'all' | 'pending' | 'complete' | 'failed'
const RENDER_CHUNK = 120

const STATUS_SUB: Record<ChapterStatus, string> = {
  pending: 'Pending', diarized: 'Diarized', tts_done: 'Synthesized',
  assembled: 'Assembled', complete: 'Complete', error: 'Failed',
}

const STAGE_LABEL: Record<Stage, string> = {
  diarize: 'Weaving the dream', synthesize: 'Synthesizing', assemble: 'Binding echoes',
}

const MARK_CLASS: Record<ChapterStatus, string> = {
  pending:   'text-spell-g3',
  diarized:  'text-spell-g5',
  tts_done:  'text-spell-g6',
  assembled: 'text-spell-g6',
  complete:  'text-spell-g6',
  error:     'text-blood-text [text-shadow:0_0_10px_rgba(140,39,49,0.6)]',
}

interface RowProps {
  chapter: Chapter
  isRunning: boolean
  activeStage: Stage | null
  ttsProg?: { done: number; total: number }
  selected: boolean
  isPlaying: boolean
  playerPlaying: boolean
  onSelect: (id: number) => void
  onPlay: (id: number) => void
  onChanged: () => void
}

const QueueRow = memo(function QueueRow({
  chapter, isRunning, activeStage, ttsProg, selected, isPlaying, playerPlaying,
  onSelect, onPlay, onChanged,
}: RowProps) {
  const num = String(chapter.chapter_index + 1)
  const failed = chapter.status === 'error'
  const complete = chapter.status === 'complete'

  if (isRunning) {
    const pct = ttsProg && ttsProg.total > 0 ? Math.round((ttsProg.done / ttsProg.total) * 100) : 0
    const synth = activeStage === 'synthesize'
    return (
      <div className="cv-auto rounded border border-spell-g6 bg-gradient-to-b from-[#1c1c1c] to-spell-g1
                      p-[15px] flex items-center gap-[15px] animate-glowpulse"
           data-chapter-row={chapter.id}>
        <span className="font-mono text-xs w-[42px] text-right flex-none text-ink-hot [text-shadow:0_0_10px_rgba(255,255,255,0.5)]">
          {num}
        </span>
        <span className="flex-none text-[11px] leading-none text-ink-hot animate-breathe [text-shadow:0_0_12px_rgba(255,255,255,0.7)]" aria-hidden>✦</span>
        <div className="flex-1 min-w-0">
          <div className="font-display text-[14.5px] tracking-[1.5px] text-ink-hot truncate [text-shadow:0_0_14px_rgba(255,255,255,0.3)]">
            {chapter.title}
          </div>
          <div className="flex items-center gap-2 mt-1 text-[10.5px] text-spell-g7">
            <span className="equalizer" aria-hidden><span /><span /><span /></span>
            <b className="text-ink-primary font-medium">
              {activeStage ? STAGE_LABEL[activeStage] : 'Processing'}
            </b>
            {synth && ttsProg && (
              <span>· line <b className="text-ink-primary">{ttsProg.done}∕{ttsProg.total}</b></span>
            )}
          </div>
          <div className={`progress-track mt-2 ${synth ? '' : 'progress-indeterminate'}`}>
            {synth && <i className="progress-fill" style={{ width: `${pct}%` }} />}
          </div>
        </div>
      </div>
    )
  }

  const err = failed ? parseChapterError(chapter.error_message) : null

  return (
    <div
      className={`cv-auto group rounded border px-[15px] py-2.5 flex items-center gap-[15px] cursor-pointer
                  transition-[transform,border-color] duration-150 hover:translate-x-[3px]
                  ${failed
                    ? 'bg-blood-bg border-[#33141a]'
                    : 'bg-spell-g1 border-[#1d1d1d] hover:border-spell-g4 hover:bg-[#151515]'}
                  ${selected ? '!border-spell-g6' : ''}`}
      data-chapter-row={chapter.id}
      onClick={() => onSelect(chapter.id)}
    >
      <span className="font-mono text-xs w-[42px] text-right flex-none text-spell-g6">{num}</span>
      <span className={`flex-none text-[11px] leading-none ${MARK_CLASS[chapter.status]}`} aria-hidden>✦</span>
      <div className="flex-1 min-w-0">
        <div className={`font-medium truncate ${
          failed ? 'text-blood-text' : complete ? 'text-ink-primary' : 'text-ink-secondary'
        }`}>
          {chapter.title}
        </div>
        <div className={`text-[10.5px] mt-px truncate ${failed ? 'text-[#8d4a51]' : 'text-spell-g6'}`}>
          {failed && err
            ? <>Failed at {err.stage ?? 'unknown stage'} — {err.detail}</>
            : complete
              ? <>Complete{chapter.output_file_size_bytes != null && (
                  <> · <span className="font-mono">{formatMB(chapter.output_file_size_bytes)}</span></>
                )}</>
              : STATUS_SUB[chapter.status]}
        </div>
      </div>

      {isPlaying && (
        <span className={`equalizer flex-none ${playerPlaying ? '' : 'equalizer--paused'}`} aria-hidden>
          <span /><span /><span />
        </span>
      )}

      <div className="hidden group-hover:flex gap-1.5 flex-none" onClick={e => e.stopPropagation()}>
        {complete && chapter.output_audio_path != null && (
          <button
            className="btn !p-0 w-[27px] h-[27px] text-[11px]"
            onClick={() => onPlay(chapter.id)}
            aria-label={`Play chapter ${num}`}
            title="Play in the Echo player"
          >▶</button>
        )}
        {(complete || failed) && (
          <ConfirmButton
            className="btn !p-0 w-[27px] h-[27px] text-[11px]"
            confirmClassName="btn !px-2 h-[27px] text-[9px]"
            confirmLabel={failed ? 'Retry?' : 'Redo?'}
            onConfirm={async () => { await resetChapter(chapter.id); onChanged() }}
            ariaLabel={failed ? `Retry chapter ${num}` : `Redo chapter ${num}`}
            title="Reset and re-run this chapter"
          >↻</ConfirmButton>
        )}
        {complete && (
          <ConfirmButton
            className="btn-danger !p-0 w-[27px] h-[27px] text-[11px]"
            confirmClassName="btn-danger !px-2 h-[27px] text-[9px]"
            confirmLabel="Delete?"
            onConfirm={async () => { await deleteChapterAudio(chapter.id); onChanged() }}
            ariaLabel={`Delete audio for chapter ${num}`}
            title="Delete audio from disk"
          >✕</ConfirmButton>
        )}
      </div>
    </div>
  )
})

interface Props {
  chapters: Chapter[]
  activeChapterId: number | null
  activeStage: Stage | null
  ttsProgress: Record<number, { done: number; total: number }>
  selectedId: number | null
  onSelect: (id: number) => void
  playingChapterId: number | null
  playerPlaying: boolean
  onPlay: (id: number) => void
  /** Fired after retry/redo/delete so the page refetches chapters. */
  onChanged: () => void
}

export default function ChapterQueue({
  chapters, activeChapterId, activeStage, ttsProgress, selectedId, onSelect,
  playingChapterId, playerPlaying, onPlay, onChanged,
}: Props) {
  const [filter, setFilter] = useState<Filter>('all')
  const [query,  setQuery]  = useState('')
  const [limit,  setLimit]  = useState(RENDER_CHUNK)
  const sentinelRef = useRef<HTMLDivElement>(null)

  const counts = useMemo(() => {
    let complete = 0, failed = 0
    for (const c of chapters) {
      if (c.status === 'complete') complete++
      else if (c.status === 'error') failed++
    }
    return { all: chapters.length, complete, failed, pending: chapters.length - complete - failed }
  }, [chapters])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return chapters.filter(c => {
      if (filter === 'complete' && c.status !== 'complete') return false
      if (filter === 'failed'   && c.status !== 'error')    return false
      if (filter === 'pending'  && (c.status === 'complete' || c.status === 'error')) return false
      if (q && !c.title.toLowerCase().includes(q) && !String(c.chapter_index + 1).includes(q)) return false
      return true
    })
  }, [chapters, filter, query])

  // Incremental render — grow the window as the sentinel scrolls into view.
  // jsdom has no IntersectionObserver: render everything there (tests).
  useEffect(() => { setLimit(RENDER_CHUNK) }, [filter, query])
  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') { setLimit(Number.MAX_SAFE_INTEGER); return }
    const el = sentinelRef.current
    if (!el) return
    const io = new IntersectionObserver(entries => {
      if (entries.some(e => e.isIntersecting)) setLimit(l => l + RENDER_CHUNK)
    })
    io.observe(el)
    return () => io.disconnect()
  }, [visible.length, limit])

  const FILTERS: { key: Filter; label: string; count: number; blood?: boolean }[] = [
    { key: 'all',      label: 'All',      count: counts.all },
    { key: 'pending',  label: 'Pending',  count: counts.pending },
    { key: 'complete', label: 'Complete', count: counts.complete },
    { key: 'failed',   label: 'Failed',   count: counts.failed, blood: true },
  ]

  return (
    <section className="deck-card flex-[1.8] flex flex-col min-w-0 overflow-hidden">
      <div className="flex items-center gap-1.5 px-[15px] py-[13px] border-b border-[#1a1a1a]">
        {FILTERS.map(f => (
          <button
            key={f.key}
            className={`btn-filter ${filter === f.key ? 'btn-filter-active' : ''} ${f.blood ? 'btn-filter--blood' : ''}`}
            onClick={() => setFilter(f.key)}
            aria-pressed={filter === f.key}
          >
            {f.label}<b className="font-mono font-normal opacity-70 ml-1">{f.count}</b>
          </button>
        ))}
        <input
          className="ml-auto w-[200px] !py-[7px] !px-[13px]"
          placeholder="Search chapters…"
          value={query}
          onChange={e => setQuery(e.target.value)}
        />
      </div>

      <div className="flex-1 overflow-y-auto p-[13px] flex flex-col gap-[7px]">
        {visible.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-3 text-spell-g5 select-none">
            <span className="text-2xl text-spell-g3" aria-hidden>✦</span>
            <span className="text-[11px] tracking-[0.18em] uppercase">
              {chapters.length === 0 ? 'No chapters — forge a project to begin' : 'Nothing matches'}
            </span>
          </div>
        ) : (
          <>
            {visible.slice(0, limit).map(ch => (
              <QueueRow
                key={ch.id}
                chapter={ch}
                isRunning={ch.id === activeChapterId}
                activeStage={activeStage}
                ttsProg={ttsProgress[ch.id]}
                selected={ch.id === selectedId}
                isPlaying={ch.id === playingChapterId}
                playerPlaying={playerPlaying}
                onSelect={onSelect}
                onPlay={onPlay}
                onChanged={onChanged}
              />
            ))}
            {visible.length > limit && <div ref={sentinelRef} className="h-2 flex-shrink-0" />}
          </>
        )}
      </div>
    </section>
  )
}
