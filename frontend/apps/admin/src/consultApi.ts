import { apiGet, apiSend, apiUpload } from './api'

export type Channel = 'tg' | 'max'
export type ConsultStatus = 'open' | 'closed'
export type ConsultSender = 'client' | 'admin'
export type ConsultTab = 'waiting' | 'open' | 'closed' | 'all'

export interface MediaItem {
  url: string
  type: string
  name?: string | null
  code?: string | null
  state?: string | null
}

export interface ConsultThread {
  id: number
  client_id: number
  client_name: string
  client_phone: string | null
  channel: Channel
  status: ConsultStatus
  last_message_at: string | null
  last_preview: string | null
  last_sender: ConsultSender | null
  unread_admin: number
  created_at: string
}

export interface ConsultMessage {
  id: number
  sender: ConsultSender
  admin_user_id: number | null
  kind: string
  text: string | null
  media: MediaItem[]
  created_at: string
}

export interface ThreadDetail {
  thread: ConsultThread
  messages: ConsultMessage[]
}

export const fetchThreads = (tab: ConsultTab, q?: string) => {
  const p = new URLSearchParams({ tab })
  if (q?.trim()) p.set('q', q.trim())
  return apiGet<ConsultThread[]>(`/admin/consult/threads?${p}`)
}

export const fetchThread = (id: number) => apiGet<ThreadDetail>(`/admin/consult/threads/${id}`)

export const markRead = (id: number) => apiSend<{ ok: boolean }>('POST', `/admin/consult/threads/${id}/read`)

export const closeThread = (id: number) =>
  apiSend<ConsultThread>('POST', `/admin/consult/threads/${id}/close`)

export const reopenThread = (id: number) =>
  apiSend<ConsultThread>('POST', `/admin/consult/threads/${id}/reopen`)

export const sendReply = (id: number, text: string, media: MediaItem[]) =>
  apiSend<ConsultMessage>('POST', `/admin/consult/threads/${id}/messages`, { text, media })

export const sendScenario = (id: number, code: string) =>
  apiSend<ConsultMessage>('POST', `/admin/consult/threads/${id}/scenario`, { code })

export const uploadConsultMedia = (file: File) =>
  apiUpload<MediaItem>('/admin/consult/media', file)
