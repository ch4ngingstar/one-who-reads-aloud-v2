'use client'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { audioUrl } from '@/lib/api'
import type { Chapter } from '@/lib/types'

const SPEEDS    = [0.75, 1, 1.25, 1.5, 2] as const
const SKIP_SECS = 15
const PREFS_KEY = 'player_prefs'
const POS_KEY   = 'player_pos'

interface Prefs { speed: number; volume: number; muted: boolean }

function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    if (raw) {
      const p = JSON.parse(raw)
      return {
        speed:  SPEEDS.includes(p.speed) ? p.speed : 1,
        volume: typeof p.volume === 'number' ? Math.min(1, Math.max(0, p.volume)) : 1,
        muted:  Boolean(p.muted),
      }
    }
  } catch { /* corrupt prefs — fall through to defaults */ }
  return { speed: 1, volume: 1, muted: false }
}

function loadPos(): { chapterId: number; time: number } | null {
  try {
    const raw = localStorage.getItem(POS_KEY)
    if (raw) {
      const p = JSON.parse(raw)
      if (typeof p.chapterId === 'number' && typeof p.time === 'number') return p
    }
  } catch { /* ignore */ }
  return null
}

function fmtTime(s: number) {
  if (!isFinite(s) || isNaN(s)) return '--:--'
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

function isTypingTarget(el: EventTarget | null): boolean {
  if (!(el instanceof HTMLElement)) return false
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA'
      || el.tagName === 'SELECT' || el.isContentEditable
}

interface Props {
  /** Playable chapters (complete + audio on disk), sorted by chapter_index. */
  queue: Chapter[]
  currentId: number | null
  onCurrentChange: (id: number | null) => void
  onPlayingChange?: (playing: boolean) => void
}

/**
 * Persistent bottom player — the Echo chamber. One global <audio>, a queue of
 * finished chapters, auto-advance, keyboard transport, prefs in localStorage.
 */
export default function PlayerBar({ queue, currentId, onCurrentChange, onPlayingChange }: Props) {
  const ref = useRef<HTMLAudioElement>(null)
  const [playing,  setPlaying]  = useState(false)
  const [current,  setCurrent]  = useState(0)
  const [duration, setDuration] = useState(0)
  const [ready,    setReady]    = useState(false)
  const [prefs,    setPrefs]    = useState<Prefs>({ speed: 1, volume: 1, muted: false })
  const lastPosSave = useRef(0)

  const idx     = useMemo(() => queue.findIndex(c => c.id === currentId), [queue, currentId])
  const chapter = idx >= 0 ? queue[idx] : null

  useEffect(() => { setPrefs(loadPrefs()) }, [])

  const savePrefs = useCallback((patch: Partial<Prefs>) => {
    setPrefs(prev => {
      const next = { ...prev, ...patch }
      try { localStorage.setItem(PREFS_KEY, JSON.stringify(next)) } catch { /* quota */ }
      return next
    })
  }, [])

  // Apply prefs to the element whenever they (or the track) change.
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.playbackRate = prefs.speed
    el.volume       = prefs.volume
    el.muted        = prefs.muted
  }, [prefs, currentId])

  useEffect(() => { onPlayingChange?.(playing) }, [playing, onPlayingChange])

  // New track: reset state; position restore happens in onLoadedMetadata.
  useEffect(() => { setReady(false); setCurrent(0); setDuration(0) }, [currentId])

  const toggle = useCallback(() => {
    const el = ref.current
    if (!el || !ready) return
    if (el.paused) void el.play().catch(() => {})
    else el.pause()
  }, [ready])

  const skip = useCallback((s: number) => {
    const el = ref.current
    if (!el || !ready) return
    el.currentTime = Math.max(0, Math.min(el.duration || 0, el.currentTime + s))
  }, [ready])

  const goto = useCallback((targetIdx: number) => {
    const ch = queue[targetIdx]
    if (ch) onCurrentChange(ch.id)
  }, [queue, onCurrentChange])

  // Global transport keys — ignored while the user is typing in a field.
  useEffect(() => {
    if (currentId == null) return
    function onKey(e: KeyboardEvent) {
      if (isTypingTarget(e.target)) return
      if (e.code === 'Space')      { e.preventDefault(); toggle() }
      if (e.key  === 'ArrowLeft')  { e.preventDefault(); skip(-SKIP_SECS) }
      if (e.key  === 'ArrowRight') { e.preventDefault(); skip(SKIP_SECS) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [currentId, toggle, skip])

  if (!chapter) return null

  const pct = duration > 0 ? (current / duration) * 100 : 0

  return (
    <div
      className="flex-shrink-0 flex items-center gap-4 px-5 h-16 animate-slide-up"
      style={{ borderTop: '1px solid #27272A', background: 'rgba(0,0,0,0.97)' }}
    >
      <audio
        ref={ref}
        src={audioUrl(chapter.id)}
        autoPlay
        onTimeUpdate={() => {
          const el = ref.current
          if (!el) return
          setCurrent(el.currentTime)
          // Persist position at most every 2s so a reload resumes mid-chapter.
          const now = Date.now()
          if (now - lastPosSave.current > 2000) {
            lastPosSave.current = now
            try {
              localStorage.setItem(POS_KEY, JSON.stringify({ chapterId: chapter.id, time: el.currentTime }))
            } catch { /* quota */ }
          }
        }}
        onLoadedMetadata={() => {
          const el = ref.current
          if (!el) return
          setDuration(el.duration); setReady(true)
          const pos = loadPos()
          if (pos && pos.chapterId === chapter.id && pos.time < el.duration - 5) {
            el.currentTime = pos.time
          }
        }}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => {
          setPlaying(false)
          try { localStorage.removeItem(POS_KEY) } catch { /* */ }
          if (idx >= 0 && idx < queue.length - 1) goto(idx + 1)
          else onCurrentChange(null)
        }}
      />

      {/* Transport */}
      <div className="flex items-center gap-1.5 flex-shrink-0">
        <button className="btn text-[10px] px-2 py-1.5 font-mono" onClick={() => goto(idx - 1)}
                disabled={idx <= 0} title="Previous chapter" aria-label="Previous chapter">⟪</button>
        <button
          onClick={toggle}
          disabled={!ready}
          aria-label={playing ? 'Pause' : 'Play'}
          className={`flex items-center justify-center w-10 h-10 text-base transition-all duration-150 active:scale-95 ${
            ready
              ? 'bg-[#0A0A0A] border border-[#52525B] text-[#D4D4D8] hover:bg-[#121212] hover:border-[#A0A0A8]'
              : 'bg-white/5 border border-white/8 text-ink-ghost opacity-40 cursor-not-allowed'
          }`}
        >
          {playing ? '⏸' : '▶'}
        </button>
        <button className="btn text-[10px] px-2 py-1.5 font-mono" onClick={() => goto(idx + 1)}
                disabled={idx < 0 || idx >= queue.length - 1} title="Next chapter" aria-label="Next chapter">⟫</button>
      </div>

      {/* Track + seek */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className={`equalizer flex-shrink-0 ${playing ? '' : 'equalizer--paused'}`} aria-hidden>
            <span /><span /><span />
          </span>
          <span className="tech text-sm text-ink-ghost tabular-nums flex-shrink-0">
            {String(chapter.chapter_index + 1).padStart(3, '0')}
          </span>
          <span className="text-[11px] text-ink-secondary truncate">{chapter.title}</span>
          <span className="text-[9px] text-ink-ghost font-mono flex-shrink-0 ml-auto tabular-nums">
            {fmtTime(current)} <span className="opacity-50">/</span> {fmtTime(duration)}
          </span>
        </div>
        <div className="relative h-4 flex items-center">
          <div className="absolute inset-x-0 h-px" style={{ background: '#27272A' }} />
          <div className="absolute h-px" style={{ width: `${pct}%`, background: '#D4D4D8' }} />
          <input
            type="range"
            min={0} max={duration || 100} step={0.1}
            value={current}
            onChange={e => {
              const el = ref.current
              if (!el || !ready) return
              const v = Number(e.target.value)
              el.currentTime = v; setCurrent(v)
            }}
            disabled={!ready}
            className="w-full relative"
            aria-label="Seek"
          />
        </div>
      </div>

      {/* Speed */}
      <div className="hidden md:flex items-center gap-1 flex-shrink-0" role="group" aria-label="Playback speed">
        {SPEEDS.map(s => (
          <button
            key={s}
            onClick={() => savePrefs({ speed: s })}
            aria-pressed={prefs.speed === s}
            className={`text-[10px] font-mono px-2 py-1 transition-all ${
              prefs.speed === s
                ? 'bg-[#0A0A0A] text-[#D4D4D8] border border-[#52525B]'
                : 'text-ink-ghost border border-transparent hover:text-ink-muted'
            }`}
          >
            {s}×
          </button>
        ))}
      </div>

      {/* Volume + close */}
      <div className="flex items-center gap-2 flex-shrink-0">
        <button
          className="text-[11px] text-ink-secondary hover:text-ink-primary transition-colors w-4 text-center"
          onClick={() => savePrefs({ muted: !prefs.muted })}
          aria-label={prefs.muted ? 'Unmute' : 'Mute'}
        >
          {prefs.muted || prefs.volume === 0 ? '○' : prefs.volume < 0.5 ? '◔' : '◕'}
        </button>
        <input
          type="range"
          min={0} max={1} step={0.05}
          value={prefs.muted ? 0 : prefs.volume}
          onChange={e => {
            const v = Number(e.target.value)
            savePrefs({ volume: v, muted: v === 0 ? prefs.muted : false })
          }}
          className="range-vol w-16"
          aria-label={`Volume ${Math.round((prefs.muted ? 0 : prefs.volume) * 100)}%`}
        />
        <button className="btn text-[10px] px-2 py-1 ml-1" onClick={() => onCurrentChange(null)} aria-label="Close player">✕</button>
      </div>
    </div>
  )
}
