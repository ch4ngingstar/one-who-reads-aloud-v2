import { describe, it, expect } from 'vitest'
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

  it('shows Preview button for complete chapters with audio', () => {
    const ch = makeChapter({ status: 'complete', output_audio_path: 'data/output/ch_0001.mp3' })
    render(<ChapterGrid chapters={[ch]} activeChapterId={null} />)
    expect(screen.getByRole('button', { name: /preview/i })).toBeInTheDocument()
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
