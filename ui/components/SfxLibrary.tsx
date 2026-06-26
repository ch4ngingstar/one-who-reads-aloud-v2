'use client'
import { useEffect, useRef, useState } from 'react'
import { uploadSfx, deleteSfx, sfxAudioUrl } from '@/lib/api'
import ConfirmButton from '@/components/ConfirmButton'
import { SFX_CATALOG, SFX_CATEGORIES, CATEGORY_LABEL, tagLabel } from '@/lib/sfxCatalog'
import type { SfxAsset, SfxCategory } from '@/lib/types'

/** The sound-design library: tagged ambience / sfx / music clips, mirroring the
 *  voice mapper. Recommended Shadow-Slave tags show as empty slots to fill; you
 *  upload a clip per tag (CC0 / royalty-free). Files normalise server-side
 *  (ambience/music stereo, sfx mono). */
export default function SfxLibrary({ sfx, onUpdate }: {
  sfx: SfxAsset[]; onUpdate: () => void
}) {
  const [uploading, setUploading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState<string | null>(null)
  const [versions, setVersions] = useState<Record<string, number>>({})
  const [okTags, setOkTags] = useState<Set<string>>(new Set())
  const [customTag, setCustomTag] = useState('')
  const [customCat, setCustomCat] = useState<SfxCategory>('ambience')
  const previewRef = useRef<HTMLAudioElement | null>(null)

  useEffect(() => () => { previewRef.current?.pause(); previewRef.current = null }, [])

  const byTag = Object.fromEntries(sfx.map(s => [s.tag, s]))

  function togglePreview(tag: string) {
    if (previewing === tag) {
      previewRef.current?.pause(); previewRef.current = null; setPreviewing(null); return
    }
    previewRef.current?.pause()
    const v = versions[tag]
    const audio = new Audio(sfxAudioUrl(tag) + (v ? `?v=${v}` : ''))
    audio.onended = () => setPreviewing(p => (p === tag ? null : p))
    audio.onerror = () => { setPreviewing(p => (p === tag ? null : p)); setError(`Could not play '${tag}'.`) }
    previewRef.current = audio
    setError(null); setPreviewing(tag)
    void audio.play().catch(() => setPreviewing(null))
  }

  function pickFile(tag: string, category: SfxCategory) {
    const input = document.createElement('input')
    input.type = 'file'; input.accept = '.wav,.mp3,.flac,.ogg'; input.style.display = 'none'
    document.body.appendChild(input)
    input.onchange = async () => {
      document.body.removeChild(input)
      const file = input.files?.[0]; if (!file) return
      setUploading(tag); setError(null)
      try {
        await uploadSfx(tag, category, file)
        setVersions(prev => ({ ...prev, [tag]: Date.now() }))
        setOkTags(prev => new Set(prev).add(tag))
        setTimeout(() => setOkTags(prev => { const s = new Set(prev); s.delete(tag); return s }), 2500)
        onUpdate()
      } catch (err) { setError(err instanceof Error ? err.message : 'Upload failed') }
      finally { setUploading(null) }
    }
    input.click()
  }

  async function handleDelete(tag: string) {
    setError(null)
    try { await deleteSfx(tag); onUpdate() }
    catch (err) { setError(err instanceof Error ? err.message : 'Delete failed') }
  }

  function addCustom() {
    const slug = customTag.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')
    if (slug) pickFile(slug, customCat)
    setCustomTag('')
  }

  const registered = sfx.length

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <span className="label">Sound Library</span>
        <div className="flex-1 weaver-thread" />
        <span className="text-[10px] text-ink-ghost">
          <span className="tech text-sm text-ink-secondary">{registered}</span> clips
        </span>
      </div>

      {error && (
        <div className="px-3 py-2 text-xs text-[#991B1B]"
             style={{ background: 'rgba(153,27,27,0.06)', border: '1px solid rgba(153,27,27,0.25)' }}>
          {error}
        </div>
      )}

      {SFX_CATEGORIES.map(category => {
        // union of registered tags for this category + recommended catalogue tags
        const regTags = sfx.filter(s => s.category === category).map(s => s.tag)
        const tags = Array.from(new Set([...SFX_CATALOG[category], ...regTags]))
        return (
          <div key={category} className="space-y-1.5">
            <div className="text-[9px] tracking-[2px] uppercase text-spell-g4 mt-2">
              {CATEGORY_LABEL[category]}
            </div>
            {tags.map(tag => {
              const asset = byTag[tag]
              const isUploading = uploading === tag
              const filename = asset?.audio_path.split(/[\\/]/).pop()
              const accent = asset ? '#D4D4D8' : '#27272A'
              return (
                <div key={tag} className={`memory-card flex flex-col px-4 py-2.5 ${asset ? 'memory-card--ready' : ''}`}
                     style={{ borderLeft: `3px solid ${accent}` }}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <span className="text-xs text-white font-medium block leading-none">{tagLabel(tag)}</span>
                      <span className="text-[9px] text-ink-ghost font-mono block truncate max-w-[120px] mt-0.5"
                            title={asset?.audio_path ?? 'not yet supplied'}>
                        {asset ? filename : 'recommended — not supplied'}
                      </span>
                    </div>
                    <div className="flex items-center gap-1.5 flex-shrink-0">
                      {asset && (
                        <button
                          className={`btn py-1 px-2 ${previewing === tag ? '!text-[#D4D4D8] !border-[#52525B]' : ''}`}
                          onClick={() => togglePreview(tag)}
                          aria-pressed={previewing === tag}
                          title="Play clip"
                        >
                          {previewing === tag
                            ? <span className="equalizer" aria-hidden><span /><span /><span /></span>
                            : '▶'}
                        </button>
                      )}
                      <button
                        className={`btn text-[10px] py-1 px-2.5 ${okTags.has(tag) ? '!text-emerald-400 !border-emerald-700' : ''}`}
                        onClick={() => pickFile(tag, category)}
                        disabled={isUploading}
                        title={asset ? 'Replace clip' : 'Upload clip'}
                      >
                        {isUploading ? '…' : okTags.has(tag) ? '✓ SAVED' : asset ? 'SYNC' : 'LOAD'}
                      </button>
                      {asset && (
                        <ConfirmButton
                          className="btn-danger py-1 px-2"
                          confirmClassName="btn-danger py-1 px-2 text-[9px]"
                          confirmLabel="Remove?"
                          onConfirm={() => handleDelete(tag)}
                          ariaLabel={`Remove ${tag}`}
                          title="Remove mapping (file stays on disk)"
                        >✕</ConfirmButton>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )
      })}

      {/* Add a custom tag outside the recommended catalogue */}
      <div className="flex gap-1.5 mt-1">
        <select className="input text-[11px] cursor-pointer" value={customCat}
                onChange={e => setCustomCat(e.target.value as SfxCategory)}>
          {SFX_CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <input
          className="input flex-1"
          placeholder="custom tag…"
          value={customTag}
          onChange={e => setCustomTag(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCustom())}
        />
        <button className="btn px-3.5 text-sm" onClick={addCustom} aria-label="Add + upload">+</button>
      </div>
    </div>
  )
}
