import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AudiobookExport from '@/components/AudiobookExport'
import * as api from '@/lib/api'

vi.mock('@/lib/api', () => ({
  getAudiobookExport: vi.fn(),
  startAudiobookExport: vi.fn(),
  audiobookFileUrl: (id: number) => `/api/projects/${id}/audiobook/file`,
}))

const getJob = vi.mocked(api.getAudiobookExport)
const startJob = vi.mocked(api.startAudiobookExport)

describe('AudiobookExport', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts an export and shows it running', async () => {
    getJob.mockResolvedValue({ state: 'idle', project: 2 })
    startJob.mockResolvedValue({ state: 'running', project: 2 })
    render(<AudiobookExport projectId={2} finished={10} />)
    const button = await screen.findByRole('button', { name: /export audiobook/i })
    fireEvent.click(button)
    await waitFor(() => expect(startJob).toHaveBeenCalledWith(2))
    expect(await screen.findByRole('button', { name: /exporting audiobook/i })).toBeDisabled()
  })

  it('offers the finished file with what it contains', async () => {
    getJob.mockResolvedValue({ state: 'done', project: 2, chapters: 348, hours: 58.2, missing: 74 })
    render(<AudiobookExport projectId={2} finished={348} />)
    const link = await screen.findByRole('link', { name: /download/i })
    expect(link).toHaveAttribute('href', '/api/projects/2/audiobook/file')
    expect(link.textContent).toMatch(/348 chapters, 58.2 h, 74 unfinished left out/)
  })

  it('cannot export before any chapter is finished, and shows errors', async () => {
    getJob.mockResolvedValue({ state: 'error', project: 2, error: 'No finished chapters to export yet' })
    render(<AudiobookExport projectId={2} finished={0} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('No finished chapters')
    expect(screen.getByRole('button', { name: /export audiobook/i })).toBeDisabled()
  })
})
