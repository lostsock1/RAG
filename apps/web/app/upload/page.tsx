import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

import { getSessionFromCookieValues } from '../../lib/api-client'
import { UploadForm } from '../../components/upload-form'

export default async function UploadPage() {
  const cookieStore = await cookies()
  const session = getSessionFromCookieValues({
    token: cookieStore.get('rag_access_token')?.value,
    baseUrl: cookieStore.get('rag_api_base_url')?.value,
  })

  if (!session) {
    redirect('/login?next=/upload')
  }

  return (
    <main style={{ margin: '2rem auto', maxWidth: 720, padding: '0 1rem' }}>
      <h1>Upload document</h1>
      <p>Upload a file through the public API.</p>
      <UploadForm baseUrl={session.baseUrl} token={session.token ?? ''} />
    </main>
  )
}
