'use client'
import type { Progress } from '@/lib/types'
import type { PipeStatus, Stage } from '@/hooks/usePipelineState'

const STATUS_LABEL: Record<PipeStatus, string> = {
  idle: 'Dormant', running: 'Running', paused: 'Suspended',
  complete: 'Complete', stopped: 'Stopped', error: 'Error',
}

const STAGE_LABEL: Record<Stage, string> = {
  diarize: 'Weaving', synthesize: 'Synthesizing', assemble: 'Binding',
}

interface Props {
  pipeStatus: PipeStatus
  connected: boolean
  progress: Progress | null
  activeStage: Stage | null
  eta: string
  vramMb: number | null
  canStart: boolean
  onStart: () => void
  onPause: () => void
  onResume: () => void
  onStop: () => void
}

function Stat({ value, label, live = false }: {
  value: React.ReactNode; label: string; live?: boolean
}) {
  return (
    <div className="flex items-baseline gap-2">
      <span className={`font-mono text-sm tabular-nums ${
        live ? 'text-ink-hot animate-breathe [text-shadow:0_0_12px_rgba(255,255,255,0.5)]' : 'text-ink-primary'
      }`}>
        {value}
      </span>
      <span className="text-[9px] tracking-[0.18em] text-spell-g5 uppercase">{label}</span>
    </div>
  )
}

const Sep = () => <span className="w-px h-[18px] bg-spell-g2" aria-hidden />

export default function CommandStrip({
  pipeStatus, connected, progress, activeStage, eta, vramMb, canStart,
  onStart, onPause, onResume, onStop,
}: Props) {
  const running  = pipeStatus === 'running'
  const paused   = pipeStatus === 'paused'
  const severed  = (running || paused) && !connected

  const liveLabel = severed
    ? 'Link severed'
    : running
      ? (activeStage ? STAGE_LABEL[activeStage] : 'Running')
      : STATUS_LABEL[pipeStatus]

  return (
    <header className="glass-panel flex items-center gap-7 px-6 pt-5 pb-4 flex-shrink-0">
      <div className="select-none">
        <h1 className="font-display font-bold text-[21px] leading-none tracking-[6px] text-ink-primary
                       animate-flicker [text-shadow:0_0_18px_rgba(255,255,255,0.22),0_0_60px_rgba(255,255,255,0.08)]">
          ONE WHO READS ALOUD
        </h1>
        <span className="block mt-1 text-[9px] tracking-[3.5px] uppercase text-spell-g5">
          Shadow Slave · Audiobook Forge
        </span>
      </div>

      <div className="flex gap-2.5">
        {canStart && (
          <button className="btn-primary" onClick={onStart}>▶ Run</button>
        )}
        {running && <button className="btn" onClick={onPause}>‖ Pause</button>}
        {paused  && <button className="btn-primary" onClick={onResume}>▶ Resume</button>}
        {(running || paused) && <button className="btn-danger" onClick={onStop}>■ Stop</button>}
      </div>

      <div className="ml-auto flex items-center gap-5">
        <div className="flex items-baseline gap-2">
          <span className={`text-sm leading-none ${
            severed
              ? 'text-spell-g5'
              : running
                ? 'text-ink-hot animate-breathe [text-shadow:0_0_12px_rgba(255,255,255,0.5)]'
                : 'text-spell-g6'
          }`} aria-hidden>✦</span>
          <span className="text-[9px] tracking-[0.18em] uppercase text-spell-g5">{liveLabel}</span>
        </div>
        {progress && (
          <>
            <Sep />
            <Stat
              value={<>
                <span className="text-ink-primary">{progress.complete}</span>
                <span className="text-spell-g5">∕{progress.total}</span>
              </>}
              label="Chapters"
            />
          </>
        )}
        {eta && (<><Sep /><Stat value={eta.replace(' left', '')} label="ETA" /></>)}
        <Sep />
        <Stat value={vramMb != null ? `${(vramMb / 1024).toFixed(1)}G` : '—'} label="VRAM" />
      </div>
    </header>
  )
}
