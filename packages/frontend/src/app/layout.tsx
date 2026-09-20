import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Roofer — inwentaryzacja dachów azbestowych',
  description: 'Zaznacz obszar na mapie i sprawdź status azbestu dla budynków.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pl">
      <body>{children}</body>
    </html>
  )
}
