'use client'
import type { Chapter, ChapterStatus, Progress } from '@/lib/types'

type Stage = 'diarize' | 'synthesize' | 'assemble'

const STAGE_LABEL: Record<Stage, string> = {
  diarize:    'Diarizing',
  synthesize: 'Synthesizing',
  assemble:   'Assembling',
}

const STRIP_COLOR: Record<ChapterStatus, string> = {
  pending:   '#27272A',
  diarized:  '#52525B',
  tts_done:  '#71717A',
  assembled: '#71717A',
  complete:  '#D4D4D8',
  error:     '#991B1B',
}

export function formatEta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  if (h > 0) return `~${h}h ${m}m left`
  if (m > 0) return `~${m}m left`
  return '~1m left'
}

/** Clickable minimap — one sliver per chapter, click jumps the grid there. */
function ChapterStrip({ chapters, activeId, onSelect }: {
  chapters: Chapter[]; activeId: number | null; onSelect?: (id: number) => void
}) {
  if (!chapters.length) return null
  return (
    <div className="flex gap-[1px] mt-2 overflow-hidden" style={{ height: '5px' }}>
      {chapters.map(ch => (
        <button
          key={ch.id}
          className="flex-1 min-w-[1px] transition-colors duration-500 hover:!opacity-100 cursor-pointer p-0 border-0"
          style={{
            backgroundColor: STRIP_COLOR[ch.status],
            opacity: ch.id === activeId ? 1 : 0.55,
          }}
          title={`${ch.chapter_index + 1}. ${ch.title} (${ch.status})`}
          aria-label={`Jump to chapter ${ch.chapter_index + 1}: ${ch.title}`}
          onClick={() => onSelect?.(ch.id)}
          tabIndex={-1}
        />
      ))}
    </div>
  )
}

interface Props {
  progress:    Progress
  chapters:    Chapter[]
  activeChId:  number | null
  activeStage: Stage | null
  isRunning:   boolean
  eta:         string
  throughput:  string | null
  onSelectChapter?: (id: number) => void
}

export default function StatsBar({
  progress, chapters, activeChId, activeStage, isRunning, eta, throughput, onSelectChapter,
}: Props) {
  const activeChapter = activeChId != null ? chapters.find(c => c.id === activeChId) : undefined

  return (
    <div className="flex-shrink-0 px-6 py-4" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
      <div className="flex items-baseline gap-6 flex-wrap">
        {[
          { label: 'Total',   value: progress.total,   color: 'text-ink-secondary' },
          { label: 'Pending', value: progress.pending, color: 'text-[#52525B]'     },
          { label: 'Active',  value: progress.diarized + progress.tts_done + progress.assembled, color: 'text-[#A0A0A8]' },
          { label: 'Done',    value: progress.complete, color: 'text-[#D4D4D8]'    },
          { label: 'Error',   value: progress.error,    color: 'text-[#991B1B]'    },
        ].map(({ label, value, color }) => (
          <div key={label} className="flex items-baseline gap-1.5">
            <span className={`tech text-2xl tabular-nums leading-none ${color}`}>{value}</span>
            <span className="text-[9px] text-ink-ghost uppercase tracking-[0.14em]">{label}</span>
          </div>
        ))}

        <div className="ml-auto flex items-center gap-4">
          {eta && (
            <span className="tech text-sm text-ink-ghost tabular-nums tracking-wide">{eta}</span>
          )}
          {throughput && (
            <span className="tech text-sm text-ink-muted tabular-nums tracking-wide">
              {throughput}
              <span className="text-ink-ghost text-[11px]"> ch/hr</span>
            </span>
          )}
          <span className="tech text-base tabular-nums text-ink-secondary">
            {progress.pct_complete}%
          </span>
        </div>
      </div>

      {/* Live "now processing" line */}
      {isRunning && activeChapter && (
        <div className="flex items-center gap-2 mt-2 text-[10px] font-mono text-ink-muted animate-fade-in">
          <span className="status-dot bg-dot-running animate-pulse-slow flex-shrink-0" />
          <span className="text-ink-ghost uppercase tracking-[0.14em] text-[9px]">
            {activeStage ? STAGE_LABEL[activeStage] : 'Processing'}
          </span>
          <span className="truncate max-w-[400px] text-ink-secondary">
            {String(activeChapter.chapter_index + 1).padStart(3, '0')} · {activeChapter.title}
          </span>
        </div>
      )}

      <div className="weaver-thread animate-thread-pulse mt-3 mb-1" />
      <ChapterStrip chapters={chapters} activeId={activeChId} onSelect={onSelectChapter} />
    </div>
  )
}
