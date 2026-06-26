'use client'
import { useEffect, useState } from 'react'
import {
  chapterSegmentsUrl, diarizeChapterCloud, getLines, importChapterLabels,
  type DiarizeProvider,
} from '@/lib/api'
import type { Chapter } from '@/lib/types'

/** Download the finished labelled chapter (speaker + emotion + text per line)
 *  as a readable script. Reuses GET /chapters/{id}/lines — no backend change. */
async function downloadDiarization(chapter: Chapter) {
  const { lines } = await getLines(chapter.id)
  const header = `Ch. ${chapter.chapter_index + 1} — ${chapter.title}\n` +
                 `${lines.length} lines\n\n`
  const body = lines.map((l, idx) =>
    `[${String(idx + 1).padStart(4, '0')}] ${l.speaker} (${l.emotion}): ${l.text}`
  ).join('\n')
  const blob = new Blob([header + body], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `ch_${String(chapter.id).padStart(4, '0')}.diarization.txt`
  a.click()
  URL.revokeObjectURL(url)
}

interface ProviderCfg {
  id: DiarizeProvider
  label: string
  keyStore: string
  modelStore: string
  defaultModel: string
  placeholder: string
}

const PROVIDERS: ProviderCfg[] = [
  { id: 'claude', label: 'Claude · Anthropic', keyStore: 'anthropic_api_key',
    modelStore: 'diar_model_claude', defaultModel: 'claude-opus-4-8', placeholder: 'sk-ant-…' },
  { id: 'openai', label: 'ChatGPT · OpenAI', keyStore: 'openai_api_key',
    modelStore: 'diar_model_openai', defaultModel: 'gpt-4o', placeholder: 'sk-…' },
  { id: 'gemini', label: 'Gemini · Google', keyStore: 'gemini_api_key',
    modelStore: 'diar_model_gemini', defaultModel: 'gemini-1.5-pro', placeholder: 'AIza…' },
]

const PROVIDER_CFG = (id: DiarizeProvider) =>
  PROVIDERS.find(p => p.id === id) ?? PROVIDERS[0]

interface LabelResult { name: string; ok: boolean; message: string }

/** The diarization workspace for the selected chapter: assign speaker + emotion
 *  per line via a cloud LLM (Claude / ChatGPT / Gemini, one click) or by hand
 *  (export → label → import). The labelled lines are reviewed in the Inspector. */
export default function DiarizePanel({ chapter, onChanged }: {
  chapter: Chapter | null; onChanged: () => void
}) {
  const [results, setResults] = useState<LabelResult[]>([])
  const [busy, setBusy] = useState(false)
  const [force, setForce] = useState(false)
  const [provider, setProvider] = useState<DiarizeProvider>('claude')
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState('')

  // Restore the last-used provider once.
  useEffect(() => {
    const saved = localStorage.getItem('diar_provider') as DiarizeProvider | null
    if (saved && PROVIDERS.some(p => p.id === saved)) setProvider(saved)
  }, [])

  // Load the active provider's saved key + model whenever the provider changes.
  useEffect(() => {
    const cfg = PROVIDER_CFG(provider)
    setApiKey(localStorage.getItem(cfg.keyStore) ?? '')
    setModel(localStorage.getItem(cfg.modelStore) ?? cfg.defaultModel)
  }, [provider])

  useEffect(() => { setResults([]) }, [chapter?.id])

  if (!chapter) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-spell-g5 select-none p-6 text-center">
        <span className="text-2xl text-spell-g3" aria-hidden>✦</span>
        <span className="text-[11px] tracking-[0.18em] uppercase">Select a chapter to diarize</span>
      </div>
    )
  }

  const padded = String(chapter.id).padStart(4, '0')

  function changeProvider(id: DiarizeProvider) {
    setProvider(id)
    localStorage.setItem('diar_provider', id)
  }

  function updateApiKey(value: string) {
    setApiKey(value)
    localStorage.setItem(PROVIDER_CFG(provider).keyStore, value)
  }

  function updateModel(value: string) {
    setModel(value)
    localStorage.setItem(PROVIDER_CFG(provider).modelStore, value)
  }

  async function handleDiarizeCloud() {
    if (!chapter || !apiKey.trim() || busy) return
    setBusy(true)
    setResults([])
    try {
      const data = await diarizeChapterCloud(chapter.id, {
        provider, apiKey: apiKey.trim(), model: model.trim() || undefined, force,
      })
      setResults([{ name: `ch_${padded}`, ok: true, message: `diarized (${data.lines} lines)` }])
      onChanged()
    } catch (err) {
      setResults([{
        name: `ch_${padded}`, ok: false,
        message: err instanceof Error ? err.message : String(err),
      }])
    }
    setBusy(false)
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return
    setBusy(true)
    const out: LabelResult[] = []
    for (const file of Array.from(files)) {
      const m = file.name.match(/ch_(\d+)\.labels\.json$/)
      if (!m) {
        out.push({ name: file.name, ok: false, message: 'not a ch_XXXX.labels.json file' })
        continue
      }
      const chapterId = parseInt(m[1], 10)
      try {
        const body = JSON.parse(await file.text())
        const data = await importChapterLabels(chapterId, body, force)
        out.push({ name: file.name, ok: true, message: `diarized (${data.lines} lines)` })
      } catch (err) {
        out.push({ name: file.name, ok: false, message: err instanceof Error ? err.message : String(err) })
      }
    }
    setResults(out)
    setBusy(false)
    if (out.some(r => r.ok)) onChanged()
  }

  const cfg = PROVIDER_CFG(provider)
  const hasDiarization = chapter.status !== 'pending'

  return (
    <div className="flex-1 overflow-y-auto p-5 min-h-0">
      <div className="font-display text-[15px] tracking-[1.5px] text-ink-primary leading-snug">
        Ch. {chapter.chapter_index + 1} — {chapter.title}
      </div>
      <div className="text-[10px] tracking-[0.18em] uppercase text-spell-g5 mt-1">
        {chapter.status}
      </div>

      {/* Primary path: one-click cloud diarization */}
      <section className="mt-5">
        <div className="flex items-center gap-2 text-[9px] tracking-[2px] uppercase text-spell-g4 mb-3">
          <span className="text-[14px] leading-none text-ink-secondary" aria-hidden>✦</span>
          Cloud diarization
        </div>

        <label className="block text-[9px] tracking-[1.6px] uppercase text-spell-g5 mb-1">Provider</label>
        <select
          className="input w-full text-[11px] cursor-pointer"
          value={provider}
          disabled={busy}
          onChange={e => changeProvider(e.target.value as DiarizeProvider)}
        >
          {PROVIDERS.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>

        <label className="block text-[9px] tracking-[1.6px] uppercase text-spell-g5 mb-1 mt-3">Model</label>
        <input
          type="text"
          className="input w-full text-[11px] font-mono"
          placeholder={cfg.defaultModel}
          value={model}
          disabled={busy}
          onChange={e => updateModel(e.target.value)}
        />

        <label className="block text-[9px] tracking-[1.6px] uppercase text-spell-g5 mb-1 mt-3">API key</label>
        <input
          type="password"
          className="input w-full text-[11px]"
          placeholder={cfg.placeholder}
          value={apiKey}
          disabled={busy}
          onChange={e => updateApiKey(e.target.value)}
        />

        <button
          className="btn-primary w-full mt-4"
          disabled={busy || !apiKey.trim()}
          onClick={handleDiarizeCloud}
        >
          {busy ? 'Diarizing…' : 'Diarize this chapter'}
        </button>
        <p className="mt-2 text-[9px] leading-snug text-spell-g6">
          Labels speaker + emotion per line with no local LLM. The key is stored in this
          browser only and sent per request — never saved on the server. The server needs the
          provider&apos;s SDK installed (anthropic / openai / google-generativeai).
        </p>
      </section>

      <label className="flex items-center gap-1.5 mt-4 text-[10px] text-spell-g5 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={force}
          disabled={busy}
          onChange={e => setForce(e.target.checked)}
        />
        force overwrite (re-diarize past diarized — clears existing audio)
      </label>

      {/* Secondary path: manual round-trip */}
      <section className="mt-5 pt-4 border-t border-[#1a1a1a]">
        <div className="text-[9px] tracking-[2px] uppercase text-spell-g4 mb-2.5">
          Manual / external
        </div>
        <div className="flex gap-2">
          <a
            className="btn-gold flex-1 text-center"
            href={chapterSegmentsUrl(chapter.id)}
            download={`ch_${padded}.segments.json`}
          >↓ Export segments</a>
          <label className="btn-gold flex-1 text-center cursor-pointer" aria-disabled={busy}>
            ↑ Import labels
            <input
              type="file"
              accept=".json,application/json"
              multiple
              className="hidden"
              disabled={busy}
              onChange={e => handleUpload(e.target.files)}
            />
          </label>
        </div>
        {hasDiarization && (
          <button
            className="btn-gold w-full text-center mt-2"
            onClick={() => downloadDiarization(chapter)}
            title="Download the labelled chapter (speaker + emotion per line)"
          >↓ Download labelled script</button>
        )}
      </section>

      {results.length > 0 && (
        <div className="mt-3 space-y-1">
          {results.map(r => (
            <p
              key={r.name}
              className={`text-[10px] leading-snug break-words ${r.ok ? 'text-emerald-500' : 'text-blood-text'}`}
            >
              {r.name}: {r.message}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
