'use client'
import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import {
  getProject, getChapters, getVoices, listProjects,
  startPipeline, pausePipeline, resumePipeline, stopPipeline, getPipelineStatus,
} from '@/lib/api'
import { useSSE }        from '@/hooks/useSSE'
import ProjectSetup      from '@/components/ProjectSetup'
import VoiceMapper       from '@/components/VoiceMapper'
import ChapterGrid       from '@/components/ChapterGrid'
import LiveLog           from '@/components/LiveLog'
import type {
  Project, Progress, Chapter, Voice, SSEEvent, PipelineStatusResponse, ChapterStatus, GenOptions,
} from '@/lib/types'

const STORAGE_KEY = 'pipeline_cfg'
type  PipeStatus  = PipelineStatusResponse['status']
type  Stage       = 'diarize' | 'synthesize' | 'assemble'

interface SavedConfig {
  projectName: string; llmPath: string
  ttsDir: string; epubPath: string; speakers: string
  outputFormat?: string; vramCheck?: boolean
  fishDir?: string  // legacy key — migrated to ttsDir on load
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }: { status: PipeStatus }) {
  const map: Record<string, { color: string; pulse: boolean }> = {
    idle:     { color: 'text-ink-muted',      pulse: false },
    running:  { color: 'text-dot-running',    pulse: true  },
    paused:   { color: 'text-ink-secondary',  pulse: false },
    complete: { color: 'text-dot-complete',   pulse: false },
    stopped:  { color: 'text-ink-muted',      pulse: false },
    error:    { color: 'text-dot-error',      pulse: false },
  }
  const { color, pulse } = map[status] ?? map.idle
  return (
    <div className={`inline-flex items-center gap-1.5 text-[11px] font-medium ${color}`}>
      <span className={`status-dot bg-current ${pulse ? 'animate-pulse-slow' : ''}`} />
      <span className="uppercase tracking-wider">{status}</span>
    </div>
  )
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function ProgressBar({ pct, running }: { pct: number; running: boolean }) {
  return (
    <div className="h-[2px] w-full relative overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)' }}>
      <div
        className="absolute inset-y-0 left-0 transition-all duration-700"
        style={{
          width: `${Math.max(0, Math.min(100, pct))}%`,
          background: running ? '#D4D4D8' : '#27272A',
          opacity: running ? 0.7 : 1,
        }}
      />
      {running && pct > 0 && (
        <div
          className="absolute inset-y-0 w-20 pointer-events-none"
          style={{
            left: `${Math.max(-8, pct - 10)}%`,
            background: 'linear-gradient(to right, transparent, rgba(212,212,216,0.2), transparent)',
            transition: 'left 0.7s ease',
          }}
        />
      )}
    </div>
  )
}

// ── Chapter pipeline strip ────────────────────────────────────────────────────
const STRIP_COLOR: Record<ChapterStatus, string> = {
  pending:   '#27272A',
  diarized:  '#52525B',
  tts_done:  '#71717A',
  assembled: '#71717A',
  complete:  '#D4D4D8',
  error:     '#991B1B',
}

function ChapterStrip({ chapters, activeId }: { chapters: Chapter[]; activeId: number | null }) {
  if (!chapters.length) return null
  return (
    <div className="flex gap-[1px] mt-2 overflow-hidden" style={{ height: '2px' }} aria-hidden>
      {chapters.map(ch => (
        <div
          key={ch.id}
          className="flex-1 min-w-[1px] transition-colors duration-500"
          style={{
            backgroundColor: STRIP_COLOR[ch.status],
            opacity: ch.id === activeId ? 1 : 0.55,
          }}
          title={`${ch.chapter_index + 1}. ${ch.title} (${ch.status})`}
        />
      ))}
    </div>
  )
}

// ── ETA helper ────────────────────────────────────────────────────────────────
function formatEta(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return ''
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  if (h > 0) return `~${h}h ${m}m left`
  if (m > 0) return `~${m}m left`
  return '~1m left'
}

const STAGE_LABEL: Record<Stage, string> = {
  diarize:    'Diarizing',
  synthesize: 'Synthesizing',
  assemble:   'Assembling',
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const [project,    setProject]    = useState<Project | null>(null)
  const [progress,   setProgress]   = useState<Progress | null>(null)
  const [chapters,   setChapters]   = useState<Chapter[]>([])
  const [voices,     setVoices]     = useState<Voice[]>([])
  const [pipeStatus, setPipeStatus] = useState<PipeStatus>('idle')
  const [events,     setEvents]     = useState<SSEEvent[]>([])
  const [activeChId,  setActiveChId]  = useState<number | null>(null)
  const [activeStage, setActiveStage] = useState<Stage | null>(null)
  const [ttsProgress, setTtsProgress] = useState<Record<number, { done: number; total: number }>>({})
  const [logOpen,     setLogOpen]     = useState(false)
  const logUserClosed = useRef(false)
  const [sideTab,   setSideTab]   = useState<'setup' | 'voices'>('setup')
  const [startError,setStartError] = useState<string | null>(null)
  const [llmPath,   setLlmPath]   = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/models/qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf')
  const [ttsDir,    setTtsDir]    = useState('C:/Users/alityan/OneDrive/Desktop/shaodw salve/index-tts/checkpoints')
  const [projects,  setProjects]  = useState<(Project & { progress: Progress })[]>([])
  const [epubPath,  setEpubPath]  = useState('')
  const [speakers,  setSpeakers]  = useState('Sunny, Nephis, Cassie, Effie, Kai')
  const [outputFormat, setOutputFormat] = useState('mp3')
  const [vramCheck,    setVramCheck]    = useState(true)
  const [startedAt, setStartedAt] = useState<number | null>(null)

  const fetchChapters = useCallback(async (p: Project) => {
    try { const { chapters: chs } = await getChapters(p.id); setChapters(chs) } catch { /* silent */ }
  }, [])

  const refreshChapters = useCallback(async () => {
    if (project) return fetchChapters(project)
  }, [project, fetchChapters])

  const refreshProgress = useCallback(async () => {
    if (!project) return
    try { const { progress: p } = await getProject(project.name); setProgress(p) } catch { /* silent */ }
  }, [project])

  const refreshVoices = useCallback(async () => {
    try { const { voices: vs } = await getVoices(); setVoices(vs) } catch { /* silent */ }
  }, [])

  const saveCfg = useCallback((patch: Partial<SavedConfig>) => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      const cfg = raw ? JSON.parse(raw) : {}
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cfg, ...patch }))
    } catch { /* quota/parse — non-fatal */ }
  }, [])

  const selectProject = useCallback(async (name: string) => {
    if (!name) return
    try {
      const { project: p, progress: pr } = await getProject(name)
      setProject(p); setProgress(pr); setSideTab('voices'); fetchChapters(p)
      getPipelineStatus().then(s => setPipeStatus(s.status)).catch(() => {})
      saveCfg({ projectName: name })
    } catch { /* */ }
  }, [fetchChapters, saveCfg])

  useEffect(() => {
    refreshVoices()
    listProjects().then(({ projects: ps }) => setProjects(ps)).catch(() => {})
    // Always sync with the backend — the pipeline may still be running from a
    // previous browser session.
    getPipelineStatus().then(s => setPipeStatus(s.status)).catch(() => {})
    let cfg: Partial<SavedConfig> = {}
    try { const r = localStorage.getItem(STORAGE_KEY); if (r) cfg = JSON.parse(r) } catch { /* */ }
    if (cfg.llmPath && !cfg.llmPath.includes('7b'))  setLlmPath(cfg.llmPath)
    // Migrate legacy fishDir, but ignore stale Fish Speech paths — TTS is now
    // IndexTTS2 (index-tts/checkpoints). A saved fish-speech dir would fail.
    const savedTtsDir = cfg.ttsDir || cfg.fishDir
    if (savedTtsDir && !/fish[-_ ]?speech/i.test(savedTtsDir)) setTtsDir(savedTtsDir)
    if (cfg.epubPath) setEpubPath(cfg.epubPath)
    if (cfg.speakers) setSpeakers(cfg.speakers)
    if (cfg.outputFormat) setOutputFormat(cfg.outputFormat)
    if (cfg.vramCheck != null) setVramCheck(cfg.vramCheck)
    if (cfg.projectName) {
      getProject(cfg.projectName)
        .then(({ project: p, progress: pr }) => {
          setProject(p); setProgress(pr); setSideTab('voices'); fetchChapters(p)
        })
        .catch(() => {})
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (pipeStatus !== 'running') return
    const id = setInterval(() => {
      refreshChapters(); refreshProgress()
      // Catch missed SSE terminal events (e.g. laptop slept through them).
      getPipelineStatus().then(s => {
        if (s.status !== 'running') setPipeStatus(s.status)
      }).catch(() => {})
    }, 3000)
    return () => clearInterval(id)
  }, [pipeStatus, refreshChapters, refreshProgress])

  const handleSSE = useCallback((e: SSEEvent) => {
    setEvents(prev => [...prev.slice(-499), e])
    if (e.type === 'pipeline_start') {
      logUserClosed.current = false
      setLogOpen(true)
      setStartedAt(Date.now()); setTtsProgress({})
    }
    // Respect an explicit close — don't force the log back open on every event.
    if (!logOpen && !logUserClosed.current
        && e.type !== 'pipeline_done' && e.type !== 'pipeline_stopped') setLogOpen(true)
    if (e.type === 'chapter_start')    { setActiveChId(e.chapter_id ?? null); setActiveStage(null) }
    if (e.type === 'stage_start' && typeof e.stage === 'string') {
      setActiveStage(e.stage as Stage)
    }
    if (e.type === 'tts_progress' && e.chapter_id != null) {
      setActiveChId(e.chapter_id)
      setTtsProgress(prev => ({
        ...prev, [e.chapter_id as number]: { done: e.lines_done ?? 0, total: e.lines_total ?? 0 },
      }))
    }
    if (e.type === 'chapter_done')     { setActiveChId(null); setActiveStage(null); refreshChapters(); refreshProgress() }
    if (e.type === 'chapter_error')    { setActiveChId(null); setActiveStage(null); refreshChapters() }
    if (e.type === 'pipeline_done')    { setPipeStatus('complete'); setActiveChId(null); setActiveStage(null); refreshChapters(); refreshProgress() }
    if (e.type === 'pipeline_stopped') { setPipeStatus('stopped');  setActiveChId(null); setActiveStage(null); refreshChapters(); refreshProgress() }
    if (e.type === 'pipeline_error')   setPipeStatus('error')
  }, [logOpen, refreshChapters, refreshProgress])

  useSSE(pipeStatus === 'running' || pipeStatus === 'paused', handleSSE)

  function buildStartParams() {
    const speakerList = speakers.split(',').map(s => s.trim()).filter(Boolean)
    return {
      llm_model_path: llmPath, tts_model_dir: ttsDir,
      speakers: speakerList, output_format: outputFormat,
      vram_check_enabled: vramCheck,
    }
  }

  async function handleStart() {
    if (!project) return; setStartError(null)
    try {
      await startPipeline({ project_name: project.name, ...buildStartParams() })
      setPipeStatus('running'); logUserClosed.current = false; setLogOpen(true)
    } catch (err) { setStartError(err instanceof Error ? err.message : 'Failed to start') }
  }

  async function handlePause()  { try { await pausePipeline();  setPipeStatus('paused')  } catch { /* */ } }
  async function handleResume() { try { await resumePipeline(); setPipeStatus('running') } catch { /* */ } }
  async function handleStop()   { try { await stopPipeline();   setPipeStatus('stopped') } catch { /* */ } }

  function handleProjectCreated(
    p: Project, prog: Progress, llm: string, tts: string, spkList: string[], opts: GenOptions,
  ) {
    setProject(p); setProgress(prog); setLlmPath(llm); setTtsDir(tts)
    setSpeakers(spkList.join(', ')); setOutputFormat(opts.outputFormat)
    setVramCheck(opts.vramCheck); setSideTab('voices')
    saveCfg({
      projectName: p.name, llmPath: llm, ttsDir: tts, epubPath,
      speakers: spkList.join(', '),
      outputFormat: opts.outputFormat, vramCheck: opts.vramCheck,
    })
    fetchChapters(p)
    startPipeline({
      project_name: p.name, llm_model_path: llm, tts_model_dir: tts, speakers: spkList,
      chapter_range: opts.chapterRange, output_format: opts.outputFormat,
      vram_check_enabled: opts.vramCheck,
    })
      .then(() => { setPipeStatus('running'); logUserClosed.current = false; setLogOpen(true) })
      .catch(err => {
        const msg = err instanceof Error ? err.message : 'Failed to start'
        if (msg.toLowerCase().includes('already running')) setPipeStatus('running')
        else setStartError(msg)
      })
  }

  const throughput = startedAt && progress && progress.complete > 0
    ? (progress.complete / ((Date.now() - startedAt) / 3_600_000)).toFixed(1)
    : null

  // ETA from measured per-chapter processing time × chapters left.
  const eta = useMemo(() => {
    if (!progress || pipeStatus !== 'running') return ''
    const timed = chapters.filter(c => c.processing_seconds != null && c.status === 'complete')
    if (!timed.length) return ''
    const avg = timed.reduce((s, c) => s + (c.processing_seconds ?? 0), 0) / timed.length
    const remaining = progress.total - progress.complete - progress.error
    return formatEta(avg * remaining)
  }, [chapters, progress, pipeStatus])

  const activeChapter = activeChId != null ? chapters.find(c => c.id === activeChId) : undefined

  const canStart  = project && llmPath && ttsDir && ['idle','stopped','complete','error'].includes(pipeStatus)
  const isRunning = pipeStatus === 'running'

  return (
    <div className="flex flex-col h-screen overflow-hidden">

      {/* ══════════════════════════════════════════════════════ HEADER ═══ */}
      <header className="flex-shrink-0 glass-panel">
        <div className="flex items-center justify-between px-6 h-14">

          {/* Brand */}
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex items-center gap-2.5 flex-shrink-0 select-none">
              <span className="text-white/20 text-lg leading-none animate-twinkle" aria-hidden>◈</span>
              <div>
                <div className="text-[11px] font-semibold text-white tracking-[0.1em] uppercase leading-none">
                  Audiobook Pipeline
                </div>
                <div className="text-[9px] text-white/18 tracking-[0.2em] uppercase leading-none mt-0.5 select-none">
                  Shadow Slave
                </div>
              </div>
            </div>

            {project && (
              <div className="flex items-center gap-2 min-w-0 ml-1">
                <span className="text-white/10 select-none">·</span>
                <span
                  className="text-[11px] text-ink-muted font-mono truncate max-w-[260px]"
                  title={project.source_epub}
                >
                  {project.source_epub.split(/[\\/]/).pop()}
                </span>
              </div>
            )}
          </div>

          {/* Controls */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <StatusBadge status={pipeStatus} />

            {progress && (
              <span className="tech text-sm text-ink-muted tabular-nums tracking-wide">
                {progress.complete}
                <span className="text-ink-ghost">/</span>
                {progress.total}
              </span>
            )}

            {throughput && (
              <span className="tech text-sm text-ink-ghost tracking-wide">{throughput} ch/hr</span>
            )}

            {(canStart || isRunning || pipeStatus === 'paused') && (
              <div className="w-px h-4" style={{ background: 'rgba(255,255,255,0.08)' }} />
            )}

            {canStart && (
              <button className="btn-primary" onClick={handleStart}>
                {pipeStatus === 'idle' ? '▶ Start' : '↺ Retry'}
              </button>
            )}
            {isRunning && (
              <>
                <button className="btn" onClick={handlePause}>⏸ Pause</button>
                <button className="btn-danger" onClick={handleStop}>■ Stop</button>
              </>
            )}
            {pipeStatus === 'paused' && (
              <>
                <button className="btn-primary" onClick={handleResume}>▶ Resume</button>
                <button className="btn-danger" onClick={handleStop}>■ Stop</button>
              </>
            )}
          </div>
        </div>

        <ProgressBar pct={progress?.pct_complete ?? 0} running={isRunning} />
      </header>

      {/* ══════════════════════════════════════════════════ ERROR BANNER ═══ */}
      {startError && (
        <div className="flex-shrink-0 px-6 py-2.5 flex items-center justify-between gap-4 animate-slide-up"
             style={{ background: 'rgba(153,27,27,0.06)', borderBottom: '1px solid rgba(153,27,27,0.25)' }}>
          <span className="text-xs text-[#991B1B] truncate">{startError}</span>
          <button
            className="text-[#991B1B]/60 hover:text-[#991B1B] transition-colors flex-shrink-0 text-sm"
            onClick={() => setStartError(null)}
            aria-label="Dismiss"
          >✕</button>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════ BODY ══════ */}
      <div className="flex flex-1 min-h-0">

        {/* ─── Sidebar ──────────────────────────────────────────────── */}
        <aside
          className="w-72 flex-shrink-0 flex flex-col overflow-hidden"
          style={{ background: '#0A0A0F', borderRight: '1px solid rgba(255,255,255,0.04)' }}
        >
          {/* Shadow Slave brand strip */}
          <div
            className="flex items-center justify-center gap-2.5 px-4 py-3 select-none"
            style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
          >
            <span className="text-white/15 animate-twinkle text-[9px]" aria-hidden>✦</span>
            <span className="text-[9px] text-white/20 tracking-[0.25em] uppercase font-medium">
              Shadow Slave
            </span>
            <span className="text-white/15 animate-twinkle text-[9px] [animation-delay:1.5s]" aria-hidden>✦</span>
          </div>

          {/* Setup / Voices tabs */}
          <div className="flex flex-shrink-0" style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
            {(['setup', 'voices'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setSideTab(tab)}
                className={`flex-1 py-3 text-[11px] font-medium uppercase tracking-[0.1em]
                            transition-all duration-150 border-b-2 -mb-px ${
                  sideTab === tab
                    ? 'text-white/65 border-white/18'
                    : 'text-ink-ghost border-transparent hover:text-ink-secondary'
                }`}
              >
                {tab === 'setup' ? 'Setup' : 'Voices'}
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto p-5">
            {sideTab === 'setup' ? (
              <div className="space-y-5">
                {projects.length > 0 && (
                  <div>
                    <label className="block text-[11px] font-medium uppercase tracking-[0.1em] text-ink-ghost mb-1.5">
                      Open existing project
                    </label>
                    <select
                      value={project?.name ?? ''}
                      onChange={(e) => selectProject(e.target.value)}
                      className="w-full bg-black/30 border border-white/10 rounded-md px-3 py-2
                                 text-sm text-ink-secondary focus:border-white/25 focus:outline-none"
                    >
                      <option value="" disabled>Select a project…</option>
                      {projects.map((p) => (
                        <option key={p.id} value={p.name}>
                          {p.name} — {p.progress.complete}/{p.progress.total} done
                        </option>
                      ))}
                    </select>
                    <p className="mt-1.5 text-[11px] text-ink-ghost">
                      Or create a new one from an EPUB below.
                    </p>
                  </div>
                )}
                <ProjectSetup
                  initialEpub={epubPath} initialLlm={llmPath}
                  initialTtsDir={ttsDir} initialSpeakers={speakers}
                  onCreated={handleProjectCreated}
                />
              </div>
            ) : (
              <VoiceMapper voices={voices} onUpdate={refreshVoices} />
            )}
          </div>
        </aside>

        {/* ─── Main ─────────────────────────────────────────────────── */}
        <main className="flex-1 flex flex-col min-w-0 overflow-hidden">

          {/* Stats bar */}
          {progress && (
            <div
              className="flex-shrink-0 px-6 py-4"
              style={{ borderBottom: '1px solid rgba(255,255,255,0.05)' }}
            >
              <div className="flex items-baseline gap-6 flex-wrap">
                {[
                  { label: 'Total',   value: progress.total,                       color: 'text-ink-secondary' },
                  { label: 'Pending', value: progress.pending,                      color: 'text-[#52525B]'     },
                  { label: 'Active',  value: progress.diarized + progress.tts_done + progress.assembled, color: 'text-[#A0A0A8]' },
                  { label: 'Done',    value: progress.complete,                     color: 'text-[#D4D4D8]'     },
                  { label: 'Error',   value: progress.error,                        color: 'text-[#991B1B]'     },
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

              {/* Live "now playing" line */}
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
              <ChapterStrip chapters={chapters} activeId={activeChId} />
            </div>
          )}

          {/* Chapter grid / empty state */}
          <div className="flex-1 overflow-hidden p-6">
            {chapters.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center gap-6">
                {project ? (
                  <div className="flex items-center gap-2 text-[10px] text-ink-ghost font-mono">
                    <span className="text-white/15 animate-twinkle">✦</span>
                    <span>Loading chapters…</span>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-5 max-w-[280px] text-center animate-slide-up">

                    {/* Floating logo cluster */}
                    <div className="relative w-20 h-20 flex items-center justify-center">
                      <span className="text-white/15 animate-twinkle text-xs absolute top-0 right-0 select-none" aria-hidden>✦</span>
                      <span className="text-white/12 animate-twinkle text-[9px] absolute bottom-1 left-0 select-none [animation-delay:2s]" aria-hidden>✧</span>
                      <span className="text-white/10 animate-twinkle text-[8px] absolute top-2 left-2 select-none [animation-delay:1.2s]" aria-hidden>✦</span>
                      <span className="text-white/10 text-6xl select-none animate-drift" aria-hidden>◈</span>
                    </div>

                    <div className="space-y-1.5">
                      <div className="text-[9px] text-white/18 tracking-[0.3em] uppercase select-none">
                        ✦ Shadow Slave ✦
                      </div>
                      <p className="text-sm font-medium text-ink-secondary">Ready to begin</p>
                      <p className="text-xs text-ink-muted leading-relaxed">
                        Configure your EPUB, LLM model, and IndexTTS2 model directory in the Setup panel.
                      </p>
                    </div>

                    <div className="flex items-center gap-2 text-[9px] font-mono tracking-widest text-ink-ghost/60">
                      {['EPUB', 'DIARIZE', 'TTS', 'ASSEMBLE'].map((s, i, a) => (
                        <span key={s} className="flex items-center gap-2">
                          <span className={i === 0 ? 'text-white/28' : ''}>{s}</span>
                          {i < a.length - 1 && <span style={{ color: 'rgba(255,255,255,0.1)' }}>→</span>}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <ChapterGrid
                chapters={chapters}
                activeChapterId={activeChId}
                activeStage={activeStage}
                ttsProgress={ttsProgress}
                onDelete={refreshChapters}
                onRedo={refreshChapters}
              />
            )}
          </div>
        </main>
      </div>

      {/* ══════════════════════════════════════════════════════ LIVE LOG ═══ */}
      <LiveLog
        events={events}
        open={logOpen}
        onToggle={() => setLogOpen(v => { if (v) logUserClosed.current = true; return !v })}
      />
    </div>
  )
}
