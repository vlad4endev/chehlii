import { apiGet } from './api'

export interface StatusBucket {
  status: string
  label: string
  count: number
}

export interface RecentOrder {
  id: number
  created_at: string
  client_name: string | null
  channel: 'tg' | 'max'
  status: string
  label: string
  client_price: number | null
}

export interface Stats {
  orders_total: number
  orders_active: number
  orders_today: number
  orders_cancelled: number
  clients_total: number
  reviews_pending: number
  broadcasts_drafts: number
  revenue_active: number | null
  status_distribution: StatusBucket[]
  recent_orders: RecentOrder[]
}

export const fetchStats = () => apiGet<Stats>('/admin/stats')
