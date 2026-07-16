import { apiGet } from './api'

export interface StageBucket {
  key: string
  label: string
  count: number
}

export interface AttentionItem {
  key: string
  label: string
  count: number
  href: string
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
  orders_week: number
  orders_done: number
  orders_cancelled: number
  clients_total: number
  reviews_pending: number
  broadcasts_drafts: number
  revenue_paid: number | null
  pipeline_value: number | null
  avg_check: number | null
  stages: StageBucket[]
  attention: AttentionItem[]
  recent_orders: RecentOrder[]
}

export const fetchStats = () => apiGet<Stats>('/admin/stats')
