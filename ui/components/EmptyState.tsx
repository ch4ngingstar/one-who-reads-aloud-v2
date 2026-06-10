'use client'

/** Pre-project hero — Spell greeting and the pipeline stage map. */
export default function EmptyState({ hasProject }: { hasProject: boolean }) {
  if (hasProject) {
    return (
      <div className="flex items-center gap-2 text-[10px] text-ink-ghost font-mono">
        <span className="text-white/15 animate-twinkle">✦</span>
        <span>Loading chapters…</span>
      </div>
    )
  }

  return (
    <div className="flex flex-col items-center gap-5 max-w-[300px] text-center animate-slide-up">

      {/* Floating logo cluster */}
      <div className="relative w-20 h-20 flex items-center justify-center">
        <span className="text-white/15 animate-twinkle text-xs absolute top-0 right-0 select-none" aria-hidden>✦</span>
        <span className="text-white/12 animate-twinkle text-[9px] absolute bottom-1 left-0 select-none [animation-delay:2s]" aria-hidden>✧</span>
        <span className="text-white/10 animate-twinkle text-[8px] absolute top-2 left-2 select-none [animation-delay:1.2s]" aria-hidden>✦</span>
        <span className="text-white/10 text-6xl select-none animate-drift" aria-hidden>◈</span>
      </div>

      <div className="space-y-2">
        <div className="font-display text-[11px] text-white/30 tracking-[0.32em] uppercase select-none">
          Shadow Slave
        </div>
        <p className="text-[11px] font-mono text-ink-muted">
          <span className="text-white/20 select-none">[&thinsp;</span>
          You have entered the Dream Realm
          <span className="text-white/20 select-none">&thinsp;]</span>
        </p>
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
  )
}
