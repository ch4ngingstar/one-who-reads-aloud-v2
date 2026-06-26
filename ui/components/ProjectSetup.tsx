'use client'
import { useState, useEffect } from 'react'
import { createProject } from '@/lib/api'
import type { Project, Progress, GenOptions } from '@/lib/types'

const OUTPUT_FORMATS = ['mp3', 'wav', 'flac', 'ogg'] as const

interface Props {
  initialEpub: string; initialLlm: string
  initialTtsDir: string; initialSpeakers: string
  onCreated: (
    project: Project, progress: Progress,
    llmPath: string, ttsDir: string, speakers: string[], options: GenOptions,
    epubPath: string,
  ) => void
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <label className="label">{label}</label>
        {hint && <span className="text-[9px] text-ink-ghost">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

export default function ProjectSetup({ initialEpub, initialLlm, initialTtsDir, initialSpeakers, onCreated }: Props) {
  // epub: "remembered" uses the last-saved path; "new" shows an editable input
  const [epubMode,    setEpubMode]    = useState<'remembered' | 'new'>(initialEpub ? 'remembered' : 'new')
  const [newEpubPath, setNewEpubPath] = useState('')
  const [llmPath,  setLlmPath]  = useState(initialLlm)
  const [ttsDir,   setTtsDir]   = useState(initialTtsDir)
  const [speakers, setSpeakers] = useState(initialSpeakers)
  const [rangeStart, setRangeStart] = useState('')   // 1-based, matches the chapter grid; empty = whole book
  const [rangeEnd,   setRangeEnd]   = useState('')
  const [outputFormat, setOutputFormat] = useState<string>('mp3')
  const [vramCheck,    setVramCheck]    = useState(true)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  // When the parent loads a remembered epub from localStorage, switch to remembered mode
  // (only if the user hasn't already typed something in the new-path input)
  useEffect(() => { if (initialEpub && !newEpubPath) setEpubMode('remembered') }, [initialEpub])
  useEffect(() => { setLlmPath(initialLlm) },       [initialLlm])
  useEffect(() => { setTtsDir(initialTtsDir) },     [initialTtsDir])
  useEffect(() => { setSpeakers(initialSpeakers) }, [initialSpeakers])

  const effectiveEpub = epubMode === 'remembered' ? initialEpub : newEpubPath
  const epubFilename  = initialEpub.split(/[\\/]/).pop() ?? initialEpub

  /** Build the 0-based [start, end] chapter_index range from the 1-based form inputs. */
  function resolveChapterRange(): [number, number] | null {
    const s = rangeStart.trim(), e = rangeEnd.trim()
    if (!s && !e) return null   // whole book
    const start = s ? parseInt(s, 10) : 1
    const end   = e ? parseInt(e, 10) : start
    if (!Number.isFinite(start) || !Number.isFinite(end)) throw new Error('Chapter range must be whole numbers')
    if (start < 1 || end < 1) throw new Error('Chapter numbers start at 1')
    if (start > end) throw new Error('Chapter range: "From" must be ≤ "To"')
    return [start - 1, end - 1]   // → 0-based chapter_index, inclusive
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setError(null); setLoading(true)
    try {
      const epub = effectiveEpub.trim()
      if (!epub) { setError('EPUB path is required'); setLoading(false); return }
      const speakerList = speakers.split(',').map(s => s.trim()).filter(Boolean)
      const chapterRange = resolveChapterRange()   // throws on invalid input → caught below
      const result = await createProject({
        epub_path: epub, llm_model_path: llmPath.trim(),
        tts_model_dir: ttsDir.trim(), speakers: speakerList,
      })
      onCreated(result.project, result.progress, llmPath.trim(), ttsDir.trim(), speakerList, {
        chapterRange, outputFormat, vramCheck,
      }, epub)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally { setLoading(false) }
  }

  const speakerList = speakers.split(',').map(s => s.trim()).filter(Boolean)

  return (
    <form onSubmit={handleSubmit} className="space-y-5">

      {/* Section header */}
      <div className="flex items-center gap-3">
        <span className="label">Project Setup</span>
        <div className="flex-1 weaver-thread" />
      </div>

      {/* Source EPUB — shows remembered path by default; "Change" to enter a new one */}
      <Field label="EPUB Path">
        {epubMode === 'remembered' ? (
          <div className="flex items-center gap-2">
            <div
              className="input flex-1 text-ink-ghost truncate cursor-default select-none"
              title={initialEpub}
            >
              {epubFilename}
            </div>
            <button
              type="button"
              className="text-[11px] text-ink-ghost hover:text-ink-primary underline shrink-0"
              onClick={() => { setEpubMode('new'); setNewEpubPath('') }}
            >
              Change
            </button>
          </div>
        ) : (
          <div className="space-y-1.5">
            <input
              className="input"
              placeholder="data/input/shadow_slave.epub"
              value={newEpubPath}
              onChange={e => setNewEpubPath(e.target.value)}
              required
              spellCheck={false}
              autoFocus={Boolean(initialEpub)}
            />
            {initialEpub && (
              <button
                type="button"
                className="text-[11px] text-ink-ghost hover:text-ink-primary underline"
                onClick={() => setEpubMode('remembered')}
              >
                ← Use remembered: {epubFilename}
              </button>
            )}
          </div>
        )}
      </Field>

      <div className="divider" />

      {/* Model paths */}
      <Field label="LLM Model" hint=".gguf">
        <input
          className="input"
          placeholder="models/Qwen3-14B-Q4_K_M.gguf"
          value={llmPath}
          onChange={e => setLlmPath(e.target.value)}
          required
          spellCheck={false}
        />
      </Field>

      <Field label="IndexTTS2 Model Dir" hint="checkpoints">
        <input
          className="input"
          placeholder="index-tts/checkpoints"
          value={ttsDir}
          onChange={e => setTtsDir(e.target.value)}
          required
          spellCheck={false}
        />
      </Field>

      <div className="divider" />

      {/* Speakers */}
      <Field label="Speakers" hint="comma-separated">
        <input
          className="input"
          value={speakers}
          onChange={e => setSpeakers(e.target.value)}
          spellCheck={false}
          placeholder="Sunny, Nephis, Cassie…"
        />
        {/* Speaker chips */}
        {speakerList.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {speakerList.map(s => (
              <span key={s} className="chip">{s}</span>
            ))}
          </div>
        )}
      </Field>

      <div className="divider" />

      {/* Generation options */}
      <div className="flex items-center gap-3">
        <span className="label">Generation</span>
        <div className="flex-1 weaver-thread" />
      </div>

      {/* Chapter range — 1-based, matches the chapter grid; blank = whole book */}
      <Field label="Chapter Range" hint="optional · whole book if blank">
        <div className="flex items-center gap-2">
          <input
            className="input"
            type="number"
            min={1}
            placeholder="From"
            value={rangeStart}
            onChange={e => setRangeStart(e.target.value)}
            spellCheck={false}
          />
          <span className="text-ink-ghost text-[11px] select-none">→</span>
          <input
            className="input"
            type="number"
            min={1}
            placeholder="To"
            value={rangeEnd}
            onChange={e => setRangeEnd(e.target.value)}
            spellCheck={false}
          />
        </div>
      </Field>

      {/* Output format */}
      <Field label="Output Format" hint="assembled audio">
        <select
          className="input"
          value={outputFormat}
          onChange={e => setOutputFormat(e.target.value)}
        >
          {OUTPUT_FORMATS.map(f => (
            <option key={f} value={f}>{f.toUpperCase()}</option>
          ))}
        </select>
      </Field>

      {/* VRAM barrier toggle */}
      <label className="flex items-center gap-2.5 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={vramCheck}
          onChange={e => setVramCheck(e.target.checked)}
          className="w-3.5 h-3.5 accent-[#FBBF24] cursor-pointer"
        />
        <span className="text-[11px] text-ink-secondary">VRAM barrier between LLM &amp; TTS</span>
      </label>

      {/* Error */}
      {error && (
        <div
          className="px-4 py-3 text-xs text-[#991B1B] animate-slide-up"
          style={{ background: 'rgba(153,27,27,0.06)', border: '1px solid rgba(153,27,27,0.25)' }}
        >
          {error}
        </div>
      )}

      {/* Submit */}
      <button type="submit" className="btn-primary w-full py-2.5 mt-2" disabled={loading}>
        {loading ? (
          <span className="flex items-center gap-2">
            <span className="animate-pulse">◈</span> Initializing…
          </span>
        ) : '▶ Initialize & Start'}
      </button>
    </form>
  )
}
