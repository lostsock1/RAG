'use client'

import { useEffect, useState } from 'react'

import { listDocuments, type DocumentRecord } from '../../../packages/clients/typescript/src/api'
import { getReadableErrorMessage } from '../lib/api-client'

type DocumentListProps = {
  baseUrl: string
  token: string
}

export function DocumentList({ baseUrl, token }: DocumentListProps) {
  const [documents, setDocuments] = useState<DocumentRecord[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadDocuments() {
      setStatus('loading')
      setError(null)

      try {
        const response = await listDocuments(fetch, { baseUrl, token })
        if (cancelled) {
          return
        }
        setDocuments(response.items)
        setStatus('ready')
      } catch (loadError) {
        if (cancelled) {
          return
        }
        setError(getReadableErrorMessage(loadError))
        setStatus('error')
      }
    }

    void loadDocuments()

    return () => {
      cancelled = true
    }
  }, [baseUrl, token])

  if (status === 'loading') {
    return <p>Loading documents…</p>
  }

  if (status === 'error') {
    return (
      <p role="alert" style={{ color: '#b91c1c' }}>
        {error}
      </p>
    )
  }

  if (documents.length === 0) {
    return <p>No documents are visible for this account yet.</p>
  }

  return (
    <ul style={{ display: 'grid', gap: '.75rem', padding: 0, listStyle: 'none' }}>
      {documents.map((document) => (
        <li key={document.id} style={{ border: '1px solid #d4d4d8', borderRadius: 8, padding: '1rem' }}>
          <strong>{document.title}</strong>
          <div>Source type: {document.source_type}</div>
          <div>Status: {document.ingestion_status}</div>
          <div>Created: {new Date(document.created_at).toLocaleString()}</div>
        </li>
      ))}
    </ul>
  )
}
