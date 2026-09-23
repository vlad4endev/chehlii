import { apiGet, apiSend } from './api'

export interface ProxyKey {
  id: string
  kind: string
  label: string
  host: string
  port: number
  network: string | null
  security: string | null
  enabled: boolean
  added_at: string | null
}

export interface TgProxyState {
  enabled: boolean
  keys: ProxyKey[]
  bot: {
    ok: boolean | null
    detail: string | null
    via: string | null
    updated_at: string | null
  }
  fingerprint: string
}

export interface ProxyCheck {
  ok: boolean
  detail: string
  keys: { id: string; label: string; ok: boolean; detail: string }[]
}

export const fetchTgProxy = () => apiGet<TgProxyState>('/admin/tg-proxy')

export const patchTgProxy = (body: {
  enabled?: boolean
  add?: string
  remove_ids?: string[]
  set_enabled?: Record<string, boolean>
}) => apiSend<TgProxyState>('PATCH', '/admin/tg-proxy', body)

export const checkTgProxy = () => apiSend<ProxyCheck>('POST', '/admin/tg-proxy/check')

export const previewTgProxy = (text: string) =>
  apiSend<
    { kind: string; label: string; host: string; port: number; network: string | null; security: string | null }[]
  >('POST', '/admin/tg-proxy/preview', { text })
