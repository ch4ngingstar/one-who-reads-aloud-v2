'use client'
import { useState, useRef, useEffect, useCallback } from 'react'

const SPEEDS    = [0.75, 1, 1.25, 1.5, 2] as const
type  Speed     = typeof SPEEDS[number]
const SKIP_SECS = 15

// Voice-like waveform envelope
const WAVE_H = [28,55,72,44,88,36,68,52,82,40,74,30,62,85,48,78,35,65,90,42]

function fmtTime(s: number) {
  if (!isFinite(s) || isNaN(s)) return '--:--'
  return `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
}

interface Props {
  src:      string
  onEnded?: () => void
  onClose?: () => void
}

export default function AudioPlayer({ src, onEnded, onClose }: Props) {
  const ref                     = useRef<HTMLAudioElement>(null)
  const [playing,  setPlaying]  = useState(false)
  const [current,  setCurrent]  = useState(0)
  const [duration, setDuration] = useState(0)
  const [volume,   setVolume]   = useState(1)
  const [speed,    setSpeed]    = useState<Speed>(1)
  const [ready,    setReady]    = useState(false)
  const [muted,    setMuted]    = useState(false)

  useEffect(() => { if (ref.current) ref.current.playbackRate = speed }, [speed])
  useEffect(() => { if (ref.current) ref.current.muted = muted }, [muted])

  const toggle = useCallback(() => {
    if (!ref.current) return
    playing ? ref.current.pause() : ref.current.play()
  }, [playing])

  function skip(s: number) {
    if (!ref.current || !ready) return
    ref.current.currentTime = Math.max(0, Math.min(duration, ref.current.currentTime + s))
  }

  const pct       = duration > 0 ? (current / duration) * 100 : 0
  const activeBars = Math.floor((pct / 100) * WAVE_H.length)

  return (
    <div className="glass-card overflow-hidden animate-slide-up" style={{ borderRadius: '12px' }}>
      <audio
        ref={ref}
        src={src}
        onTimeUpdate={() => setCurrent(ref.current?.currentTime ?? 0)}
        onLoadedMetadata={() => { setDuration(ref.current?.duration ?? 0); setReady(true) }}
        onEnded={() => { setPlaying(false); onEnded?.() }}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
      />

      {/* ── Waveform ─────────────────────────────────────────────────── */}
      <div className="px-4 pt-4 pb-1">
        {/* Bars */}
        <div className="relative flex items-end gap-[2px] h-12 mb-2">
          {/* Progress sweep */}
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `linear-gradient(to right, rgba(212,212,216,0.06) 0%, rgba(212,212,216,0.02) ${Math.max(0,pct-12)}%, transparent ${pct}%)`,
            }}
          />
          {/* Playhead needle */}
          {ready && (
            <div
              className="absolute top-0 bottom-0 w-px pointer-events-none"
              style={{ left: `${pct}%`, background: 'rgba(212,212,216,0.6)' }}
            />
          )}
          {WAVE_H.map((h, i) => (
            <div
              key={i}
              className={`flex-1 min-w-0 rounded-[1px] transition-colors ${playing ? 'animate-wave' : ''}`}
              style={{
                height: `${h}%`,
                backgroundColor: i < activeBars
                  ? 'rgba(212,212,216,0.45)'
                  : i === activeBars
                  ? 'rgba(212,212,216,0.7)'
                  : '#27272A',
                animationDelay:    `${(i * 53) % 580}ms`,
                animationDuration: `${560 + (i * 43) % 320}ms`,
              }}
            />
          ))}
        </div>

        {/* Seek */}
        <input
          type="range"
          min={0}
          max={duration || 100}
          step={0.1}
          value={current}
          onChange={e => { if (!ref.current || !ready) return; const v = Number(e.target.value); ref.current.currentTime = v; setCurrent(v) }}
          disabled={!ready}
          className="w-full block"
          style={{ marginBottom: '2px' }}
          aria-label="Seek"
        />

        {/* Time */}
        <div className="flex justify-between mb-1">
          <span className="text-[10px] text-ink-ghost font-mono tabular-nums">{fmtTime(current)}</span>
          <span className="text-[10px] text-ink-ghost font-mono tabular-nums">{fmtTime(duration)}</span>
        </div>
      </div>

      {/* ── Controls ─────────────────────────────────────────────────── */}
      <div
        className="px-4 pb-4 pt-3 flex items-center justify-between gap-3 flex-wrap"
        style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}
      >
        {/* Transport */}
        <div className="flex items-center gap-1.5">
          <button
            className="btn text-[10px] px-2.5 py-1.5 font-mono"
            onClick={() => skip(-SKIP_SECS)}
            disabled={!ready}
            title={`Back ${SKIP_SECS}s`}
          >
            ⟨{SKIP_SECS}s
          </button>
          <button
            onClick={toggle}
            disabled={!ready}
            aria-label={playing ? 'Pause' : 'Play'}
            className={`flex items-center justify-center w-10 h-10 rounded-full text-base
                        transition-all duration-150 active:scale-95 ${
              ready
                ? 'bg-[#0A0A0A] border border-[#52525B] text-[#D4D4D8] hover:bg-[#121212] hover:border-[#A0A0A8]'
                : 'bg-white/5 border border-white/8 text-ink-ghost opacity-40 cursor-not-allowed'
            }`}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <button
            className="btn text-[10px] px-2.5 py-1.5 font-mono"
            onClick={() => skip(SKIP_SECS)}
            disabled={!ready}
            title={`Forward ${SKIP_SECS}s`}
          >
            {SKIP_SECS}s⟩
          </button>
        </div>

        {/* Speed */}
        <div className="flex items-center gap-1" role="group" aria-label="Playback speed">
          <span className="text-[9px] text-ink-ghost mr-1 uppercase tracking-wider select-none">spd</span>
          {SPEEDS.map(s => (
            <button
              key={s}
              onClick={() => setSpeed(s)}
              aria-pressed={speed === s}
              className={`text-[10px] font-mono px-2 py-1 rounded-md transition-all ${
                speed === s
                  ? 'bg-[#0A0A0A] text-[#D4D4D8] border border-[#52525B]'
                  : 'bg-white/4 text-ink-ghost border border-white/6 hover:bg-white/7 hover:text-ink-muted'
              }`}
            >
              {s}×
            </button>
          ))}
        </div>

        {/* Volume + close */}
        <div className="flex items-center gap-2 ml-auto">
          <button
            className="text-[11px] text-ink-secondary hover:text-ink-primary transition-colors w-4 text-center"
            onClick={() => setMuted(m => !m)}
            aria-label={muted ? 'Unmute' : 'Mute'}
          >
            {muted || volume === 0 ? '○' : volume < 0.5 ? '◔' : '◕'}
          </button>
          <input
            type="range"
            min={0} max={1} step={0.05}
            value={muted ? 0 : volume}
            onChange={e => { const v = Number(e.target.value); setVolume(v); if (ref.current) ref.current.volume = v; if (v > 0) setMuted(false) }}
            className="range-vol w-14"
            aria-label={`Volume ${Math.round((muted ? 0 : volume) * 100)}%`}
          />
          {onClose && (
            <button className="btn text-[10px] px-2 py-1 ml-1" onClick={onClose} aria-label="Close">✕</button>
          )}
        </div>
      </div>

      {!ready && (
        <div className="px-4 pb-3 text-[10px] text-ink-ghost font-mono animate-pulse">Loading audio…</div>
      )}
    </div>
  )
}
