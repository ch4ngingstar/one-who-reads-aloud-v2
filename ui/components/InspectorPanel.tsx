'use client'
import { useEffect, useState } from 'react'
import ConfirmButton from '@/components/ConfirmButton'
import VoiceMapper from '@/components/VoiceMapper'
import LiveLog from '@/components/LiveLog'
import { deleteChapterAudio, getLines, resetChapter } from '@/lib/api'
import { formatMB, parseChapterError } from '@/lib/format'
import type { Chapter, Line, SSEEvent, Voice } from '@/lib/types'
import type { LiveLine, Stage } from '@/hooks/usePipelineState'

export type SideTab = 'inspector' | 'voices' | 'forge' | 'log'

const TABS: { key: SideTab; label: string }[] = [
  { key: 'inspector', label: 'Inspector' },
  { key: 'voices',    label: 'Voices' },
  { key: 'forge',     label: 'Forge' },
  { key: 'log',       label: 'Log' },
]

const STAGE_LABEL: Record<Stage, string> = {
  diarize: 'Weaving the dream', synthesize: 'Synthesizing', assemble: 'Binding echoes',
}

interface Props {
  tab: SideTab
  onTabChange: (t: SideTab) => void
  running: boolean
  activeChapter: Chapter | null
  activeStage: Stage | null
  liveLine: LiveLine | null
  ttsProg: { done: number; total: number } | null
  selectedChapter: Chapter | null
  onPlay: (id: number) => void
  /** Fired after retry/redo/delete so the page refetches chapters. */
  onChanged: () => void
  voices: Voice[]
  onVoicesUpdate: () => void
  /** Page-provided Forge content (project picker + ProjectSetup). */
  forge: React.ReactNode
  events: SSEEvent[]
  onClearLog: () => void
}

function LiveStage({ chapter, stage, liveLine, ttsProg }: {
  chapter: Chapter; stage: Stage | null; liveLine: LiveLine | null
  ttsProg: { done: number; total: number } | null
}) {
  const synth = stage === 'synthesize'
  const pct = synth && ttsProg && ttsProg.total > 0
    ? Math.round((ttsProg.done / ttsProg.total) * 100) : null

  return (
    <div className="stage-glow relative px-5 pt-[22px] pb-6 border-b border-[#1a1a1a]">
      <span className="absolute top-2.5 right-3.5 text-[38px] leading-none text-[#1c1c1c] select-none" aria-hidden>✦</span>
      <div className="font-display text-[17px] tracking-[2px] leading-[1.45] text-ink-hot [text-shadow:0_0_18px_rgba(255,255,255,0.25)]">
        Ch. {chapter.chapter_index + 1}<br />{chapter.title}
      </div>
      <div className="flex items-center gap-2 my-[14px] text-[9px] tracking-[3px] uppercase text-ink-hot animate-breathe">
        <span className="equalizer" aria-hidden><span /><span /><span /></span>
        {stage ? STAGE_LABEL[stage] : 'Processing'}
        {synth && ttsProg && <> — line {ttsProg.done} of {ttsProg.total}</>}
      </div>
      {synth && liveLine ? (
        <>
          <div className="text-[15px] leading-[1.7] italic text-[#e0e0e0] min-h-[52px] pl-[15px] border-l-2 border-spell-g4">
            &ldquo;{liveLine.text}&rdquo;
          </div>
          <div className="text-[9px] tracking-[2.4px] uppercase text-spell-g5 mt-[11px] pl-[15px]">
            speaker <b className="text-ink-primary font-medium normal-case">{liveLine.speaker}</b>
            {' '}· emotion <b className="text-ink-primary font-medium normal-case">{liveLine.emotion}</b>
          </div>
        </>
      ) : (
        <div className="text-[11px] text-spell-g6 italic min-h-[52px] pl-[15px] border-l-2 border-spell-g3">
          {stage === 'diarize'
            ? 'The Spell reads each line, assigning voices and emotions…'
            : 'Working…'}
        </div>
      )}
      <div className={`progress-track mt-[18px] ${pct == null ? 'progress-indeterminate' : ''}`}>
        {pct != null && <i className="progress-fill" style={{ width: `${pct}%` }} />}
      </div>
      {pct != null && ttsProg && (
        <div className="font-mono text-[10px] text-spell-g6 mt-[7px] flex justify-between">
          <span>{pct}%</span>
          <span>line {ttsProg.done}∕{ttsProg.total}</span>
        </div>
      )}
    </div>
  )
}

const EMOTION_COLOR: Record<string, string> = {
  neutral: 'text-spell-g5', happy: 'text-emerald-500', angry: 'text-red-400',
  sad: 'text-blue-400', afraid: 'text-purple-400', disgust: 'text-yellow-600',
  melancholic: 'text-indigo-400', surprised: 'text-amber-400', calm: 'text-teal-500',
}

function LineRow({ line }: { line: Line }) {
  const emoColor = EMOTION_COLOR[line.emotion] ?? 'text-spell-g5'
  return (
    <div className="py-[9px] border-b border-[#181818] last:border-0">
      <div className="flex items-center gap-2 mb-[5px]">
        <span className="text-[9px] tracking-[1.8px] uppercase font-medium text-ink-secondary truncate max-w-[120px]">
          {line.speaker}
        </span>
        <span className={`text-[9px] tracking-[1.5px] uppercase ${emoColor} ml-auto shrink-0`}>
          {line.emotion}
        </span>
      </div>
      <p className="text-[11px] leading-[1.6] text-spell-g5 line-clamp-2">{line.text}</p>
    </div>
  )
}

function ChapterDetail({ chapter, onPlay, onChanged }: {
  chapter: Chapter; onPlay: (id: number) => void; onChanged: () => void
}) {
  const failed = chapter.status === 'error'
  const complete = chapter.status === 'complete'
  const hasDiarization = chapter.status !== 'pending'
  const err = failed ? parseChapterError(chapter.error_message) : null
  const num = String(chapter.chapter_index + 1)
  const [lines, setLines] = useState<Line[]>([])

  useEffect(() => {
    if (!hasDiarization) { setLines([]); return }
    getLines(chapter.id).then(r => setLines(r.lines)).catch(() => setLines([]))
  }, [chapter.id, chapter.status, hasDiarization])

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="p-5 flex-shrink-0">
        <div className="font-display text-[15px] tracking-[1.5px] text-ink-primary leading-snug">
          Ch. {num} — {chapter.title}
        </div>
        <div className="text-[10px] tracking-[0.18em] uppercase text-spell-g5 mt-1">
          {chapter.status}
        </div>

        <div className="flex mt-4 pb-1.5">
          <div className="flex-1">
            <b className="font-mono text-base text-ink-primary font-medium block">{chapter.total_lines}</b>
            <span className="text-[9px] tracking-[1.8px] uppercase text-spell-g5">lines</span>
          </div>
          <div className="flex-1 border-l border-spell-g2 pl-[18px]">
            <b className="font-mono text-base text-ink-primary font-medium block">{chapter.total_chunks}</b>
            <span className="text-[9px] tracking-[1.8px] uppercase text-spell-g5">chunks</span>
          </div>
          <div className="flex-1 border-l border-spell-g2 pl-[18px]">
            <b className="font-mono text-base text-ink-primary font-medium block">
              {chapter.output_file_size_bytes != null ? formatMB(chapter.output_file_size_bytes) : '—'}
            </b>
            <span className="text-[9px] tracking-[1.8px] uppercase text-spell-g5">audio</span>
          </div>
        </div>

        {failed && err && (
          <div className="mt-4 p-3 rounded border border-[#33141a] bg-blood-bg">
            <div className="text-[9px] tracking-[2.2px] uppercase text-blood-text mb-1.5">
              Failed at {err.stage ?? 'unknown stage'}
            </div>
            <div className="text-[11px] leading-relaxed text-[#8d4a51] break-words">{err.detail}</div>
          </div>
        )}

        <div className="flex gap-2 mt-5">
          {complete && chapter.output_audio_path != null && (
            <button className="btn flex-1" onClick={() => onPlay(chapter.id)}>▶ Play</button>
          )}
          <ConfirmButton
            className="btn flex-1"
            confirmClassName="btn flex-1"
            confirmLabel={failed ? 'Retry?' : 'Redo?'}
            onConfirm={async () => { await resetChapter(chapter.id); onChanged() }}
            ariaLabel={failed ? `Retry chapter ${num}` : `Redo chapter ${num}`}
            title="Reset and re-run this chapter"
          >↻ {failed ? 'Retry' : 'Redo'}</ConfirmButton>
          {complete && (
            <ConfirmButton
              className="btn-danger flex-1"
              confirmClassName="btn-danger flex-1"
              confirmLabel="Delete?"
              onConfirm={async () => { await deleteChapterAudio(chapter.id); onChanged() }}
              ariaLabel={`Delete audio for chapter ${num}`}
              title="Delete audio from disk"
            >✕ Delete</ConfirmButton>
          )}
        </div>
      </div>

      {hasDiarization && lines.length > 0 && (
        <div className="flex-1 overflow-y-auto border-t border-[#1a1a1a] px-5 min-h-0">
          <div className="text-[9px] tracking-[2px] uppercase text-spell-g4 py-[10px]">
            Diarization · {lines.length} lines
          </div>
          {lines.map(l => <LineRow key={l.id} line={l} />)}
        </div>
      )}
    </div>
  )
}

export default function InspectorPanel({
  tab, onTabChange, running, activeChapter, activeStage, liveLine, ttsProg,
  selectedChapter, onPlay, onChanged, voices, onVoicesUpdate, forge,
  events, onClearLog,
}: Props) {
  return (
    <aside className="deck-card flex-1 min-w-[330px] max-w-[430px] flex flex-col min-h-0 overflow-hidden">
      <div className="flex border-b border-[#1a1a1a] flex-shrink-0">
        {TABS.map(t => (
          <button
            key={t.key}
            className={`flex-1 text-center py-3 font-display text-[10px] tracking-[2.4px] uppercase border-b
                        transition-colors duration-100 ${
              tab === t.key
                ? 'text-ink-hot border-ink-hot [text-shadow:0_0_12px_rgba(255,255,255,0.4)]'
                : 'text-spell-g5 border-transparent hover:text-ink-secondary'
            }`}
            onClick={() => onTabChange(t.key)}
            aria-pressed={tab === t.key}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'inspector' && (
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          {running && activeChapter && (
            <LiveStage chapter={activeChapter} stage={activeStage} liveLine={liveLine} ttsProg={ttsProg} />
          )}
          {selectedChapter ? (
            <ChapterDetail chapter={selectedChapter} onPlay={onPlay} onChanged={onChanged} />
          ) : !running ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-spell-g5 select-none p-6 text-center">
              <span className="text-2xl text-spell-g3" aria-hidden>✦</span>
              <span className="text-[11px] tracking-[0.18em] uppercase">Select a chapter to inspect</span>
            </div>
          ) : null}
        </div>
      )}

      {tab === 'voices' && (
        <div className="flex-1 overflow-y-auto p-5">
          <VoiceMapper voices={voices} onUpdate={onVoicesUpdate} />
        </div>
      )}

      {tab === 'forge' && (
        <div className="flex-1 overflow-y-auto p-5">{forge}</div>
      )}

      {tab === 'log' && (
        <LiveLog events={events} open onToggle={() => {}} onClear={onClearLog} embedded />
      )}
    </aside>
  )
}
