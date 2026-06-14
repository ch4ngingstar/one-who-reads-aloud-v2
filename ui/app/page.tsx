'use client'
import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  getProject, getChapters, getVoices, listProjects,
  startPipeline, pausePipeline, resumePipeline, stopPipeline, getPipelineStatus,
} from '@/lib/api'
import { usePipelineState } from '@/hooks/usePipelineState'
import { formatEta } from '@/lib/format'
import CommandStrip   from '@/components/CommandStrip'
import ChapterQueue   from '@/components/ChapterQueue'
import InspectorPanel, { type SideTab } from '@/components/InspectorPanel'
import ProjectSetup   from '@/components/ProjectSetup'
import PlayerBar      from '@/components/PlayerBar'
import Toasts         from '@/components/Toasts'
import type { Project, Progress, Chapter, Voice, GenOptions } from '@/lib/types'

const STORAGE_KEY = 'pipeline_cfg'

interface SavedConfig {
  projectName: string; llmPath: string
  ttsDir: string; epubPath: string; speakers: string
  outputFormat?: string; vramCheck?: boolean
  fishDir?: string  // legacy key — migrated to ttsDir on load
}

export default function CommandDeck() {
  const [project,  setProject]  = useState<Project | null>(null)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [voices,   setVoices]   = useState<Voice[]>([])
  const [projects, setProjects] = useState<(Project & { progress: Progress })[]>([])

  const [sideTab,    setSideTab]    = useState<SideTab>('forge')
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const [llmPath,      setLlmPath]      = useState('')
  const [ttsDir,       setTtsDir]       = useState('')
  const [epubPath,     setEpubPath]     = useState('')
  const [speakers,     setSpeakers]     = useState('Sunny, Nephis, Cassie, Effie, Kai')
  const [outputFormat, setOutputFormat] = useState('mp3')
  const [vramCheck,    setVramCheck]    = useState(true)

  const [playingChId,   setPlayingChId]   = useState<number | null>(null)
  const [playerPlaying, setPlayerPlaying] = useState(false)

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

  const onRefresh = useCallback(() => { refreshChapters(); refreshProgress() }, [refreshChapters, refreshProgress])
  const { state, dispatch } = usePipelineState(onRefresh)
  const { pipeStatus } = state

  const toast = useCallback((tone: 'warn' | 'crimson' | 'chrome', message: string) => {
    dispatch({ kind: 'toast', tone, message })
  }, [dispatch])

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
      setProject(p); setProgress(pr); setSideTab('voices'); setSelectedId(null); fetchChapters(p)
      getPipelineStatus().then(s => {
        dispatch({ kind: 'set-status', status: s.status })
        if ((s.status === 'running' || s.status === 'paused') && s.last_event) {
          dispatch({ kind: 'sse', event: s.last_event, now: Date.now() })
        }
      }).catch(() => {})
      saveCfg({ projectName: name })
    } catch { /* */ }
  }, [fetchChapters, saveCfg, dispatch])

  useEffect(() => {
    refreshVoices()
    listProjects().then(({ projects: ps }) => setProjects(ps)).catch(() => {})
    // Always sync with the backend — the pipeline may still be running from a
    // previous browser session. Replay last_event so Inspector seeds activeChId/
    // activeStage without waiting for the next SSE frame.
    getPipelineStatus().then(s => {
      dispatch({ kind: 'set-status', status: s.status })
      if ((s.status === 'running' || s.status === 'paused') && s.last_event) {
        dispatch({ kind: 'sse', event: s.last_event, now: Date.now() })
      }
    }).catch(() => {})
    let cfg: Partial<SavedConfig> = {}
    try { const r = localStorage.getItem(STORAGE_KEY); if (r) cfg = JSON.parse(r) } catch { /* */ }
    if (cfg.llmPath) setLlmPath(cfg.llmPath)
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

  // Poll while running — catches missed SSE terminal events (e.g. sleep).
  useEffect(() => {
    if (pipeStatus !== 'running') return
    const id = setInterval(() => {
      refreshChapters(); refreshProgress()
      getPipelineStatus().then(s => {
        if (s.status !== 'running') dispatch({ kind: 'set-status', status: s.status })
      }).catch(() => {})
    }, 3000)
    return () => clearInterval(id)
  }, [pipeStatus, refreshChapters, refreshProgress, dispatch])

  function buildStartParams() {
    const speakerList = speakers.split(',').map(s => s.trim()).filter(Boolean)
    return {
      llm_model_path: llmPath, tts_model_dir: ttsDir,
      speakers: speakerList, output_format: outputFormat,
      vram_check_enabled: vramCheck,
    }
  }

  async function handleStart() {
    if (!project) return
    try {
      await startPipeline({ project_name: project.name, ...buildStartParams() })
      dispatch({ kind: 'set-status', status: 'running' })
      setSideTab('inspector')
    } catch (err) {
      toast('crimson', err instanceof Error ? err.message : 'Failed to start')
    }
  }

  async function handlePause()  { try { await pausePipeline();  dispatch({ kind: 'set-status', status: 'paused'  }) } catch (e) { toast('crimson', e instanceof Error ? e.message : 'Failed to pause')  } }
  async function handleResume() { try { await resumePipeline(); dispatch({ kind: 'set-status', status: 'running' }) } catch (e) { toast('crimson', e instanceof Error ? e.message : 'Failed to resume') } }
  async function handleStop()   { try { await stopPipeline();   dispatch({ kind: 'set-status', status: 'stopped' }) } catch (e) { toast('crimson', e instanceof Error ? e.message : 'Failed to stop')   } }

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
      .then(() => { dispatch({ kind: 'set-status', status: 'running' }); setSideTab('inspector') })
      .catch(err => {
        const msg = err instanceof Error ? err.message : 'Failed to start'
        if (msg.toLowerCase().includes('already running')) dispatch({ kind: 'set-status', status: 'running' })
        else toast('crimson', msg)
      })
  }

  // ETA from measured per-chapter processing time × chapters left.
  const eta = useMemo(() => {
    if (!progress || pipeStatus !== 'running') return ''
    const timed = chapters.filter(c => c.processing_seconds != null && c.status === 'complete')
    if (!timed.length) return ''
    const avg = timed.reduce((s, c) => s + (c.processing_seconds ?? 0), 0) / timed.length
    const remaining = progress.total - progress.complete - progress.error
    return formatEta(avg * remaining)
  }, [chapters, progress, pipeStatus])

  // Listenable chapters, in book order — the global player's queue.
  const playerQueue = useMemo(
    () => chapters
      .filter(c => c.status === 'complete' && c.output_audio_path != null)
      .sort((a, b) => a.chapter_index - b.chapter_index),
    [chapters],
  )

  const activeChapter   = useMemo(() => chapters.find(c => c.id === state.activeChId) ?? null, [chapters, state.activeChId])
  const selectedChapter = useMemo(() => chapters.find(c => c.id === selectedId) ?? null, [chapters, selectedId])
  const ttsProg = state.activeChId != null ? state.ttsProgress[state.activeChId] ?? null : null

  const canStart = Boolean(project && llmPath && ttsDir
    && ['idle', 'stopped', 'complete', 'error'].includes(pipeStatus))

  const forge = (
    <div className="space-y-5">
      {projects.length > 0 && (
        <div>
          <label className="label block mb-1.5">Open existing project</label>
          <select
            value={project?.name ?? ''}
            onChange={(e) => selectProject(e.target.value)}
            className="w-full px-3 py-2 text-sm"
          >
            <option value="" disabled>Select a project…</option>
            {projects.map((p) => (
              <option key={p.id} value={p.name}>
                {p.name} — {p.progress.complete}/{p.progress.total} done
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-[11px] text-ink-ghost">Or forge a new one from an EPUB below.</p>
        </div>
      )}
      <ProjectSetup
        initialEpub={epubPath} initialLlm={llmPath}
        initialTtsDir={ttsDir} initialSpeakers={speakers}
        onCreated={handleProjectCreated}
      />
    </div>
  )

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Toasts toasts={state.toasts} onDismiss={(id) => dispatch({ kind: 'dismiss-toast', id })} />

      <CommandStrip
        pipeStatus={pipeStatus}
        connected={state.connected}
        progress={progress}
        activeStage={state.activeStage}
        eta={eta}
        vramMb={state.vramMb}
        canStart={canStart}
        onStart={handleStart}
        onPause={handlePause}
        onResume={handleResume}
        onStop={handleStop}
      />

      <main className="flex flex-1 min-h-0 gap-[18px] px-6 py-[18px]">
        <ChapterQueue
          chapters={chapters}
          activeChapterId={state.activeChId}
          activeStage={state.activeStage}
          ttsProgress={state.ttsProgress}
          selectedId={selectedId}
          onSelect={(id) => { setSelectedId(id); setSideTab('inspector') }}
          playingChapterId={playingChId}
          playerPlaying={playerPlaying}
          onPlay={setPlayingChId}
          onChanged={onRefresh}
        />
        <InspectorPanel
          tab={sideTab}
          onTabChange={setSideTab}
          running={pipeStatus === 'running' || pipeStatus === 'paused'}
          activeChapter={activeChapter}
          activeStage={state.activeStage}
          liveLine={state.liveLine}
          ttsProg={ttsProg}
          selectedChapter={selectedChapter}
          onPlay={setPlayingChId}
          onChanged={onRefresh}
          voices={voices}
          onVoicesUpdate={refreshVoices}
          forge={forge}
          events={state.events}
          onClearLog={() => dispatch({ kind: 'clear-log' })}
        />
      </main>

      <PlayerBar
        queue={playerQueue}
        currentId={playingChId}
        onCurrentChange={setPlayingChId}
        onPlayingChange={setPlayerPlaying}
      />
    </div>
  )
}
