import { apiGet, apiSend } from './api'

export interface Client {
  id: number
  phone: string | null
  channel: 'tg' | 'max'
  channel_user_id: string
  nickname: string | null
  date_start: string | null
  master_code: string | null
  date_master_code: string | null
  discount_master_code: number
  slave_code: string | null
  discount_slave_code: number
  number_slave: number
  discount_for_slave: number
  number_orders: number
  loyal_discount: number
  total_discount: number
}

export interface DiscountsInput {
  loyal_discount: number
  discount_for_slave: number
  discount_master_code: number
  discount_slave_code: number
}

export function fetchClients(q?: string): Promise<Client[]> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  return apiGet<Client[]>(`/admin/clients${qs}`)
}
export const fetchClient = (id: number) => apiGet<Client>(`/admin/clients/${id}`)
export const updateDiscounts = (id: number, body: DiscountsInput) =>
  apiSend<Client>('PATCH', `/admin/clients/${id}`, body)
