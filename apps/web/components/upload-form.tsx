'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'

import { uploadDocument } from '../../../packages/clients/typescript/src/api'
import { getReadableErrorMessage } from '../lib/api-client'

type UploadFormProps = {
  baseUrl: string
  token: string
}

export function UploadForm({ baseUrl, token }: UploadFormProps) {
  const router = useRouter()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSubmit(formData: FormData) {
    const file = formData.get('file')
    const title = String(formData.get('title') ?? '').trim()
    const sourceType = String(formData.get('sourceType') ?? '').trim()
    const documentType = String(formData.get('documentType') ?? '').trim()
    const language = String(formData.get('language') ?? '').trim()

    if (!(file instanceof File)) {
      setError('Choose a file before uploading.')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await uploadDocument(fetch, { baseUrl, token }, {
        file,
        fileName: file.name,
        title,
        sourceType,
        documentType: documentType || undefined,
        language: language || undefined,
      })
      router.push('/documents')
      router.refresh()
    } catch (uploadError) {
      setError(getReadableErrorMessage(uploadError))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form action={onSubmit} style={{ display: 'grid', gap: '1rem' }}>
      <label style={{ display: 'grid', gap: '.5rem' }}>
        <span>Title</span>
        <input name="title" required disabled={isSubmitting} />
      </label>
      <label style={{ display: 'grid', gap: '.5rem' }}>
        <span>Source type</span>
        <input name="sourceType" defaultValue="loose_document" required disabled={isSubmitting} />
      </label>
      <label style={{ display: 'grid', gap: '.5rem' }}>
        <span>Document type</span>
        <input name="documentType" defaultValue="report" disabled={isSubmitting} />
      </label>
      <label style={{ display: 'grid', gap: '.5rem' }}>
        <span>Language</span>
        <input name="language" placeholder="en" disabled={isSubmitting} />
      </label>
      <label style={{ display: 'grid', gap: '.5rem' }}>
        <span>File</span>
        <input name="file" type="file" required disabled={isSubmitting} />
      </label>
      {error ? (
        <p role="alert" style={{ color: '#b91c1c' }}>
          {error}
        </p>
      ) : null}
      <button type="submit" disabled={isSubmitting}>
        {isSubmitting ? 'Uploading…' : 'Upload'}
      </button>
    </form>
  )
}
