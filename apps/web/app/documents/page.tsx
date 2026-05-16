import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

import { DocumentList } from '../../components/document-list'
import { getSessionFromCookieValues } from '../../lib/api-client'

export default async function DocumentsPage() {
  const cookieStore = await cookies()
  const session = getSessionFromCookieValues({
    token: cookieStore.get('rag_access_token')?.value,
    baseUrl: cookieStore.get('rag_api_base_url')?.value,
  })

  if (!session) {
    redirect('/login?next=/documents')
  }

  return (
    <main style={{ margin: '2rem auto', maxWidth: 720, padding: '0 1rem' }}>
      <h1>Documents</h1>
      <p>Read-only list backed by GET /api/v1/documents.</p>
      <DocumentList baseUrl={session.baseUrl} token={session.token ?? ''} />
    </main>
  )
}
