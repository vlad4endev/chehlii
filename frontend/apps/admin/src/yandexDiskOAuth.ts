/** OAuth Яндекс.Диска: URL авторизации и захват токена из redirect (hash/query). */

const TOKEN_KEY = 'casetop:yandex-disk:oauth-token'
const CODE_KEY = 'casetop:yandex-disk:oauth-code'
const ERROR_KEY = 'casetop:yandex-disk:oauth-error'

export function yandexDiskAuthorizeUrl(clientId: string, redirectUri: string): string {
  const params = new URLSearchParams({
    response_type: 'token',
    client_id: clientId.trim(),
    redirect_uri: redirectUri,
    force_confirm: 'yes',
    scope: 'cloud_api:disk.write cloud_api:disk.read cloud_api:disk.info',
  })
  return `https://oauth.yandex.ru/authorize?${params.toString()}`
}

/** Вызвать до роутера: иначе редирект на /login сотрёт #access_token. */
export function stashYandexDiskOAuthFromUrl(): void {
  if (typeof window === 'undefined') return
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ''))
  const search = new URLSearchParams(window.location.search)
  const token = hash.get('access_token')
  const code = search.get('code')
  const error = search.get('error') || hash.get('error')
  const errorDescription = search.get('error_description') || hash.get('error_description')
  if (token) sessionStorage.setItem(TOKEN_KEY, token)
  if (code) sessionStorage.setItem(CODE_KEY, code)
  if (error) {
    const detail = errorDescription ? `${error}: ${errorDescription}` : error
    sessionStorage.setItem(ERROR_KEY, detail)
  }
  if (!token && !code && !error) return
  const url = new URL(window.location.href)
  url.hash = ''
  url.searchParams.delete('code')
  url.searchParams.delete('state')
  url.searchParams.delete('error')
  url.searchParams.delete('error_description')
  window.history.replaceState({}, '', `${url.pathname}${url.search}`)
}

export function takeYandexDiskOAuth(): { token: string | null; code: string | null; error: string | null } {
  const token = sessionStorage.getItem(TOKEN_KEY)
  const code = sessionStorage.getItem(CODE_KEY)
  const error = sessionStorage.getItem(ERROR_KEY)
  sessionStorage.removeItem(TOKEN_KEY)
  sessionStorage.removeItem(CODE_KEY)
  sessionStorage.removeItem(ERROR_KEY)
  return { token, code, error }
}

/** React StrictMode дважды монтирует эффект — токен из URL читаем один раз на модуль. */
let _consumed: ReturnType<typeof takeYandexDiskOAuth> | undefined

export function consumeYandexDiskOAuth(): { token: string | null; code: string | null; error: string | null } {
  if (_consumed === undefined) {
    _consumed = takeYandexDiskOAuth()
  }
  return _consumed
}
