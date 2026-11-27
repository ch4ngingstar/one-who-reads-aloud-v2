'use client'
import { useEffect, useState } from 'react'
import { getPronunciations, setPronunciation } from '@/lib/api'

export default function PronunciationEditor() {
  const [rules, setRules] = useState<Record<string, string>>({})
  const [name, setName] = useState('')
  const [reading, setReading] = useState('')
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    getPronunciations().then(values => { if (active) setRules(values) })
      .catch(() => { if (active) setError('Could not load pronunciations.') })
      .finally(() => { if (active) setBusy(false) })
    return () => { active = false }
  }, [])

  async function save(spelling: string, replacement: string) {
    setBusy(true)
    setError('')
    try {
      setRules(await setPronunciation(spelling, replacement))
      setName('')
      setReading('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save pronunciation.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <details className="border-y border-[#292929] py-3">
      <summary className="label cursor-pointer">Name pronunciations</summary>
      <p className="my-3 text-xs text-ink-secondary">Enter how a name should sound in future takes.</p>
      {Object.entries(rules).map(([spelling, value]) => (
        <div key={spelling} className="flex items-center justify-between gap-2 py-1 text-xs">
          <button type="button" onClick={() => { setName(spelling); setReading(value) }}>
            {spelling} → {value}
          </button>
          <button type="button" disabled={busy} aria-label={`Remove pronunciation for ${spelling}`}
            onClick={() => save(spelling, '')}>Remove</button>
        </div>
      ))}
      <form className="mt-2 space-y-2" onSubmit={e => { e.preventDefault(); void save(name.trim(), reading.trim()) }}>
        <input className="input" aria-label="Name in book" placeholder="Name in book"
          required maxLength={100} value={name} onChange={e => setName(e.target.value)} />
        <input className="input" aria-label="Read aloud as" placeholder="Read aloud as"
          required maxLength={150} value={reading} onChange={e => setReading(e.target.value)} />
        <button className="btn text-xs" disabled={busy || !name.trim() || !reading.trim()}>Save pronunciation</button>
      </form>
      {error && <p role="alert" className="mt-2 text-xs text-blood-text">{error}</p>}
    </details>
  )
}
