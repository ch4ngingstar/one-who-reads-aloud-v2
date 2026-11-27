import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import InspectorPanel from '@/components/InspectorPanel'
import * as api from '@/lib/api'
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
  it('shows the source cue that supports an explicit speaker assignment', async () => {
    const getLines = vi.spyOn(api, 'getLines').mockResolvedValue({ total: 2, lines: [
      { id: 1, line_index: 0, speaker: 'Jet', text: 'Wait—', emotion: 'neutral', status: 'pending',
        audio_path: null, error_message: null, attribution: { method: 'explicit', cue_indices: [1] } },
      { id: 2, line_index: 1, speaker: 'Narrator', text: 'Jet said.', emotion: 'neutral', status: 'pending',
        audio_path: null, error_message: null },
    ] })
    try {
      render(<InspectorPanel {...base} selectedChapter={makeChapter({ status: 'diarized' })} />)
      fireEvent.click(await screen.findByText('Speaker attribution'))
      expect(screen.getByText('Explicit attribution in the book')).toBeInTheDocument()
      expect(screen.getByText('Cue 2 · Jet said.')).toBeInTheDocument()
    } finally {
      getLines.mockRestore()
    }
  })
  it('lists only flagged lines on request and clears a flag when the speaker is confirmed', async () => {
    const getLines = vi.spyOn(api, 'getLines').mockResolvedValue({ total: 2, lines: [
      { id: 1, line_index: 0, speaker: 'Kim', text: 'Welcome.', emotion: 'neutral', status: 'pending',
        audio_path: null, error_message: null,
        review_reason: 'Speaker unsure: a second opinion picked June instead of Kim.',
        attribution: { method: 'qwen-v1:agree', cue_indices: [], votes: ['Kim', 'Kim'], voice_as: 'The Bureaucrat' } },
      { id: 2, line_index: 1, speaker: 'Narrator', text: 'She nodded.', emotion: 'neutral', status: 'pending',
        audio_path: null, error_message: null },
    ] })
    const confirm = vi.spyOn(api, 'confirmSpeaker').mockResolvedValue({})
    try {
      render(<InspectorPanel {...base} selectedChapter={makeChapter({ status: 'diarized' })} />)
      fireEvent.click(await screen.findByRole('button', { name: 'Needs review · 1' }))
      expect(screen.queryByText('She nodded.')).not.toBeInTheDocument()
      fireEvent.click(screen.getByText('Speaker attribution'))
      expect(screen.getByText('Local labeller: Both independent votes agreed (votes: Kim, Kim)')).toBeInTheDocument()
      expect(screen.getByText('No cast voice yet: voiced by The Bureaucrat.')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Kim is right for line 1' }))
      expect(confirm).toHaveBeenCalledWith(1, 0)
      expect(await screen.findByRole('button', { name: 'Show all lines' })).toBeInTheDocument()
      expect(screen.queryByText(/second opinion picked June/)).not.toBeInTheDocument()
      expect(screen.getByText('Every flagged line in this chapter has been checked.')).toBeInTheDocument()
    } finally {
      getLines.mockRestore()
      confirm.mockRestore()
    }
  })
  it('starts the selected chapter with the renderer chosen in Inspector', () => {
    const chapter = makeChapter({ status: 'complete' })
    const renderChapter = vi.fn().mockResolvedValue(undefined)
    render(<InspectorPanel {...base} selectedChapter={chapter} renderChapter={renderChapter}
      currentRenderer="index" renderers={[{ name: 'Index', path: 'index' }, { name: 'Directed cast', path: 'cast' }]} />)
    fireEvent.change(screen.getByLabelText('Chapter speech renderer'), { target: { value: 'cast' } })
    fireEvent.click(screen.getByRole('button', { name: 'Render this chapter' }))
    expect(renderChapter).toHaveBeenCalledWith(chapter, 'cast')
  })
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
