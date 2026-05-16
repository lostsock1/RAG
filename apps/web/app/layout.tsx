import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Uber-RAG',
  description: 'API-first, ACL-aware RAG platform',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: 'system-ui, sans-serif', margin: 0 }}>{children}</body>
    </html>
  )
}
