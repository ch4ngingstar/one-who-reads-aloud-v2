'use client'
import { useCallback, useEffect, useState } from 'react'
import {
  getSfx, getCues, putCues, generateCuesCloud, importCues, cuesExportUrl,
  type DiarizeProvider,
} from '@/lib/api'
import SfxLibrary from '@/components/SfxLibrary'
import { SFX_CATALOG, tagLabel } from '@/lib/sfxCatalog'
import type { Chapter, Cue, CueType, SfxAsset, SfxCategory } from '@/lib/types'

interface ProviderCfg {
  id: DiarizeProvider; label: string; keyStore: string; defaultModel: string; placeholder: string
}
// Reuses the SAME localStorage keys as the Diarize panel so a key entered once
// works for both cloud diarization and cloud sound design.
const PROVIDERS: ProviderCfg[] = [
  { id: 'claude', label: 'Claude · Anthropic', keyStore: 'anthropic_api_key', defaultModel: 'claude-opus-4-8', placeholder: 'sk-ant-…' },
  { id: 'openai', label: 'ChatGPT · OpenAI', keyStore: 'openai_api_key', defaultModel: 'gpt-4o', placeholder: 'sk-…' },
  { id: 'gemini', label: 'Gemini · Google', keyStore: 'gemini_api_key', defaultModel: 'gemini-2.5-flash', placeholder: 'AIza…' },
]
const CFG = (id: DiarizeProvider) => PROVIDERS.find(p => p.id === id) ?? PROVIDERS[0]

const CUE_CATEGORY: Record<CueType, SfxCategory> = { scene: 'ambience', sfx: 'sfx', music: 'music' }

/** Sound-design workspace for the selected chapter: let Claude author a
 *  restrained cue plan (ambience beds + sparse sfx + occasional music), review
 *  and tweak it, plus manage the clip library. Cues only take effect at assembly
 *  time when sound design is enabled. */
export default function SoundDesignPanel({ chapter, onChanged }: {
  chapter: Chapter | null; onChanged: () => void
}) {
  const [sfx, setSfx] = useState<SfxAsset[]>([])
  const [cues, setCues] = useState<Cue[]>([])
  const [reviewed, setReviewed] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [force, setForce] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const [provider, setProvider] = useState<DiarizeProvider>('claude')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')

  const refreshSfx = useCallback(async () => {
    try { setSfx((await getSfx()).sfx) } catch { /* silent */ }
  }, [])

  const refreshCues = useCallback(async () => {
    if (!chapter) { setCues([]); setReviewed(false); return }
    try {
      const r = await getCues(chapter.id)
      setCues(r.cues); setReviewed(r.reviewed); setDirty(false)
    } catch { setCues([]); setReviewed(false) }
  }, [chapter])

  useEffect(() => { refreshSfx() }, [refreshSfx])
  useEffect(() => { refreshCues(); setMsg(null) }, [refreshCues])

  useEffect(() => {
    const saved = localStorage.getItem('diar_provider') as DiarizeProvider | null
    if (saved && PROVIDERS.some(p => p.id === saved)) setProvider(saved)
  }, [])
  useEffect(() => {
    const cfg = CFG(provider)
    setApiKey(localStorage.getItem(cfg.keyStore) ?? '')
    let stored = localStorage.getItem(`sd_model_${provider}`) ?? cfg.defaultModel
    if (stored === 'gemini-3.1-pro') stored = 'gemini-3.1-pro-preview'
    setModel(stored)
  }, [provider])

  if (!chapter) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-spell-g5 select-none p-6 text-center">
        <span className="text-2xl text-spell-g3" aria-hidden>✦</span>
        <span className="text-[11px] tracking-[0.18em] uppercase">Select a chapter to score</span>
      </div>
    )
  }

  const padded = String(chapter.id).padStart(4, '0')
  const cfg = CFG(provider)

  function updateKey(v: string) { setApiKey(v); localStorage.setItem(CFG(provider).keyStore, v) }
  function updateModel(v: string) { setModel(v); localStorage.setItem(`sd_model_${provider}`, v) }
  function changeProvider(id: DiarizeProvider) { setProvider(id); localStorage.setItem('diar_provider', id) }

  async function handleCloud() {
    if (!apiKey.trim() || busy) return
    setBusy(true); setMsg(null)
    try {
      const data = await generateCuesCloud(chapter!.id, {
        provider, apiKey: apiKey.trim(), model: model.trim() || undefined, force,
      })
      setMsg({ ok: true, text: `designed — ${data.cues} cues` })
      await refreshCues(); onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    }
    setBusy(false)
  }

  async function handleImport(files: FileList | null) {
    if (!files || files.length === 0) return
    setBusy(true); setMsg(null)
    try {
      const payload = JSON.parse(await files[0].text())
      const data = await importCues(chapter!.id, payload, force)
      setMsg({ ok: true, text: `imported — ${data.cues} cues` })
      await refreshCues(); onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    }
    setBusy(false)
  }

  async function handleSave() {
    setBusy(true); setMsg(null)
    try {
      const data = await putCues(chapter!.id, cues)
      setMsg({ ok: true, text: `saved — ${data.cues} cues` })
      setReviewed(true); setDirty(false); onChanged()
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : String(err) })
    }
    setBusy(false)
  }

  function patchCue(i: number, patch: Partial<Cue>) {
    setCues(prev => prev.map((c, idx) => (idx === i ? { ...c, ...patch } : c))); setDirty(true)
  }
  function removeCue(i: number) {
    setCues(prev => prev.filter((_, idx) => idx !== i)); setDirty(true)
  }
  function addCue(type: CueType) {
    const cat = CUE_CATEGORY[type]
    const tag = (sfx.find(s => s.category === cat)?.tag) ?? SFX_CATALOG[cat][0]
    setCues(prev => [...prev, {
      cue_type: type, tag, line_start: 0,
      line_end: type === 'scene' ? 0 : null,
      at_anchor: type === 'sfx' ? 'start' : null,
      gain_db: type === 'scene' ? -22 : type === 'music' ? -20 : -14,
      duration_s: type === 'music' ? 8 : null, source: 'manual',
    }])
    setDirty(true)
  }

  function tagOptions(type: CueType): string[] {
    const cat = CUE_CATEGORY[type]
    const reg = sfx.filter(s => s.category === cat).map(s => s.tag)
    return Array.from(new Set([...reg, ...SFX_CATALOG[cat]]))
  }

  return (
    <div className="flex-1 overflow-y-auto p-5 min-h-0">
      <div className="font-display text-[15px] tracking-[1.5px] text-ink-primary leading-snug">
        Ch. {chapter.chapter_index + 1} — {chapter.title}
      </div>
      <div className="text-[10px] tracking-[0.18em] uppercase text-spell-g5 mt-1 flex items-center gap-2">
        {chapter.status}
        {reviewed && <span className="text-spell-g4">· cues reviewed</span>}
      </div>

      {/* Cloud sound design */}
      <section className="mt-5">
        <div className="flex items-center gap-2 text-[9px] tracking-[2px] uppercase text-spell-g4 mb-3">
          <span className="text-[14px] leading-none text-ink-secondary" aria-hidden>✦</span>
          Cloud sound design
        </div>
        <label className="block text-[9px] tracking-[1.6px] uppercase text-spell-g5 mb-1">Provider</label>
        <select className="input w-full text-[11px] cursor-pointer" value={provider} disabled={busy}
                onChange={e => changeProvider(e.target.value as DiarizeProvider)}>
          {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <label className="block text-[9px] tracking-[1.6px] uppercase text-spell-g5 mb-1 mt-3">Model</label>
        <input type="text" className="input w-full text-[11px] font-mono" placeholder={cfg.defaultModel}
               value={model} disabled={busy} onChange={e => updateModel(e.target.value)} />
        <label className="block text-[9px] tracking-[1.6px] uppercase text-spell-g5 mb-1 mt-3">API key</label>
        <input type="password" className="input w-full text-[11px]" placeholder={cfg.placeholder}
               value={apiKey} disabled={busy} onChange={e => updateKey(e.target.value)} />
        <button className="btn-primary w-full mt-4" disabled={busy || !apiKey.trim()} onClick={handleCloud}>
          {busy ? 'Designing…' : 'Design this chapter'}
        </button>
        <p className="mt-2 text-[9px] leading-snug text-spell-g6">
          Claude scores the chapter with restrained ambience beds, sparse sfx and occasional music,
          against a fixed Shadow-Slave vocabulary. Cues only render when sound design is enabled at
          generation time. The key is stored in this browser only.
        </p>
      </section>

      <label className="flex items-center gap-1.5 mt-4 text-[10px] text-spell-g5 cursor-pointer select-none">
        <input type="checkbox" checked={force} disabled={busy} onChange={e => setForce(e.target.checked)} />
        force overwrite (re-design even if cues were hand-edited)
      </label>

      {/* Manual import/export */}
      <section className="mt-5 pt-4 border-t border-[#1a1a1a]">
        <div className="text-[9px] tracking-[2px] uppercase text-spell-g4 mb-2.5">Manual / external</div>
        <div className="flex gap-2">
          <a className="btn-gold flex-1 text-center" href={cuesExportUrl(chapter.id)}
             download={`ch_${padded}.cue-export.json`}>↓ Export segments</a>
          <label className="btn-gold flex-1 text-center cursor-pointer" aria-disabled={busy}>
            ↑ Import cues
            <input type="file" accept=".json,application/json" className="hidden" disabled={busy}
                   onChange={e => handleImport(e.target.files)} />
          </label>
        </div>
      </section>

      {/* Cue editor */}
      <section className="mt-5 pt-4 border-t border-[#1a1a1a]">
        <div className="flex items-center justify-between mb-2.5">
          <span className="text-[9px] tracking-[2px] uppercase text-spell-g4">
            Cues · {cues.length}
          </span>
          {dirty && (
            <button className="btn-primary text-[10px] py-1 px-3" disabled={busy} onClick={handleSave}>
              Save edits
            </button>
          )}
        </div>

        {cues.length === 0 && (
          <p className="text-[10px] text-spell-g6 italic">No cues yet — design with Claude or add below.</p>
        )}

        <div className="space-y-1.5">
          {cues.map((c, i) => (
            <div key={c.id ?? `n${i}`} className="memory-card px-3 py-2"
                 style={{ borderLeft: '3px solid #27272A' }}>
              <div className="flex items-center gap-1.5">
                <span className="text-[8px] tracking-[1.5px] uppercase text-spell-g5 w-9">{c.cue_type}</span>
                <select className="input text-[10px] flex-1 min-w-0 cursor-pointer" value={c.tag}
                        onChange={e => patchCue(i, { tag: e.target.value })}>
                  {tagOptions(c.cue_type).map(t => <option key={t} value={t}>{tagLabel(t)}</option>)}
                </select>
                <button className="btn-danger py-0.5 px-1.5 text-[9px]" onClick={() => removeCue(i)}
                        aria-label="Remove cue">✕</button>
              </div>
              <div className="flex items-center gap-2 mt-1.5 text-[9px] text-spell-g5">
                <label className="flex items-center gap-1">L<input type="number" min={0}
                  className="input w-12 text-[10px] py-0.5 px-1" value={c.line_start}
                  onChange={e => patchCue(i, { line_start: Number(e.target.value) })} /></label>
                {c.cue_type === 'scene' && (
                  <label className="flex items-center gap-1">→<input type="number" min={0}
                    className="input w-12 text-[10px] py-0.5 px-1" value={c.line_end ?? 0}
                    onChange={e => patchCue(i, { line_end: Number(e.target.value) })} /></label>
                )}
                {c.cue_type === 'sfx' && (
                  <select className="input text-[10px] py-0.5 px-1 cursor-pointer" value={c.at_anchor ?? 'start'}
                          onChange={e => patchCue(i, { at_anchor: e.target.value as 'start' | 'end' })}>
                    <option value="start">at start</option>
                    <option value="end">at end</option>
                  </select>
                )}
                <label className="flex items-center gap-1 ml-auto">{c.gain_db}dB
                  <input type="range" min={-40} max={0} step={1} value={c.gain_db}
                    onChange={e => patchCue(i, { gain_db: Number(e.target.value) })} /></label>
              </div>
            </div>
          ))}
        </div>

        <div className="flex gap-1.5 mt-2">
          {(['scene', 'sfx', 'music'] as CueType[]).map(t => (
            <button key={t} className="btn text-[10px] py-1 px-2 flex-1" onClick={() => addCue(t)}>
              + {t}
            </button>
          ))}
        </div>
      </section>

      {msg && (
        <p className={`mt-3 text-[10px] leading-snug break-words ${msg.ok ? 'text-emerald-500' : 'text-blood-text'}`}>
          {msg.text}
        </p>
      )}

      {/* Library */}
      <section className="mt-6 pt-4 border-t border-[#1a1a1a]">
        <SfxLibrary sfx={sfx} onUpdate={refreshSfx} />
      </section>
    </div>
  )
}
