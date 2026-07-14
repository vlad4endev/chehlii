// API-клиент админки. Токен — в localStorage, добавляется в Authorization.
const BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api/v1'
const TOKEN_KEY = 'chehlii:admin:token'

export type Role = 'admin' | 'designer'

export interface AdminUser {
  id: number
  email: string
  full_name: string | null
  role: Role
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

function headers(): Record<string, string> {
  const t = getToken()
  return t ? { 'Content-Type': 'application/json', Authorization: `Bearer ${t}` } : { 'Content-Type': 'application/json' }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `Ошибка ${res.status}`
    try {
      const body = await res.json()
      if (body?.detail) detail = String(body.detail)
    } catch {
      /* нет тела */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

export const apiUrl = (path: string): string => `${BASE}${path}`

export async function apiGet<T>(path: string): Promise<T> {
  return handle<T>(await fetch(`${BASE}${path}`, { headers: headers() }))
}
export async function apiSend<T>(method: string, path: string, body?: unknown): Promise<T> {
  return handle<T>(
    await fetch(`${BASE}${path}`, {
      method,
      headers: headers(),
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  )
}

// ── Аутентификация ─────────────────────────────────────
interface LoginOut {
  access_token: string
  role: Role
  full_name: string | null
}

export async function login(email: string, password: string): Promise<void> {
  const data = await handle<LoginOut>(
    await fetch(`${BASE}/admin/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    }),
  )
  setToken(data.access_token)
}

export async function fetchMe(): Promise<AdminUser> {
  return apiGet<AdminUser>('/admin/auth/me')
}
