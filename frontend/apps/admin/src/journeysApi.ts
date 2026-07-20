import { apiGet, apiUrl, getToken } from './api'

export interface JourneyRow {
  client_id: number
  nickname: string | null
  phone: string | null
  channel: 'tg' | 'max'
  first_msg_at: string | null
  last_msg_at: string | null
  last_msg_code: string | null
  master_code: string | null
  successful_orders: number
}

export const fetchJourneys = () => apiGet<JourneyRow[]>('/admin/journeys')

export async function downloadJourneysXlsx(): Promise<void> {
  const res = await fetch(apiUrl('/admin/journeys/export.xlsx'), {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!res.ok) throw new Error(`Экспорт недоступен (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'journeys.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}
