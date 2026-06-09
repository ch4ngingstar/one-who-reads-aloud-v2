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
        sans: ['var(--font-sans)', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
        tech: ['var(--font-tech)', 'VT323', 'Courier New', 'monospace'],
      },
      colors: {
        // ── Monochromatic canvas ────────────────────────────────────────────────
        void: '#000000',
        surface: {
          base:    '#000000',   // Pitch black
          raised:  '#050505',
          card:    '#0A0A0A',   // Barely elevated
          overlay: '#121212',   // Dark graphite
        },
        edge: {
          DEFAULT: '#27272A',
          subtle:  'rgba(39,39,42,0.6)',
          bright:  'rgba(39,39,42,1)',
          silver:  'rgba(212,212,216,0.12)',
          gold:    'rgba(251,191,36,0.3)',
          cyan:    'rgba(212,212,216,0.1)',   // alias kept for compat
        },
        ink: {
          primary:   '#F4F4F5',   // Bone White
          secondary: '#D4D4D8',   // Chrome Silver — Active/Done
          muted:     '#52525B',   // Dim Ash Gray — Pending/Inactive
          ghost:     '#3F3F46',   // Near-invisible
        },
        soul: {
          chrome:  '#D4D4D8',   // Active/Done accent
          gold:    '#FBBF24',   // CTA — the only bright color
          crimson: '#991B1B',   // Error/Delete
          ash:     '#52525B',   // Pending/Inactive
          dim:     '#3F3F46',   // Ghost
          deep:    '#000000',
        },
        accent: '#121212',
        dot: {
          pending:  '#3F3F46',   // Ghost dim
          diarized: '#71717A',   // Mid zinc
          tts:      '#71717A',   // Mid zinc
          complete: '#D4D4D8',   // Chrome Silver
          error:    '#991B1B',   // Deep Crimson
          running:  '#A0A0A8',   // Light zinc
        },
      },
      borderWidth: { DEFAULT: '1px' },
      keyframes: {
        'glow-pulse': {
          '0%, 100%': { boxShadow: '0 0 0 0 transparent' },
          '50%':      { boxShadow: '0 0 20px -8px rgba(212,212,216,0.15)' },
        },
        'gold-glow': {
          '0%, 100%': { boxShadow: '0 0 0 0 transparent' },
          '50%':      { boxShadow: '0 0 18px -6px rgba(212,212,216,0.12)' },
        },
        'cyber-aura': {
          '0%, 100%': { boxShadow: '0 0 0 0 transparent' },
          '50%':      { boxShadow: '0 0 28px -10px rgba(212,212,216,0.14), 0 0 60px -20px rgba(212,212,216,0.06)' },
        },
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        'wave': {
          '0%':   { opacity: '0.3' },
          '100%': { opacity: '0.9' },
        },
        'twinkle': {
          '0%, 100%': { opacity: '0.06' },
          '50%':      { opacity: '0.35' },
        },
        'drift': {
          '0%, 100%': { transform: 'translateY(0px) rotate(0deg)' },
          '40%':      { transform: 'translateY(-3px) rotate(6deg)' },
          '70%':      { transform: 'translateY(1px) rotate(-4deg)' },
        },
        'flicker': {
          '0%, 91%, 94%, 97%, 100%': { opacity: '1' },
          '92%, 95%':                { opacity: '0.25' },
          '96%':                     { opacity: '0.6' },
        },
        'thread-pulse': {
          '0%, 100%': { opacity: '0.4' },
          '50%':      { opacity: '0.7' },
        },
      },
      animation: {
        'pulse-slow':   'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        'glow-pulse':   'glow-pulse 2.5s ease-in-out infinite',
        'gold-glow':    'gold-glow 2.5s ease-in-out infinite',
        'cyber-aura':   'cyber-aura 3s ease-in-out infinite',
        'fade-in':      'fade-in 0.2s ease-out',
        'slide-up':     'slide-up 0.25s ease-out',
        'wave':         'wave 0.7s ease-in-out infinite alternate',
        'twinkle':      'twinkle 3s ease-in-out infinite',
        'drift':        'drift 5s ease-in-out infinite',
        'flicker':      'flicker 8s ease-in-out infinite',
        'thread-pulse': 'thread-pulse 4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}

export default config
