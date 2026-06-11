import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ChapterQueue from '@/components/ChapterQueue'
import type { Chapter } from '@/lib/types'

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id: 1, project_id: 1, chapter_index: 0, title: 'Chapter One',
    status: 'pending', total_chunks: 1, total_lines: 44,
    output_audio_path: null, output_file_size_bytes: null,
    processing_seconds: null, error_message: null, updated_at: '',
    ...overrides,
  }
}

const chapters = [
  makeChapter({ id: 1, chapter_index: 0, title: 'What Lies Beneath', status: 'complete', output_audio_path: 'x.mp3', output_file_size_bytes: 24_200_000 }),
  makeChapter({ id: 2, chapter_index: 1, title: 'Cold Light', status: 'error', error_message: '[failed_stage:synthesize] CUDA OOM at line 31' }),
  makeChapter({ id: 3, chapter_index: 2, title: 'Sleepless', status: 'pending' }),
]

const base = {
  chapters,
  activeChapterId: null,
  activeStage: null,
  ttsProgress: {},
  selectedId: null,
  onSelect: vi.fn(),
  playingChapterId: null,
  playerPlaying: false,
  onPlay: vi.fn(),
  onChanged: vi.fn(),
}

describe('ChapterQueue', () => {
  it('renders one row per chapter with status sub-lines', () => {
    render(<ChapterQueue {...base} />)
    expect(screen.getByText('What Lies Beneath')).toBeInTheDocument()
    expect(screen.getByText(/23\.1 MB/)).toBeInTheDocument()
    expect(screen.getByText(/Failed at synthesize/)).toBeInTheDocument()
    expect(screen.getByText(/CUDA OOM/)).toBeInTheDocument()
  })

  it('filters to failed chapters', () => {
    render(<ChapterQueue {...base} />)
    fireEvent.click(screen.getByRole('button', { name: /failed/i }))
    expect(screen.getByText('Cold Light')).toBeInTheDocument()
    expect(screen.queryByText('Sleepless')).not.toBeInTheDocument()
  })

  it('searches by title', () => {
    render(<ChapterQueue {...base} />)
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'sleep' } })
    expect(screen.getByText('Sleepless')).toBeInTheDocument()
    expect(screen.queryByText('Cold Light')).not.toBeInTheDocument()
  })

  it('shows live synthesis progress on the running row', () => {
    render(<ChapterQueue
      {...base}
      activeChapterId={3}
      activeStage="synthesize"
      ttsProgress={{ 3: { done: 27, total: 44 } }}
    />)
    expect(screen.getByText(/27\s*∕\s*44/)).toBeInTheDocument()
  })

  it('routes play to the global player and selection to the inspector', () => {
    const onPlay = vi.fn(); const onSelect = vi.fn()
    render(<ChapterQueue {...base} onPlay={onPlay} onSelect={onSelect} />)
    fireEvent.click(screen.getByText('Sleepless'))
    expect(onSelect).toHaveBeenCalledWith(3)
    fireEvent.click(screen.getByRole('button', { name: /play chapter 1/i }))
    expect(onPlay).toHaveBeenCalledWith(1)
  })
})
