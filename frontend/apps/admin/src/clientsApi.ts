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

export interface ContactChannel {
  client_id: number
  channel: 'tg' | 'max'
  channel_user_id: string
  nickname: string | null
  number_orders: number
  total_discount: number
  chat_url: string | null
}

export interface Contact {
  key: string
  display_name: string | null
  phone: string | null
  total_orders: number
  max_discount: number
  channels: ContactChannel[]
}

export function fetchContacts(q?: string): Promise<Contact[]> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  return apiGet<Contact[]>(`/admin/clients/contacts${qs}`)
}

export function fetchClients(q?: string): Promise<Client[]> {
  const qs = q ? `?q=${encodeURIComponent(q)}` : ''
  return apiGet<Client[]>(`/admin/clients${qs}`)
}
export const fetchClient = (id: number) => apiGet<Client>(`/admin/clients/${id}`)
export const updateDiscounts = (id: number, body: DiscountsInput) =>
  apiSend<Client>('PATCH', `/admin/clients/${id}`, body)
