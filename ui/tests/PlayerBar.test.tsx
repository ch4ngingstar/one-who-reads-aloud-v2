import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import PlayerBar from '@/components/PlayerBar'
import type { Chapter } from '@/lib/types'

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id: 1,
    project_id: 1,
    chapter_index: 0,
    title: 'Chapter One',
    status: 'complete',
    total_chunks: 1,
    total_lines: 42,
    output_audio_path: 'data/output/ch_0001.mp3',
    output_file_size_bytes: 1024,
    processing_seconds: 10,
    error_message: null,
    updated_at: '',
    ...overrides,
  }
}

const queue = [
  makeChapter({ id: 1, chapter_index: 0, title: 'Chapter One' }),
  makeChapter({ id: 2, chapter_index: 1, title: 'Chapter Two' }),
]

describe('PlayerBar', () => {
  it('renders nothing when no track is selected', () => {
    const { container } = render(
      <PlayerBar queue={queue} currentId={null} onCurrentChange={() => {}} />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('shows the current chapter title and transport controls', () => {
    render(<PlayerBar queue={queue} currentId={1} onCurrentChange={() => {}} />)
    expect(screen.getByText('Chapter One')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /next chapter/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /previous chapter/i })).toBeDisabled()
  })

  it('advances to the next queue entry via the next button', () => {
    const onCurrentChange = vi.fn()
    render(<PlayerBar queue={queue} currentId={1} onCurrentChange={onCurrentChange} />)
    fireEvent.click(screen.getByRole('button', { name: /next chapter/i }))
    expect(onCurrentChange).toHaveBeenCalledWith(2)
  })

  it('closes via the close button', () => {
    const onCurrentChange = vi.fn()
    render(<PlayerBar queue={queue} currentId={2} onCurrentChange={onCurrentChange} />)
    fireEvent.click(screen.getByRole('button', { name: /close player/i }))
    expect(onCurrentChange).toHaveBeenCalledWith(null)
  })
})
