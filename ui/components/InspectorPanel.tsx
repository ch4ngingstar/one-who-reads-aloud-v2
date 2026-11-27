'use client'
import { useEffect, useState } from 'react'
import ConfirmButton from '@/components/ConfirmButton'
import VoiceMapper from '@/components/VoiceMapper'
import LiveLog from '@/components/LiveLog'
import DiarizePanel from '@/components/DiarizePanel'
import SoundDesignPanel from '@/components/SoundDesignPanel'
import { audioUrl, confirmSpeaker, deleteChapterAudio, getLines, queueRecording, resetChapter } from '@/lib/api'
import { chapterName, chapterNumberLabel, formatMB, parseChapterError } from '@/lib/format'
import type { Chapter, Line, SSEEvent, Voice } from '@/lib/types'
import type { LiveLine, Stage } from '@/hooks/usePipelineState'

export type SideTab = 'inspector' | 'diarize' | 'voices' | 'sound' | 'forge' | 'log'

const TABS: { key: SideTab; label: string }[] = [
  { key: 'inspector', label: 'Inspector' },
  { key: 'diarize',   label: 'Diarize' },
  { key: 'voices',    label: 'Voices' },
  { key: 'sound',     label: 'Sound' },
  { key: 'forge',     label: 'Forge' },
  { key: 'log',       label: 'Log' },
]

const STAGE_LABEL: Record<Stage, string> = {
  diarize: 'Weaving the dream', synthesize: 'Synthesizing', assemble: 'Binding echoes',
}

interface Props {
  renderChapter?: (chapter: Chapter, renderer: string) => Promise<void>
  renderers?: {name: string; path: string}[]
  currentRenderer?: string
  tab: SideTab
  onTabChange: (t: SideTab) => void
  running: boolean
  activeChapter: Chapter | null
  activeStage: Stage | null
  liveLine: LiveLine | null
  ttsProg: { done: number; total: number; etaSeconds?: number } | null
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
  ttsProg: { done: number; total: number; etaSeconds?: number } | null
}) {
  const synth = stage === 'synthesize'
  const pct = synth && ttsProg && ttsProg.total > 0
    ? Math.round((ttsProg.done / ttsProg.total) * 100) : null

  return (
    <div className="stage-glow relative px-5 pt-[22px] pb-6 border-b border-[#1a1a1a]">
      <span className="absolute top-2.5 right-3.5 text-[38px] leading-none text-[#1c1c1c] select-none" aria-hidden>✦</span>
      <div className="font-display text-[17px] tracking-[2px] leading-[1.45] text-ink-hot [text-shadow:0_0_18px_rgba(255,255,255,0.25)]">
        Ch. {chapterNumberLabel(chapter)}<br />{chapterName(chapter)}
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
          {ttsProg.etaSeconds != null && ttsProg.etaSeconds > 0 &&
            <span>Speech · about {Math.ceil(ttsProg.etaSeconds / 60)} min left</span>}
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

const ATTRIBUTION_LABEL = {
  explicit: 'Explicit attribution in the book',
  inferred: 'Inferred from the scene without a cited cue',
  exchange: 'Inferred during an exchange review',
  vocative: 'Inferred from a form of address',
  fallback: 'Assigned using a default for this cue type',
} as Record<string, string>

const LABELLER_HOW: Record<string, string> = {
  agree: 'Both independent votes agreed',
  pair: 'The votes split; settled by a closer look',
  think: 'The votes split; settled by a closer look',
  review: 'The labeller was unsure',
  kind: 'Decided from the kind of line',
}

/** Plain-language account of how a line's speaker was chosen. */
function attributionText(attribution: NonNullable<Line['attribution']>): string {
  if (ATTRIBUTION_LABEL[attribution.method]) return ATTRIBUTION_LABEL[attribution.method]
  const [, how = ''] = attribution.method.split(':')
  const votes = (attribution.votes ?? []).filter(Boolean).map(v => v === '@other' ? 'someone unnamed' : v)
  return `Local labeller: ${LABELLER_HOW[how] ?? 'automatic'}${votes.length ? ` (votes: ${votes.join(', ')})` : ''}`
}

function LineRow({ line, chapterId, active, onListen, onRetake, onConfirm, voices, cueText }: {
  line: Line; chapterId: number; active: boolean; onListen: () => void; onRetake: (speaker?: string, reading?: string) => Promise<void>; voices: Voice[]
  onConfirm: () => Promise<void>
  cueText: Map<number, string>
}) {
  const emoColor = EMOTION_COLOR[line.emotion] ?? 'text-spell-g5'
  const take = line.performance
  const [recast, setRecast] = useState(false)
  const [draft, setDraft] = useState<string | null>(null)
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
      {line.review_reason && <p className="text-xs text-amber-400">{line.review_reason}{' '}
        <button className="underline text-ink-secondary" onClick={onConfirm}
          aria-label={`${line.speaker} is right for line ${line.line_index + 1}`}>✓ {line.speaker} is right</button>
      </p>}
      {Boolean(line.speaker_locked) && <p className="text-xs">Speaker chosen by you</p>}
      {line.attribution && line.attribution.method !== 'manual' && !line.attribution.method.endsWith(':chapter') && (
        <details className="text-xs">
          <summary>Speaker attribution</summary>
          <p>{attributionText(line.attribution)}</p>
          {line.attribution.voice_as && <p>No cast voice yet: voiced by {line.attribution.voice_as}.</p>}
          {line.attribution.cue_indices.map(index => (
            <p key={index}>Cue {index + 1} · {cueText.get(index)}</p>
          ))}
        </details>
      )}
      {line.spoken_override && <p className="text-xs">Reading: {line.spoken_override}</p>}
      {line.spoken_text && <details className="text-xs"><summary>Exact TTS input</summary><p>{line.spoken_text}</p></details>}
      {draft === null ? <button className="underline text-xs" onClick={() => setDraft(line.spoken_override ?? line.text)}>Edit spoken text</button> :
        <div className="space-y-1"><textarea className="input" aria-label="Spoken text" value={draft} maxLength={10000} onChange={e => setDraft(e.target.value)} />
          <div className="flex gap-3 text-xs">
            <button disabled={!draft.trim()} onClick={async () => { await onRetake(undefined, draft); setDraft(null) }}>Save reading</button>
            <button onClick={async () => { await onRetake(undefined, ''); setDraft(null) }}>Use book text</button>
            <button onClick={() => setDraft(null)}>Cancel</button>
          </div></div>}
      {take && (
        <div className="mt-1 text-[11px] text-ink-secondary">
          <div className="flex flex-wrap items-center gap-3">
            <button onClick={onListen} className="underline">Listen at {Math.floor(take.start_ms / 60000)}:{String(Math.floor(take.start_ms / 1000) % 60).padStart(2, '0')}</button>
            <span>{take.renderer}</span>
            <ConfirmButton className="underline" confirmClassName="underline" confirmLabel="Queue retake?"
              ariaLabel={`Retake line ${line.line_index + 1}`} onConfirm={() => onRetake()}>Retake</ConfirmButton>
          </div>
          {take.audit.review && <p className="mt-1">{take.audit.reason || 'Check this reading.'} Heard “{take.audit.heard || 'No words detected'}”</p>}
          {take.fallback && <p>Used the fallback voice.</p>}
          {active && <audio controls autoPlay preload="metadata" className="mt-2 w-full" aria-label="Selected line"
            src={`${audioUrl(chapterId)}#t=${take.start_ms / 1000},${take.end_ms / 1000}`}
            onTimeUpdate={e => { if (e.currentTarget.currentTime >= take.end_ms / 1000) e.currentTarget.pause() }} />}
        </div>
      )}
      {voices.length > 0 && <div className="mt-1 text-[11px] text-ink-secondary">
        {recast ? <select aria-label="Choose new voice" className="input" defaultValue=""
          onChange={async e => { if (e.target.value) { await onRetake(e.target.value); setRecast(false) } }}>
          <option value="">Choose a voice…</option>
          {voices.map(v => <option key={v.id} value={v.speaker}>{v.speaker}</option>)}
        </select> : <button className="underline" onClick={() => setRecast(true)}>Change speaker</button>}
      </div>}
    </div>
  )
}

function ChapterDetail({ chapter, onPlay, onChanged, voices, renderChapter, renderers, currentRenderer }: {
  chapter: Chapter; onPlay: (id: number) => void; onChanged: () => void; voices: Voice[]
} & Pick<Props, 'renderChapter' | 'renderers' | 'currentRenderer'>) {
  const failed = chapter.status === 'error'
  const complete = chapter.status === 'complete'
  const hasDiarization = chapter.status !== 'pending'
  const err = failed ? parseChapterError(chapter.error_message) : null
  const num = chapterNumberLabel(chapter)
  const [lines, setLines] = useState<Line[]>([])
  const cueText = new Map(lines.map(line => [line.line_index, line.text]))
  const [listening, setListening] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [renderer, setRenderer] = useState('')
  const [starting, setStarting] = useState(false)
  const selectedRenderer = renderer || currentRenderer || renderers?.[0]?.path || ''
  async function renderSelected() {
    if (!renderChapter) return
    setStarting(true)
    try { await renderChapter(chapter, selectedRenderer); setMessage('') }
    catch (e) { setMessage(e instanceof Error ? e.message : 'Could not start recording.') }
    finally { setStarting(false) }
  }
  async function queue(line?: number, speaker?: string, reading?: string) {
    try {
      await queueRecording(chapter.id, line, speaker, reading)
      const updated = await getLines(chapter.id)
      setLines(updated.lines)
      if (reading !== undefined) setLines(rows => rows.map(row => row.line_index === line ? { ...row, spoken_override: reading.trim() || null } : row))
      if (speaker) setLines(rows => rows.map(row => row.line_index === line ? { ...row, speaker } : row))
      setMessage('Retake queued. Choose Render this chapter when ready.')
      onChanged()
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Could not queue the recording.') }
  }
  async function confirm(line: number) {
    try {
      await confirmSpeaker(chapter.id, line)
      setLines(rows => rows.map(row => row.line_index === line ? { ...row, review_reason: null, speaker_locked: 1 } : row))
    } catch (e) { setMessage(e instanceof Error ? e.message : 'Could not confirm the speaker.') }
  }
  const [reviewOnly, setReviewOnly] = useState(false)
  const flagged = lines.filter(l => l.review_reason).length
  const shown = reviewOnly ? lines.filter(l => l.review_reason) : lines
  useEffect(() => { setListening(null); setMessage(''); setReviewOnly(false) }, [chapter.id])

  useEffect(() => {
    if (!hasDiarization) { setLines([]); return }
    let current = true
    getLines(chapter.id).then(r => { if (current) setLines(r.lines) }).catch(() => { if (current) setLines([]) })
    return () => { current = false }
  }, [chapter.id, chapter.status, hasDiarization])

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div className="p-5 flex-shrink-0">
        <div className="font-display text-[15px] tracking-[1.5px] text-ink-primary leading-snug">
          Ch. {num} — {chapterName(chapter)}
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

        <div className="mt-5 space-y-2">
          {message && <p role="status" className="text-xs text-ink-secondary">{message}</p>}
          {renderChapter && <div className="space-y-1.5">
            {Boolean(renderers?.length) && <select className="input" aria-label="Chapter speech renderer"
              value={selectedRenderer} onChange={e => setRenderer(e.target.value)}>
              {!renderers?.some(r => r.path === selectedRenderer) && <option value={selectedRenderer}>Current renderer</option>}
              {renderers?.map(r => <option key={r.path} value={r.path}>{r.name}</option>)}
            </select>}
            <button className="btn w-full" disabled={starting || !selectedRenderer} onClick={renderSelected}>
              {starting ? 'Starting…' : 'Render this chapter'}
            </button>
          </div>}
          {chapter.output_audio_path != null && (
            <button className="btn-primary w-full" onClick={() => onPlay(chapter.id)}>▶ Play chapter</button>
          )}
          <div className="flex gap-2">
            <ConfirmButton
              className="btn flex-1"
              confirmClassName="btn flex-1"
              confirmLabel={failed ? 'Retry?' : 'Redo?'}
              onConfirm={async () => { await resetChapter(chapter.id, failed); onChanged() }}
              ariaLabel={failed ? `Retry chapter ${num}` : `Redo chapter ${num}`}
              title={failed ? 'Queue the failed stage and keep finished takes' : 'Reset and re-run this chapter'}
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
      </div>

      {hasDiarization && lines.length > 0 && (
        <div className="flex-1 overflow-y-auto border-t border-[#1a1a1a] px-5 min-h-0">
          <div className="flex items-center text-[9px] tracking-[2px] uppercase text-spell-g4 py-[10px]">
            <span>Diarization · {lines.length} lines</span>
            {(flagged > 0 || reviewOnly) && (
              <button className={`ml-auto underline ${reviewOnly ? 'text-amber-300' : 'text-amber-400'}`}
                aria-pressed={reviewOnly} onClick={() => setReviewOnly(v => !v)}>
                {reviewOnly ? 'Show all lines' : `Needs review · ${flagged}`}
              </button>
            )}
          </div>
          {reviewOnly && shown.length === 0 && (
            <p className="text-xs text-ink-secondary py-2">Every flagged line in this chapter has been checked.</p>
          )}
          {shown.map(l => <LineRow key={l.id} line={l} chapterId={chapter.id} cueText={cueText}
            active={listening === l.id} onListen={() => setListening(listening === l.id ? null : l.id)}
            voices={voices} onRetake={(speaker, reading) => queue(l.line_index, speaker, reading)}
            onConfirm={() => confirm(l.line_index)} />)}
        </div>
      )}
    </div>
  )
}

export default function InspectorPanel({
  tab, onTabChange, running, activeChapter, activeStage, liveLine, ttsProg, renderChapter, renderers, currentRenderer,
  selectedChapter, onPlay, onChanged, voices, onVoicesUpdate, forge,
  events, onClearLog,
}: Props) {
  return (
    <aside className="deck-card flex-1 min-w-[330px] max-w-[430px] flex flex-col min-h-0 overflow-hidden">
      <div className="flex border-b border-[#1a1a1a] flex-shrink-0">
        {TABS.map(t => (
          <button
            key={t.key}
            className={`flex-1 text-center py-3 font-display text-[9px] tracking-[1.6px] uppercase border-b
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
            <ChapterDetail key={selectedChapter.id} chapter={selectedChapter} onPlay={onPlay} onChanged={onChanged}
              voices={voices} renderChapter={renderChapter} renderers={renderers} currentRenderer={currentRenderer} />
          ) : !running ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-3 text-spell-g5 select-none p-6 text-center">
              <span className="text-2xl text-spell-g3" aria-hidden>✦</span>
              <span className="text-[11px] tracking-[0.18em] uppercase">Select a chapter to inspect</span>
            </div>
          ) : null}
        </div>
      )}

      {tab === 'diarize' && (
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          <DiarizePanel chapter={selectedChapter} onChanged={onChanged} />
        </div>
      )}

      {tab === 'voices' && (
        <div className="flex-1 overflow-y-auto p-5">
          <VoiceMapper voices={voices} onUpdate={onVoicesUpdate} />
        </div>
      )}

      {tab === 'sound' && (
        <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
          <SoundDesignPanel chapter={selectedChapter} onChanged={onChanged} />
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
