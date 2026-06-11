import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import CommandStrip from '@/components/CommandStrip'
import type { Progress } from '@/lib/types'

const progress: Progress = {
  total: 2190, pending: 339, diarized: 0, tts_done: 0, assembled: 0,
  complete: 1849, error: 1, pct_complete: 84,
}

const base = {
  connected: true,
  progress,
  activeStage: null,
  eta: '~4h 12m left',
  vramMb: 7900,
  onStart: vi.fn(), onPause: vi.fn(), onResume: vi.fn(), onStop: vi.fn(),
}

describe('CommandStrip', () => {
  it('shows RUN when startable and chapter counts', () => {
    render(<CommandStrip {...base} pipeStatus="idle" canStart />)
    expect(screen.getByRole('button', { name: /run/i })).toBeEnabled()
    expect(screen.getByText('1849')).toBeInTheDocument()
    expect(screen.getByText(/2190/)).toBeInTheDocument()
  })

  it('shows PAUSE and STOP while running, with the stage label', () => {
    render(<CommandStrip {...base} pipeStatus="running" activeStage="synthesize" canStart={false} />)
    expect(screen.getByRole('button', { name: /pause/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument()
    expect(screen.getByText(/synthesizing/i)).toBeInTheDocument()
  })

  it('shows LINK SEVERED when running but disconnected', () => {
    render(<CommandStrip {...base} pipeStatus="running" connected={false} canStart={false} />)
    expect(screen.getByText(/link severed/i)).toBeInTheDocument()
  })

  it('shows RESUME while paused', () => {
    render(<CommandStrip {...base} pipeStatus="paused" canStart={false} />)
    expect(screen.getByRole('button', { name: /resume/i })).toBeInTheDocument()
  })
})
