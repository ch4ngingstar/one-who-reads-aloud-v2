'use client'
import { useState } from 'react'
import { audioUrl, deleteChapterAudio, resetChapter } from '@/lib/api'
import AudioPlayer from '@/components/AudioPlayer'
import type { Chapter, ChapterStatus } from '@/lib/types'

// ── Japanese Minimalist palette — monochrome + two accents ───────────────────
const STATUS_COLOR: Record<ChapterStatus, string> = {
  pending:   '#3F3F46',   // Ghost dim
  diarized:  '#71717A',   // Mid zinc
  tts_done:  '#71717A',   // Mid zinc
  assembled: '#71717A',   // Mid zinc
  complete:  '#D4D4D8',   // Chrome Silver
  error:     '#991B1B',   // Deep Crimson
}

const STATUS_LABEL: Record<ChapterStatus, string> = {
  pending:   'Pending',
  diarized:  'Diarized',
  tts_done:  'TTS',
  assembled: 'Built',
  complete:  'Done',
  error:     'Error',
}

const STATUS_TEXT: Record<ChapterStatus, string> = {
  pending:   'text-[#3F3F46]',
  diarized:  'text-[#71717A]',
  tts_done:  'text-[#71717A]',
  assembled: 'text-[#71717A]',
  complete:  'text-[#D4D4D8]',
  error:     'text-[#991B1B]',
}

// ── Inline SVG icons ──────────────────────────────────────────────────────────

// Rune of Sight — geometric eye, replaces the generic play triangle
function RuneOfSight({ size = 15 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeLinecap="square" aria-hidden>
      {/* Outer containment diamond */}
      <polygon points="10,0.5 19.5,10 10,19.5 0.5,10" strokeWidth="0.6" opacity="0.4" />
      {/* Angular eye lens — rhombus shape */}
      <path d="M2,10 L10,3.5 L18,10 L10,16.5 Z" strokeWidth="0.9" />
      {/* Horizontal axis */}
      <line x1="2" y1="10" x2="18" y2="10" strokeWidth="0.3" opacity="0.35" />
      {/* Diamond pupil — filled */}
      <polygon points="10,7 13,10 10,13 7,10" fill="currentColor" strokeWidth="0" />
      {/* Vertical slit — dark slash through pupil */}
      <line x1="10" y1="7.2" x2="10" y2="12.8" strokeWidth="0.5" stroke="rgba(0,0,0,0.55)" strokeLinecap="butt" />
    </svg>
  )
}

// Soul Core — diamond status indicator, filled or hollow
function SoulCore({
  color, filled = true, size = 8, pulse = false,
}: {
  color: string; filled?: boolean; size?: number; pulse?: boolean
}) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 10 10" aria-hidden
      fill={filled ? color : 'none'}
      stroke={color}
      strokeWidth={filled ? 0 : 1.2}
      className={pulse ? 'animate-pulse-slow' : ''}
    >
      <polygon points="5,0.5 9.5,5 5,9.5 0.5,5" />
    </svg>
  )
}

// Razor Slash — delete icon, two crossing strokes of differing weight
function RazorSlash({ size = 10 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeLinecap="square" aria-hidden>
      <line x1="1.5" y1="1.5" x2="10.5" y2="10.5" strokeWidth="2" />
      <line x1="10.5" y1="1" x2="0.5" y2="11" strokeWidth="0.9" opacity="0.6" />
      <line x1="7.5" y1="9" x2="11" y2="12.5" strokeWidth="1.5" opacity="0.3" />
    </svg>
  )
}

// Rebirth Rune — circular arrow, redo/retry action
function RebirthRune({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeLinecap="square" aria-hidden>
      <path d="M9.5,6 A3.5,3.5 0 1,1 6,2.5" strokeWidth="1.2" />
      <polyline points="4.5,1.2 6,2.8 4.5,4.4" strokeWidth="1" />
    </svg>
  )
}

function cleanError(msg: string) {
  return msg.replace(/^\[failed_stage:\w+\]\s*/, '')
}

function formatBytes(b: number) {
  return b >= 1_048_576 ? `${(b / 1_048_576).toFixed(1)} MB` : `${Math.round(b / 1024)} KB`
}

function formatDuration(s: number) {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.round(s % 60)
  if (h > 0) return `${h}h ${m}m ${sec}s`
  if (m > 0) return `${m}m ${sec}s`
  return `${sec}s`
}

type Filter = 'all' | ChapterStatus
interface TtsProg { done: number; total: number }
interface Props {
  chapters: Chapter[]
  activeChapterId?: number | null
  ttsProgress?:    Record<number, TtsProg>
  onDelete?:       (chapterId: number) => void
  onRedo?:         (chapterId: number) => void
}

// ── TTS progress bar ──────────────────────────────────────────────────────────
function TtsBar({ done, total }: TtsProg) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-ink-ghost font-medium uppercase tracking-wider text-[9px]">TTS</span>
        <span className="tech text-sm text-ink-secondary tabular-nums">{done}/{total} · {pct}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%`, background: '#71717A' }} />
      </div>
    </div>
  )
}

// ── Chapter card ──────────────────────────────────────────────────────────────
function ChapterCard({
  chapter, isActive, ttsProg, onDelete, onRedo,
}: {
  chapter: Chapter; isActive: boolean; ttsProg?: TtsProg
  onDelete?: () => void; onRedo?: () => void
}) {
  const [showPlayer, setShowPlayer] = useState(false)
  const [deleting,   setDeleting]   = useState(false)
  const [redoing,    setRedoing]    = useState(false)

  const isComplete  = chapter.status === 'complete'
  const hasAudio    = isComplete && chapter.output_audio_path != null
  const showLiveTts = isActive && ttsProg && ttsProg.total > 0
  const isDone      = ['tts_done', 'assembled', 'complete'].includes(chapter.status)

  async function handleDelete() {
    if (!confirm('Delete the audio file for this chapter?')) return
    setDeleting(true)
    try { await deleteChapterAudio(chapter.id); onDelete?.() }
    finally { setDeleting(false) }
  }

  async function handleRedo() {
    if (!confirm('Reset this chapter and re-run it from scratch?')) return
    setRedoing(true)
    try { await resetChapter(chapter.id); onRedo?.() }
    finally { setRedoing(false) }
  }

  const leftColor = isActive ? '#A0A0A8' : STATUS_COLOR[chapter.status]

  return (
    <div
      className={`glass-card p-5 flex flex-col gap-3 transition-all duration-200 ${
        isActive
          ? 'animate-cyber-aura'
          : isComplete
          ? 'animate-gold-glow hover:brightness-110'
          : 'hover:brightness-110'
      }`}
      style={{ borderLeft: `3px solid ${leftColor}` }}
    >
      {/* Index + status */}
      <div className="flex items-center justify-between gap-2">
        <span className="tech text-sm text-ink-ghost tabular-nums">
          {String(chapter.chapter_index + 1).padStart(3, '0')}
        </span>
        <div className="flex items-center gap-1.5">
          {/* Soul Core status diamond */}
          <SoulCore
            color={leftColor}
            filled={chapter.status !== 'pending'}
            size={7}
            pulse={isActive}
          />
          <span className={`text-[10px] font-medium uppercase tracking-wide ${
            isActive ? 'text-[#A0A0A8]' : STATUS_TEXT[chapter.status]
          }`}>
            {isActive ? 'Processing' : STATUS_LABEL[chapter.status]}
          </span>
        </div>
      </div>

      {/* Title */}
      <p className="text-xs text-white/90 leading-snug line-clamp-2 min-h-[2rem] font-medium">
        {chapter.title}
      </p>

      {/* TTS progress */}
      {showLiveTts ? (
        <TtsBar done={ttsProg!.done} total={ttsProg!.total} />
      ) : isDone && chapter.total_lines > 0 ? (
        <div className="flex items-center justify-between text-[10px]">
          <span className="text-ink-ghost uppercase tracking-wider text-[9px]">TTS</span>
          <span className="tech text-sm text-ink-muted tabular-nums">{chapter.total_lines} lines · 100%</span>
        </div>
      ) : chapter.total_lines > 0 ? (
        <span className="tech text-sm text-ink-ghost tabular-nums">{chapter.total_lines} lines</span>
      ) : null}

      {/* Processing time */}
      {chapter.processing_seconds != null && (
        <span className="tech text-sm text-ink-ghost tabular-nums">
          {formatDuration(chapter.processing_seconds)}
        </span>
      )}

      {/* Complete — file info + player */}
      {isComplete && (
        <div className="pt-3 space-y-2" style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
          <div className="flex items-center justify-between">
            {chapter.output_file_size_bytes != null ? (
              <span className="tech text-sm text-ink-muted tracking-wide">
                {formatBytes(chapter.output_file_size_bytes)}
              </span>
            ) : (
              <span className="text-[10px] text-ink-ghost italic">file deleted</span>
            )}
            {hasAudio ? (
              <button
                className="btn-danger py-1 px-1.5 disabled:opacity-40"
                onClick={handleDelete}
                disabled={deleting}
                aria-label="Delete audio"
                title="Delete from disk"
              >
                {deleting ? '…' : <RazorSlash size={9} />}
              </button>
            ) : (
              <button
                className="btn py-1 px-1.5 disabled:opacity-40"
                onClick={handleRedo}
                disabled={redoing}
                aria-label="Redo chapter"
                title="Reset and re-run chapter"
              >
                {redoing ? '…' : <RebirthRune size={11} />}
              </button>
            )}
          </div>

          {hasAudio && (
            !showPlayer ? (
              <button className="btn-gold w-full gap-2" onClick={() => setShowPlayer(true)}>
                <RuneOfSight size={13} />
                <span>Preview</span>
              </button>
            ) : (
              <AudioPlayer
                src={audioUrl(chapter.id)}
                onEnded={() => setShowPlayer(false)}
                onClose={() => setShowPlayer(false)}
              />
            )
          )}
        </div>
      )}

      {/* Error */}
      {chapter.status === 'error' && (
        <div
          className="flex items-center justify-between gap-2 pt-2 mt-0.5"
          style={{ borderTop: '1px solid rgba(140,30,30,0.15)' }}
        >
          {chapter.error_message && (
            <p
              className="text-[10px] text-[#9A2828] truncate flex-1"
              title={cleanError(chapter.error_message)}
            >
              {cleanError(chapter.error_message)}
            </p>
          )}
          <button
            className="btn py-1 px-1.5 flex-shrink-0 disabled:opacity-40"
            onClick={handleRedo}
            disabled={redoing}
            aria-label="Retry chapter"
            title="Reset and re-run chapter"
          >
            {redoing ? '…' : <RebirthRune size={11} />}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Grid with filter bar ──────────────────────────────────────────────────────
export default function ChapterGrid({ chapters, activeChapterId, ttsProgress = {}, onDelete, onRedo }: Props) {
  const [filter, setFilter] = useState<Filter>('all')

  const counts = chapters.reduce<Partial<Record<ChapterStatus, number>>>(
    (acc, ch) => ({ ...acc, [ch.status]: (acc[ch.status] ?? 0) + 1 }),
    {},
  )

  const displayed = filter === 'all' ? chapters : chapters.filter(ch => ch.status === filter)

  const filters: { key: Filter; label: string }[] = [
    { key: 'all',      label: `All ${chapters.length}`           },
    { key: 'pending',  label: `Pending ${counts.pending  ?? 0}`  },
    { key: 'diarized', label: `Diarized ${counts.diarized ?? 0}` },
    { key: 'tts_done', label: `TTS ${counts.tts_done     ?? 0}`  },
    { key: 'complete', label: `Done ${counts.complete    ?? 0}`  },
    { key: 'error',    label: `Error ${counts.error      ?? 0}`  },
  ]

  return (
    <div className="flex flex-col gap-4 h-full">
      <div className="flex items-center gap-1.5 flex-wrap flex-shrink-0">
        {filters.map(f => {
          const active = filter === f.key
          const isDone = f.key === 'complete'
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className={`btn-filter transition-all duration-150 ${
                active
                  ? isDone ? 'btn-filter-done-active' : 'btn-filter-active'
                  : ''
              }`}
            >
              {f.label}
            </button>
          )
        })}
      </div>

      {displayed.length === 0 ? (
        <div className="text-ink-ghost text-xs text-center py-12">
          No chapters match this filter.
        </div>
      ) : (
        <div
          className="grid gap-3 overflow-y-auto pr-1"
          style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))' }}
        >
          {displayed.map(ch => (
            <ChapterCard
              key={ch.id}
              chapter={ch}
              isActive={ch.id === activeChapterId}
              ttsProg={ttsProgress[ch.id]}
              onDelete={() => onDelete?.(ch.id)}
              onRedo={() => onRedo?.(ch.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
