import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './hooks/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'Consolas', 'monospace'],
        // VT323 retired — `.tech` data values now read in IBM Plex Mono.
        tech: ['var(--font-mono)', 'ui-monospace', 'Consolas', 'monospace'],
        display: ['var(--font-display)', 'Cinzel', 'Georgia', 'serif'],
      },
      colors: {
        // ── Nightmare Spell grayscale ladder (spec §2) ────────────────────
        spell: {
          g0: '#000000', g05: '#0a0a0a', g1: '#111111', g2: '#232323',
          g3: '#343434', g4: '#464646', g5: '#575757', g6: '#696969', g7: '#7a7a7a',
        },
        // Crimson — errors and destructive confirms ONLY (variant A2).
        blood: { DEFAULT: '#8c2731', text: '#b85560', bg: '#150b0c' },
        // Legacy token names kept so reused/old components restyle for free.
        surface: { base: '#000000', raised: '#0a0a0a', card: '#111111', overlay: '#161616' },
        edge: {
          DEFAULT: '#232323',
          subtle:  'rgba(35,35,35,0.6)',
          bright:  '#343434',
          silver:  'rgba(255,255,255,0.12)',
          gold:    'rgba(255,255,255,0.12)',  // alias — gold is retired
          cyan:    'rgba(255,255,255,0.10)',  // alias — kept for compat
        },
        ink: {
          primary:   '#e8e8e8',
          secondary: '#c4c4c4',
          muted:     '#696969',
          ghost:     '#464646',
          hot:       '#ffffff',
        },
        soul: {  // pruned in Task 10 with ChapterGrid; remapped until then
          chrome: '#c4c4c4', gold: '#e8e8e8', crimson: '#8c2731',
          ash: '#696969', dim: '#464646', deep: '#000000',
        },
        accent: '#111111',
        dot: {
          pending:  '#343434',
          diarized: '#575757',
          tts:      '#696969',
          complete: '#c4c4c4',
          error:    '#b85560',
          running:  '#ffffff',
        },
      },
      borderWidth: { DEFAULT: '1px' },
      keyframes: {
        breathe: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0.35' },
        },
        glowpulse: {
          '0%, 100%': { boxShadow: '0 0 26px rgba(255,255,255,0.07), inset 0 0 18px rgba(255,255,255,0.02)' },
          '50%':      { boxShadow: '0 0 48px rgba(255,255,255,0.14), inset 0 0 26px rgba(255,255,255,0.05)' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        twinkle: {
          '0%, 100%': { opacity: '0.06' },
          '50%':      { opacity: '0.35' },
        },
        flicker: {
          '0%, 91%, 94%, 97%, 100%': { opacity: '1' },
          '92%, 95%':                { opacity: '0.75' },
          '96%':                     { opacity: '0.85' },
        },
        'thread-pulse': {
          '0%, 100%': { opacity: '0.4' },
          '50%':      { opacity: '0.7' },
        },
        'toast-in': {
          from: { opacity: '0', transform: 'translateX(16px)' },
          to:   { opacity: '1', transform: 'translateX(0)' },
        },
        equalize: {
          '0%, 100%': { transform: 'scaleY(0.3)' },
          '50%':      { transform: 'scaleY(1)' },
        },
      },
      animation: {
        'pulse-slow':   'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        breathe:        'breathe 2.4s ease-in-out infinite',
        glowpulse:      'glowpulse 3.2s ease-in-out infinite',
        'fade-in':      'fade-in 0.2s ease-out',
        'slide-up':     'slide-up 0.25s ease-out',
        twinkle:        'twinkle 3s ease-in-out infinite',
        flicker:        'flicker 7s ease-in-out infinite',
        'thread-pulse': 'thread-pulse 4s ease-in-out infinite',
        'toast-in':     'toast-in 0.22s ease-out',
        equalize:       'equalize 0.9s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}

export default config
