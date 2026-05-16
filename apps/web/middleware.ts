import { NextResponse, type NextRequest } from 'next/server'

import { ACCESS_TOKEN_COOKIE } from './lib/api-client'

const PROTECTED_PATHS = ['/upload', '/documents']

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl
  const isProtectedPath = PROTECTED_PATHS.some(
    (protectedPath) => pathname === protectedPath || pathname.startsWith(`${protectedPath}/`),
  )

  if (!isProtectedPath) {
    return NextResponse.next()
  }

  if (request.cookies.get(ACCESS_TOKEN_COOKIE)?.value) {
    return NextResponse.next()
  }

  const loginUrl = new URL('/login', request.url)
  loginUrl.searchParams.set('next', pathname)
  return NextResponse.redirect(loginUrl)
}

export const config = {
  matcher: ['/upload', '/documents'],
}
