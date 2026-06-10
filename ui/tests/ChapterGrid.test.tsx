import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ChapterGrid from '@/components/ChapterGrid'
import type { Chapter } from '@/lib/types'

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id: 1,
    project_id: 1,
    chapter_index: 0,
    title: 'Chapter One',
    status: 'pending',
    total_chunks: 1,
    total_lines: 42,
    output_audio_path: null,
    output_file_size_bytes: null,
    processing_seconds: null,
    error_message: null,
    updated_at: '',
    ...overrides,
  }
}

describe('ChapterGrid', () => {
  it('renders chapter title and line count', () => {
    render(<ChapterGrid chapters={[makeChapter()]} activeChapterId={null} />)
    expect(screen.getByText('Chapter One')).toBeInTheDocument()
    expect(screen.getByText('42 lines')).toBeInTheDocument()
  })

  it('shows "Processing" label for the active chapter', () => {
    const ch = makeChapter({ id: 7, status: 'diarized' })
    render(<ChapterGrid chapters={[ch]} activeChapterId={7} />)
    expect(screen.getByText('Processing')).toBeInTheDocument()
  })

  it('strips [failed_stage:X] sentinel from error messages', () => {
    const ch = makeChapter({
      status: 'error',
      error_message: '[failed_stage:synthesize] Fish Speech crashed',
    })
    render(<ChapterGrid chapters={[ch]} activeChapterId={null} />)
    expect(screen.queryByText(/\[failed_stage/)).not.toBeInTheDocument()
    expect(screen.getByText('Fish Speech crashed')).toBeInTheDocument()
  })

  it('shows file size badge for complete chapters', () => {
    const ch = makeChapter({
      status: 'complete',
      output_file_size_bytes: 26_214_400, // 25.0 MB
    })
    render(<ChapterGrid chapters={[ch]} activeChapterId={null} />)
    expect(screen.getByText('25.0 MB')).toBeInTheDocument()
  })

  it('shows Play button for complete chapters with audio and routes to the global player', () => {
    const onPlay = vi.fn()
    const ch = makeChapter({ status: 'complete', output_audio_path: 'data/output/ch_0001.mp3' })
    render(<ChapterGrid chapters={[ch]} activeChapterId={null} onPlay={onPlay} />)
    const btn = screen.getByRole('button', { name: /^play$/i })
    fireEvent.click(btn)
    expect(onPlay).toHaveBeenCalledWith(1)
  })

  it('shows Play All when finished chapters exist and a handler is given', () => {
    const onPlayAll = vi.fn()
    const chapters = [
      makeChapter({ id: 1, status: 'complete', output_audio_path: 'a.mp3' }),
      makeChapter({ id: 2, status: 'pending' }),
    ]
    render(<ChapterGrid chapters={chapters} activeChapterId={null} onPlayAll={onPlayAll} />)
    fireEvent.click(screen.getByRole('button', { name: /play all/i }))
    expect(onPlayAll).toHaveBeenCalledOnce()
  })

  it('filters chapters by status', () => {
    const chapters = [
      makeChapter({ id: 1, title: 'Ch A', status: 'complete' }),
      makeChapter({ id: 2, title: 'Ch B', status: 'error' }),
    ]
    render(<ChapterGrid chapters={chapters} activeChapterId={null} />)

    fireEvent.click(screen.getByRole('button', { name: /^error/i }))

    expect(screen.queryByText('Ch A')).not.toBeInTheDocument()
    expect(screen.getByText('Ch B')).toBeInTheDocument()
  })

  it('shows empty-filter message when no chapters match', () => {
    const ch = makeChapter({ status: 'pending' })
    render(<ChapterGrid chapters={[ch]} activeChapterId={null} />)

    fireEvent.click(screen.getByRole('button', { name: /^error/i }))

    expect(screen.getByText(/no chapters match/i)).toBeInTheDocument()
  })
})
