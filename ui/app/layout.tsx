import type { Metadata } from 'next'
import { Inter, IBM_Plex_Mono, Cinzel } from 'next/font/google'
import './globals.css'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-sans',
  display: 'swap',
})

const plexMono = IBM_Plex_Mono({
  weight: ['400', '500'],
  subsets: ['latin'],
  variable: '--font-mono',
  display: 'swap',
})

// Gothic display serif — wordmark, chapter titles, buttons, tabs.
const cinzel = Cinzel({
  weight: ['500', '700'],
  subsets: ['latin'],
  variable: '--font-display',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'One Who Reads Aloud — Shadow Slave Audiobook',
  description: 'Multi-voice audiobook generation for Shadow Slave',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${plexMono.variable} ${cinzel.variable}`}>
      <body className="bg-surface-base text-ink-primary antialiased min-h-screen font-sans dream-realm">
        {children}
      </body>
    </html>
  )
}
