import {
  ApiError,
  listDocuments,
  uploadDocument,
  type ApiClientConfig,
  type DocumentListResponse,
  type DocumentRecord,
  type UploadDocumentInput,
} from '../../../packages/clients/typescript/src/api'

export const ACCESS_TOKEN_COOKIE = 'rag_access_token'
export const API_BASE_URL_COOKIE = 'rag_api_base_url'
export const DEFAULT_API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? process.env.API_BASE_URL ?? 'http://localhost:8000'

export type WebSession = ApiClientConfig

export function getApiBaseUrl(value?: string | null): string {
  const trimmed = value?.trim()
  return trimmed && trimmed.length > 0 ? trimmed : DEFAULT_API_BASE_URL
}

export function getSessionFromCookieValues(values: {
  token?: string | null
  baseUrl?: string | null
}): WebSession | null {
  const token = values.token?.trim()
  if (!token) {
    return null
  }

  return {
    baseUrl: getApiBaseUrl(values.baseUrl),
    token,
  }
}

export function getAuthCookieNames(): string[] {
  return [ACCESS_TOKEN_COOKIE, API_BASE_URL_COOKIE]
}

export function getReadableErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return 'Your session is missing or expired. Log in again.'
      case 403:
        return 'You do not have permission to view these documents.'
      case 422:
        return 'Upload failed: please check the form fields and selected file.'
      default:
        return error.message
    }
  }

  if (error instanceof Error) {
    return error.message
  }

  return 'Something went wrong while talking to the API.'
}

export async function listDocumentsForSession(
  session: WebSession,
): Promise<DocumentListResponse> {
  return listDocuments(fetch, session)
}

export async function uploadDocumentForSession(
  session: WebSession,
  input: UploadDocumentInput,
): Promise<DocumentRecord> {
  return uploadDocument(fetch, session, input)
}
