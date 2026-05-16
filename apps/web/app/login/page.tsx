import { cookies } from 'next/headers'
import { redirect } from 'next/navigation'

import {
  ACCESS_TOKEN_COOKIE,
  API_BASE_URL_COOKIE,
  DEFAULT_API_BASE_URL,
} from '../../lib/api-client'

type LoginPageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const resolvedSearchParams = (await searchParams) ?? {}
  const nextParam = resolvedSearchParams.next
  const nextPath = typeof nextParam === 'string' && nextParam.startsWith('/') ? nextParam : '/documents'

  async function login(formData: FormData) {
    'use server'

    const token = String(formData.get('token') ?? '').trim()
    const baseUrl = String(formData.get('baseUrl') ?? '').trim() || DEFAULT_API_BASE_URL

    if (!token) {
      redirect('/login?error=missing-token')
    }

    const cookieStore = await cookies()
    cookieStore.set(ACCESS_TOKEN_COOKIE, token, {
      httpOnly: true,
      sameSite: 'lax',
      secure: false,
      path: '/',
    })
    cookieStore.set(API_BASE_URL_COOKIE, baseUrl, {
      httpOnly: true,
      sameSite: 'lax',
      secure: false,
      path: '/',
    })

    redirect(nextPath)
  }

  const error = resolvedSearchParams.error === 'missing-token'

  return (
    <main style={{ margin: '2rem auto', maxWidth: 480, padding: '0 1rem' }}>
      <h1>Log in</h1>
      <p>Enter an API bearer token and optional API base URL for the public Uber-RAG API.</p>
      {error ? (
        <p role="alert" style={{ color: '#b91c1c' }}>
          A token is required before you can use upload or documents.
        </p>
      ) : null}
      <form action={login} style={{ display: 'grid', gap: '1rem' }}>
        <input type="hidden" name="next" value={nextPath} />
        <label style={{ display: 'grid', gap: '.5rem' }}>
          <span>API base URL</span>
          <input name="baseUrl" type="url" defaultValue={DEFAULT_API_BASE_URL} />
        </label>
        <label style={{ display: 'grid', gap: '.5rem' }}>
          <span>Bearer token</span>
          <textarea name="token" rows={6} required placeholder="Paste a token for the public API" />
        </label>
        <button type="submit">Continue</button>
      </form>
    </main>
  )
}
