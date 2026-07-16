import { apiGet, apiSend } from './api'

export interface TrashClient {
  id: number
  nickname: string | null
  phone: string | null
  channel: 'tg' | 'max'
  number_orders: number
  deleted_at: string | null
}

export interface TrashOrder {
  id: number
  created_at: string
  client_name: string | null
  case_name: string | null
  model_name: string | null
  status_label: string
  deleted_at: string | null
}

export interface Trash {
  clients: TrashClient[]
  orders: TrashOrder[]
}

export const fetchTrash = () => apiGet<Trash>('/admin/trash')

export const restoreClient = (id: number) =>
  apiSend<void>('POST', `/admin/trash/clients/${id}/restore`)
export const restoreOrder = (id: number) =>
  apiSend<void>('POST', `/admin/trash/orders/${id}/restore`)
export const purgeClient = (id: number) => apiSend<void>('DELETE', `/admin/trash/clients/${id}`)
export const purgeOrder = (id: number) => apiSend<void>('DELETE', `/admin/trash/orders/${id}`)
