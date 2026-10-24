import { apiGet, apiSend } from './api'

export interface BotMessage {
  code: string
  trigger: string
  text: string
  buttons: unknown[] | null
  channel_tg: boolean
  channel_max: boolean
  media_format: string
  media_url: string | null
  media_file_id_tg: string | null
  media_poster_url: string | null
}

export interface BotMessagePatch {
  text: string
  channel_tg?: boolean
  channel_max?: boolean
  media_format?: string
  media_url?: string | null
  media_poster_url?: string | null
  clear_media?: boolean
}

export const fetchBotMessages = () => apiGet<BotMessage[]>('/admin/bot-messages')
export const updateBotMessage = (code: string, body: BotMessagePatch) =>
  apiSend<BotMessage>('PATCH', `/admin/bot-messages/${code}`, body)
