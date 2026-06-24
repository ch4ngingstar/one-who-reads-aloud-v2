import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import InspectorPanel from '@/components/InspectorPanel'
import type { Chapter } from '@/lib/types'

function makeChapter(overrides: Partial<Chapter> = {}): Chapter {
  return {
    id: 1, project_id: 1, chapter_index: 1849, title: 'The Throne of Bone',
    status: 'pending', total_chunks: 6, total_lines: 44,
    output_audio_path: null, output_file_size_bytes: null,
    processing_seconds: null, error_message: null, updated_at: '',
    ...overrides,
  }
}

const base = {
  tab: 'inspector' as const,
  onTabChange: vi.fn(),
  running: false,
  activeChapter: null,
  activeStage: null,
  liveLine: null,
  ttsProg: null,
  selectedChapter: null,
  onPlay: vi.fn(),
  onChanged: vi.fn(),
  voices: [],
  onVoicesUpdate: vi.fn(),
  forge: <div data-testid="forge-content" />,
  events: [],
  onClearLog: vi.fn(),
}

describe('InspectorPanel', () => {
  it('switches tabs', () => {
    const onTabChange = vi.fn()
    render(<InspectorPanel {...base} onTabChange={onTabChange} />)
    fireEvent.click(screen.getByRole('button', { name: /forge/i }))
    expect(onTabChange).toHaveBeenCalledWith('forge')
  })

  it('renders the live stage while synthesizing', () => {
    render(<InspectorPanel
      {...base}
      running
      activeChapter={makeChapter()}
      activeStage="synthesize"
      liveLine={{ text: 'Sunny narrowed his eyes…', speaker: 'Sunny', emotion: 'tense' }}
      ttsProg={{ done: 27, total: 44 }}
    />)
    expect(screen.getByText(/The Throne of Bone/)).toBeInTheDocument()
    expect(screen.getByText(/Sunny narrowed his eyes/)).toBeInTheDocument()
    expect(screen.getByText('Sunny')).toBeInTheDocument()
    expect(screen.getByText('tense')).toBeInTheDocument()
    expect(screen.getByText(/61%/)).toBeInTheDocument()
  })

  it('shows the full error and retry for a failed selected chapter', () => {
    render(<InspectorPanel
      {...base}
      selectedChapter={makeChapter({ status: 'error', error_message: '[failed_stage:synthesize] CUDA OOM at line 31' })}
    />)
    expect(screen.getByText(/CUDA OOM at line 31/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /retry chapter/i })).toBeInTheDocument()
  })

  it('renders the forge slot on the forge tab', () => {
    render(<InspectorPanel {...base} tab="forge" />)
    expect(screen.getByTestId('forge-content')).toBeInTheDocument()
  })

  it('prompts to pick a chapter on the diarize tab when none is selected', () => {
    render(<InspectorPanel {...base} tab="diarize" selectedChapter={null} />)
    expect(screen.getByText(/select a chapter to diarize/i)).toBeInTheDocument()
  })

  it('shows the cloud diarization action on the diarize tab for a selected chapter', () => {
    render(<InspectorPanel {...base} tab="diarize" selectedChapter={makeChapter()} />)
    expect(screen.getByText(/cloud diarization/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /diarize this chapter/i })).toBeInTheDocument()
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('offers Claude, OpenAI and Gemini as diarization providers', () => {
    render(<InspectorPanel {...base} tab="diarize" selectedChapter={makeChapter()} />)
    const select = screen.getByRole('combobox') as HTMLSelectElement
    const values = Array.from(select.options).map(o => o.value)
    expect(values).toEqual(['claude', 'openai', 'gemini'])
  })
})
