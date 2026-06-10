import type { Metadata } from 'next'
import { Inter, VT323, Space_Mono, Cinzel } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
})

const vt323 = VT323({
  weight: '400',
  subsets: ['latin'],
  variable: '--font-tech',
  display: 'swap',
})

const spaceMono = Space_Mono({
  weight: ['400', '700'],
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

// Dark-fantasy display serif — used only for the Shadow Slave wordmark and
// large atmospheric text, never for dense tool UI.
const cinzel = Cinzel({
  weight: ['400', '600'],
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'Shadow Slave — Audiobook Pipeline',
  description: 'Shadow Slave — multi-voice audiobook generation',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${vt323.variable} ${spaceMono.variable} ${cinzel.variable}`}>
      <body className="bg-surface-base text-ink-primary antialiased min-h-screen font-sans dream-realm">
        {children}
      </body>
    </html>
  )
}
