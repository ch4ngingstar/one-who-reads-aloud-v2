import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ProjectSetup from '@/components/ProjectSetup'

// Stub the API so submit doesn't hit the network.
vi.mock('@/lib/api', () => ({
  createProject: vi.fn(async () => ({
    project:  { id: 1, name: 'shadow_slave', source_epub: 'x.epub', created_at: '' },
    progress: { total: 1, complete: 0, error: 0, pending: 1 },
  })),
}))

const baseProps = {
  initialEpub: 'C:/books/shadow_slave.epub',
  initialLlm: 'model.gguf',
  initialTtsDir: 'index-tts/checkpoints',
  initialSpeakers: 'Sunny, Nephis',
}

describe('ProjectSetup sound-design controls', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts with the chosen installed renderer and restored chapter range', async () => {
    const onCreated = vi.fn()
    render(<ProjectSetup {...baseProps} onCreated={onCreated} initialRange={[2, 2]}
      models={{ llm: [], tts: [{ name: 'IndexTTS 2.5', path: '/new/checkpoints' }] }} />)
    fireEvent.change(screen.getByRole('combobox', { name: 'Installed speech renderer' }),
      { target: { value: '/new/checkpoints' } })
    fireEvent.click(screen.getByRole('button', { name: /initialize & start/i }))
    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    expect(onCreated.mock.calls[0][3]).toBe('/new/checkpoints')
    // The range is the book's own chapter numbers now; the server maps them to positions.
    expect(onCreated.mock.calls[0][5].chapterNumbers).toEqual([2, 2])
  })

  it('reveals the three category toggles only when sound design is enabled', () => {
    render(<ProjectSetup {...baseProps} onCreated={vi.fn()} />)

    // Hidden until the master switch is on.
    expect(screen.queryByRole('checkbox', { name: /ambience beds/i })).toBeNull()

    fireEvent.click(screen.getByRole('checkbox', { name: /sound design/i }))

    // All three appear and default to checked.
    for (const name of [/ambience beds/i, /sound effects/i, /^music$/i]) {
      const cb = screen.getByRole('checkbox', { name }) as HTMLInputElement
      expect(cb.checked).toBe(true)
    }
  })

  it('emits only the selected categories in GenOptions', async () => {
    const onCreated = vi.fn()
    render(<ProjectSetup {...baseProps} onCreated={onCreated} />)

    fireEvent.click(screen.getByRole('checkbox', { name: /sound design/i }))
    fireEvent.click(screen.getByRole('checkbox', { name: /^music$/i })) // uncheck music

    fireEvent.click(screen.getByRole('button', { name: /initialize & start/i }))

    await waitFor(() => expect(onCreated).toHaveBeenCalled())
    const opts = onCreated.mock.calls[0][5]   // GenOptions is the 6th arg
    expect(opts.sfxEnabled).toBe(true)
    expect(opts.sfxCategories).toEqual(['ambience', 'sfx'])
  })
})
