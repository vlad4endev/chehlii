import { apiGet, apiSend } from './api'

export interface BotMessage {
  code: string
  trigger: string
  text: string
  buttons: unknown[] | null
  channel_tg: boolean
  channel_max: boolean
}

export interface BotMessagePatch {
  text: string
  channel_tg?: boolean
  channel_max?: boolean
}

export const fetchBotMessages = () => apiGet<BotMessage[]>('/admin/bot-messages')
export const updateBotMessage = (code: string, body: BotMessagePatch) =>
  apiSend<BotMessage>('PATCH', `/admin/bot-messages/${code}`, body)
