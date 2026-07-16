import { apiGet } from './api'

export interface JourneyRow {
  client_id: number
  nickname: string | null
  phone: string | null
  channel: 'tg' | 'max'
  last_msg_at: string | null
  last_msg_code: string | null
  master_code: string | null
}

export const fetchJourneys = () => apiGet<JourneyRow[]>('/admin/journeys')
