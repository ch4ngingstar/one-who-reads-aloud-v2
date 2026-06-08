'use client'
import { useState, useEffect } from 'react'
import { createProject } from '@/lib/api'
import type { Project, Progress } from '@/lib/types'

interface Props {
  initialEpub: string; initialLlm: string
  initialFish: string; initialSpeakers: string
  onCreated: (project: Project, progress: Progress, llmPath: string, fishDir: string, speakers: string[]) => void
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

export default function ProjectSetup({ initialEpub, initialLlm, initialFish, initialSpeakers, onCreated }: Props) {
  const [epubPath, setEpubPath] = useState(initialEpub)
  const [llmPath,  setLlmPath]  = useState(initialLlm)
  const [fishDir,  setFishDir]  = useState(initialFish)
  const [speakers, setSpeakers] = useState(initialSpeakers)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState<string | null>(null)

  useEffect(() => { setEpubPath(initialEpub) },     [initialEpub])
  useEffect(() => { setLlmPath(initialLlm) },       [initialLlm])
  useEffect(() => { setFishDir(initialFish) },      [initialFish])
  useEffect(() => { setSpeakers(initialSpeakers) }, [initialSpeakers])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault(); setError(null); setLoading(true)
    try {
      const speakerList = speakers.split(',').map(s => s.trim()).filter(Boolean)
      const result = await createProject({
        epub_path: epubPath.trim(), llm_model_path: llmPath.trim(),
        fish_speech_dir: fishDir.trim(), speakers: speakerList,
      })
      onCreated(result.project, result.progress, llmPath.trim(), fishDir.trim(), speakerList)
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

      {/* Source EPUB */}
      <Field label="EPUB Path">
        <input
          className="input"
          placeholder="data/input/shadow_slave.epub"
          value={epubPath}
          onChange={e => setEpubPath(e.target.value)}
          required
          spellCheck={false}
        />
      </Field>

      <div className="divider" />

      {/* Model paths */}
      <Field label="LLM Model" hint=".gguf">
        <input
          className="input"
          placeholder="models/qwen2.5-14b-instruct-q4_k_m-00001-of-00003.gguf"
          value={llmPath}
          onChange={e => setLlmPath(e.target.value)}
          required
          spellCheck={false}
        />
      </Field>

      <Field label="Fish Speech Directory">
        <input
          className="input"
          placeholder="fish-speech"
          value={fishDir}
          onChange={e => setFishDir(e.target.value)}
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
