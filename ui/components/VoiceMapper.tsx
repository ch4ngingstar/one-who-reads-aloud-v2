'use client'
import { useEffect, useRef, useState } from 'react'
import { uploadVoice, deleteVoice, updateVoiceRefText, voiceAudioUrl } from '@/lib/api'
import ConfirmButton from '@/components/ConfirmButton'
import type { Voice } from '@/lib/types'

const DEFAULT_SPEAKERS = ['Narrator', 'Sunny', 'Nephis', 'Cassie', 'Effie', 'Kai', 'Morgan']

// ── Inline SVG icons ──────────────────────────────────────────────────────────

// Crystal Shard — memory rank indicator, replaces circular avatar
function CrystalShard({ color, size = 16 }: { color: string; size?: number }) {
  const w = Math.round(size * 0.55)
  return (
    <svg width={w} height={size} viewBox="0 0 9 16" fill="none" stroke={color} strokeLinecap="square" aria-hidden>
      {/* Outer shard silhouette */}
      <polygon points="4.5,0 9,5 7,16 2,16 0,5" strokeWidth="0.85" />
      {/* Internal facet lines — make it look 3D */}
      <line x1="4.5" y1="0" x2="2"   y2="16" strokeWidth="0.35" opacity="0.5" />
      <line x1="4.5" y1="0" x2="7"   y2="16" strokeWidth="0.35" opacity="0.5" />
      <line x1="0"   y1="5" x2="9"   y2="5"  strokeWidth="0.35" opacity="0.45" />
      <line x1="0.5" y1="9" x2="8.5" y2="9"  strokeWidth="0.25" opacity="0.3"  />
    </svg>
  )
}

// Data Sync — replace/upload icon, double chevrons + data bars
function DataSync({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={Math.round(size * 0.85)} viewBox="0 0 16 14" fill="none" stroke="currentColor" strokeLinecap="square" aria-hidden>
      <polyline points="0.5,1.5 4.5,7 0.5,12.5" strokeWidth="1.5" />
      <polyline points="5,1.5 9,7 5,12.5"        strokeWidth="1.5" />
      <line x1="11" y1="2.5"  x2="15.5" y2="2.5"  strokeWidth="1" />
      <line x1="11" y1="7"    x2="15.5" y2="7"    strokeWidth="0.6" />
      <line x1="11" y1="11.5" x2="15.5" y2="11.5" strokeWidth="1" />
    </svg>
  )
}

// Upload Arrow — for adding a new voice file
function UploadArrow({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeLinecap="square" aria-hidden>
      <polyline points="3.5,5 6,2 8.5,5" strokeWidth="1.5" />
      <line x1="6"   y1="2"  x2="6"   y2="9.5" strokeWidth="1.5" />
      <line x1="1.5" y1="11" x2="10.5" y2="11"  strokeWidth="1" />
    </svg>
  )
}

// Razor Slash — delete icon, two crossing strokes of differing weight
function RazorSlash({ size = 10 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeLinecap="square" aria-hidden>
      <line x1="1.5" y1="1.5" x2="10.5" y2="10.5" strokeWidth="2" />
      <line x1="10.5" y1="1"  x2="0.5"  y2="11"   strokeWidth="0.9" opacity="0.55" />
      <line x1="7.5"  y1="9"  x2="11"   y2="12.5"  strokeWidth="1.5" opacity="0.28" />
    </svg>
  )
}

// Echo Rune — sound-wave arcs, voice preview
function EchoRune({ size = 11 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeLinecap="square" aria-hidden>
      <polygon points="1,4.5 4,4.5 6.5,2 6.5,10 4,7.5 1,7.5" strokeWidth="0.9" />
      <path d="M8.5,4 A2.6,2.6 0 0,1 8.5,8"   strokeWidth="0.9" />
      <path d="M10,2.5 A4.6,4.6 0 0,1 10,9.5" strokeWidth="0.7" opacity="0.6" />
    </svg>
  )
}

// ── Inline transcript editor ──────────────────────────────────────────────────
function RefTextEditor({ speaker, initial, onSave }: {
  speaker: string; initial: string; onSave: (t: string) => Promise<void>
}) {
  const [open,   setOpen]   = useState(false)
  const [value,  setValue]  = useState(initial)
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    setSaving(true)
    try { await onSave(value.trim()); setOpen(false) }
    finally { setSaving(false) }
  }

  if (!open) {
    return (
      <button
        className="text-[10px] text-ink-ghost hover:text-ink-secondary transition-colors underline underline-offset-2 decoration-white/8"
        onClick={() => setOpen(true)}
        title="Optional note — IndexTTS2 clones from audio alone and ignores transcripts"
      >
        {initial ? 'edit transcript' : '+ add transcript'}
      </button>
    )
  }

  return (
    <div className="mt-2 space-y-1.5 animate-slide-up">
      <textarea
        className="input w-full resize-none font-mono"
        rows={2}
        placeholder={`What ${speaker} says in the clip…`}
        value={value}
        onChange={e => setValue(e.target.value)}
        autoFocus
      />
      <div className="flex gap-1.5">
        <button className="btn-primary text-[10px] py-1 px-3" onClick={handleSave} disabled={saving}>
          {saving ? '…' : 'Save'}
        </button>
        <button className="btn text-[10px] py-1 px-3" onClick={() => { setValue(initial); setOpen(false) }}>
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── VoiceMapper ───────────────────────────────────────────────────────────────
export default function VoiceMapper({ voices, onUpdate }: { voices: Voice[]; onUpdate: () => void }) {
  const [uploading,     setUploading]     = useState<string | null>(null)
  const [error,         setError]         = useState<string | null>(null)
  const [newSpeaker,    setNewSpeaker]    = useState('')
  const [extraSpeakers, setExtraSpeakers] = useState<string[]>([])
  const [previewing,    setPreviewing]    = useState<string | null>(null)
  const previewRef = useRef<HTMLAudioElement | null>(null)

  // One shared element — starting a preview stops whichever clip was playing.
  useEffect(() => () => { previewRef.current?.pause(); previewRef.current = null }, [])

  function togglePreview(speaker: string) {
    if (previewing === speaker) {
      previewRef.current?.pause()
      previewRef.current = null
      setPreviewing(null)
      return
    }
    previewRef.current?.pause()
    const audio = new Audio(voiceAudioUrl(speaker))
    audio.onended = () => setPreviewing(p => (p === speaker ? null : p))
    audio.onerror = () => {
      setPreviewing(p => (p === speaker ? null : p))
      setError(`Could not play the reference clip for ${speaker}.`)
    }
    previewRef.current = audio
    setError(null)
    setPreviewing(speaker)
    void audio.play().catch(() => setPreviewing(null))
  }

  const voiceMap    = Object.fromEntries(voices.map(v => [v.speaker, v]))
  const allSpeakers = Array.from(new Set([...DEFAULT_SPEAKERS, ...extraSpeakers, ...voices.map(v => v.speaker)]))

  function pickFile(speaker: string) {
    const input  = document.createElement('input')
    input.type   = 'file'
    input.accept = '.wav,.mp3,.flac'
    input.onchange = async () => {
      const file = input.files?.[0]; if (!file) return
      setUploading(speaker); setError(null)
      try { await uploadVoice(speaker, file); onUpdate() }
      catch (err) { setError(err instanceof Error ? err.message : 'Upload failed') }
      finally { setUploading(null) }
    }
    input.click()
  }

  async function handleDelete(speaker: string) {
    setError(null)
    try { await deleteVoice(speaker); onUpdate() }
    catch (err) { setError(err instanceof Error ? err.message : 'Delete failed') }
  }

  async function handleSaveRef(speaker: string, text: string) {
    setError(null)
    try { await updateVoiceRefText(speaker, text); onUpdate() }
    catch (err) { setError(err instanceof Error ? err.message : 'Save failed') }
  }

  function addCustomSpeaker() {
    const name = newSpeaker.trim()
    if (name && !allSpeakers.includes(name)) setExtraSpeakers(prev => [...prev, name])
    setNewSpeaker('')
  }

  const registered = voices.length

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <span className="label">Voice Mapping</span>
        <div className="flex-1 weaver-thread" />
      </div>

      {/* Roster summary */}
      <div className="flex items-center gap-2 text-[10px]">
        <span className="text-ink-ghost">
          <span className="tech text-sm text-ink-secondary">{registered}</span> voices
        </span>
      </div>

      {error && (
        <div
          className="px-3 py-2 text-xs text-[#991B1B] animate-slide-up"
          style={{ background: 'rgba(153,27,27,0.06)', border: '1px solid rgba(153,27,27,0.25)' }}
        >
          {error}
        </div>
      )}

      {/* Speaker rows */}
      <div className="space-y-1.5">
        {allSpeakers.map(speaker => {
          const voice         = voiceMap[speaker]
          const isUploading   = uploading === speaker
          const filename      = voice?.ref_audio_path.split(/[\\/]/).pop()
          const hasTranscript = Boolean(voice?.ref_text)
          const complete      = voice && hasTranscript

          // Monochrome — chrome for ready, zinc for partial, border-only for empty
          const leftAccent = complete ? '#D4D4D8' : voice ? '#52525B' : '#27272A'
          const cardMod    = complete ? 'memory-card--ready' : voice ? 'memory-card--partial' : ''

          return (
            <div
              key={speaker}
              className={`memory-card flex flex-col px-4 py-3 transition-all duration-150 ${cardMod}`}
              style={{ borderLeft: `3px solid ${leftAccent}` }}
            >
              <div className="flex items-center justify-between gap-3">
                {/* Crystal Shard + name */}
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="flex-shrink-0" style={{ opacity: voice ? 1 : 0.25 }}>
                    <CrystalShard color={leftAccent} size={15} />
                  </span>
                  <div className="min-w-0">
                    <span className="text-xs text-white font-medium block leading-none">{speaker}</span>
                    {voice && (
                      <span className="text-[9px] text-ink-ghost font-mono block truncate max-w-[90px] mt-0.5"
                            title={voice.ref_audio_path}>
                        {filename}
                      </span>
                    )}
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {voice && (
                    <button
                      className={`btn py-1 px-2 ${previewing === speaker ? '!text-[#D4D4D8] !border-[#52525B]' : ''}`}
                      onClick={() => togglePreview(speaker)}
                      aria-label={previewing === speaker ? `Stop ${speaker} preview` : `Preview ${speaker} voice`}
                      aria-pressed={previewing === speaker}
                      title="Play reference clip"
                    >
                      {previewing === speaker
                        ? <span className="equalizer" aria-hidden><span /><span /><span /></span>
                        : <EchoRune size={11} />}
                    </button>
                  )}
                  <button
                    className="btn text-[10px] py-1 px-2.5 gap-1.5"
                    onClick={() => pickFile(speaker)}
                    disabled={isUploading}
                    title={voice ? 'Replace voice file' : 'Upload voice file'}
                  >
                    {isUploading ? '…' : voice
                      ? <><DataSync size={11} /><span>SYNC</span></>
                      : <><UploadArrow size={11} /><span>LOAD</span></>
                    }
                  </button>
                  {voice && (
                    <ConfirmButton
                      className="btn-danger py-1 px-2"
                      confirmClassName="btn-danger py-1 px-2 text-[9px]"
                      confirmLabel="Remove?"
                      onConfirm={() => handleDelete(speaker)}
                      ariaLabel={`Remove ${speaker}`}
                      title="Remove mapping (audio file stays on disk)"
                    >
                      <RazorSlash size={9} />
                    </ConfirmButton>
                  )}
                </div>
              </div>

              {/* Transcript editor */}
              {voice && (
                <div className="mt-2 ml-5">
                  <RefTextEditor speaker={speaker} initial={voice.ref_text ?? ''} onSave={t => handleSaveRef(speaker, t)} />
                  {voice.ref_text && (
                    <p className="text-[9px] text-ink-ghost mt-1 line-clamp-1 italic">"{voice.ref_text}"</p>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Add custom speaker */}
      <div className="flex gap-1.5 mt-1">
        <input
          className="input flex-1"
          placeholder="Add speaker…"
          value={newSpeaker}
          onChange={e => setNewSpeaker(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCustomSpeaker())}
        />
        <button className="btn px-3.5 text-sm" onClick={addCustomSpeaker} aria-label="Add">+</button>
      </div>
    </div>
  )
}
