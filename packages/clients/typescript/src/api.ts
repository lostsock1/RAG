export type FetchLike = typeof fetch

export type ApiClientConfig = {
  baseUrl: string
  token?: string
}

export type UploadDocumentInput = {
  file: File | Blob
  fileName: string
  title: string
  sourceType: string
  documentType?: string
  language?: string
}

export type DocumentRecord = {
  id: string
  tenant_id: string
  owner_user_id: string
  title: string
  source_type: string
  document_type: string | null
  language: string | null
  source_hash: string
  file_name: string | null
  file_size_bytes: number | null
  object_key: string | null
  ingestion_status: string
  created_at: string
  updated_at: string
}

export type DocumentListResponse = {
  items: DocumentRecord[]
}

export class ApiError extends Error {
  status: number
  body: unknown

  constructor(status: number, body: unknown, fallbackMessage?: string) {
    const message =
      (body as { detail?: string } | null)?.detail ??
      (body as { message?: string } | null)?.message ??
      fallbackMessage ??
      `API request failed with status ${status}`
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl
}

async function readErrorBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get('content-type') ?? ''

  if (contentType.includes('application/json')) {
    return response.json().catch(() => null)
  }

  const text = await response.text().catch(() => '')
  return text || null
}

async function request<T>(
  fetchImpl: FetchLike,
  config: ApiClientConfig,
  path: string,
  init: RequestInit,
): Promise<T> {
  const headers = new Headers(init.headers)

  if (config.token) {
    headers.set('Authorization', `Bearer ${config.token}`)
  }

  const response = await fetchImpl(`${normalizeBaseUrl(config.baseUrl)}${path}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    const body = await readErrorBody(response)
    throw new ApiError(response.status, body)
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export async function listDocuments(
  fetchImpl: FetchLike,
  config: ApiClientConfig,
): Promise<DocumentListResponse> {
  return request<DocumentListResponse>(fetchImpl, config, '/api/v1/documents', {
    method: 'GET',
  })
}

export async function uploadDocument(
  fetchImpl: FetchLike,
  config: ApiClientConfig,
  input: UploadDocumentInput,
): Promise<DocumentRecord> {
  const formData = new FormData()
  const file = input.file instanceof File ? input.file : new File([input.file], input.fileName)

  formData.set('title', input.title)
  formData.set('source_type', input.sourceType)
  if (input.documentType) {
    formData.set('document_type', input.documentType)
  }
  if (input.language) {
    formData.set('language', input.language)
  }
  formData.set('file', file, input.fileName)

  return request<DocumentRecord>(fetchImpl, config, '/api/v1/documents/upload', {
    method: 'POST',
    body: formData,
  })
}
