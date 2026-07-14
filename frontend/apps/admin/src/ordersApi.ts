import { apiGet, apiSend, apiUrl, getToken } from './api'

export interface StatusOption {
  value: string
  label: string
}

export interface OrderRow {
  id: number
  created_at: string
  channel: 'tg' | 'max'
  client_name: string | null
  client_phone: string | null
  case_name: string | null
  model_name: string | null
  is_custom: boolean | null
  branch: string | null
  status: string
  status_label: string
  payment_status: string | null
  final_price: number | null
}

export interface StatusEvent {
  status: string
  status_label: string
  changed_by: string | null
  trigger: string | null
  created_at: string
}

export interface OrderDetail extends OrderRow {
  materials_text: string | null
  materials_files: unknown[] | null
  custom_text: string | null
  mockup_url: string | null
  delivery_service: string | null
  delivery_address: string | null
  tracking_code: string | null
  cost: number | null
  margin: number | null
  total_discount: number | null
  delivery_cost: number | null
  allowed_next: StatusOption[]
  history: StatusEvent[]
}

// Все статусы (для фильтра). Значения совпадают с backend.
export const STATUSES: StatusOption[] = [
  { value: 'case_type_selected', label: 'Выбран тип чехла' },
  { value: 'model_selected', label: 'Выбрана модель' },
  { value: 'case_confirmed', label: 'Согласован чехол' },
  { value: 'materials_submitted', label: 'Отправка материала' },
  { value: 'prepayment_issued', label: 'Предоплата выставлена' },
  { value: 'prepayment_paid', label: 'Предоплата прошла' },
  { value: 'handed_to_design', label: 'Передан в дизайн' },
  { value: 'design_in_progress', label: 'Дизайн в процессе' },
  { value: 'mockup_sent', label: 'Отправка макета' },
  { value: 'mockup_approval', label: 'Согласование макета' },
  { value: 'mockup_revision', label: 'Пересогласование макета' },
  { value: 'postpayment_issued', label: 'Постоплата выставлена' },
  { value: 'postpayment_paid', label: 'Постоплата прошла' },
  { value: 'cancelled', label: 'Отменён' },
  { value: 'delivery_service_selection', label: 'Выбор службы доставки' },
  { value: 'delivery_address_selection', label: 'Выбор адреса' },
  { value: 'delivery_payment', label: 'Оплата доставки' },
  { value: 'shipped', label: 'Заказ отправлен' },
  { value: 'delivered', label: 'Заказ получен' },
  { value: 'review_offered', label: 'Предложение об отзыве' },
  { value: 'review_received', label: 'Отзыв получен' },
]

export const CHANNELS: StatusOption[] = [
  { value: 'tg', label: 'Telegram' },
  { value: 'max', label: 'MAX' },
]

export interface OrderFilters {
  status?: string
  channel?: string
  q?: string
}

export function fetchOrders(f: OrderFilters): Promise<OrderRow[]> {
  const p = new URLSearchParams()
  if (f.status) p.set('status', f.status)
  if (f.channel) p.set('channel', f.channel)
  if (f.q) p.set('q', f.q)
  const qs = p.toString()
  return apiGet<OrderRow[]>(`/admin/orders${qs ? `?${qs}` : ''}`)
}

export const fetchOrder = (id: number) => apiGet<OrderDetail>(`/admin/orders/${id}`)
export const changeStatus = (id: number, status: string) =>
  apiSend<OrderDetail>('PATCH', `/admin/orders/${id}/status`, { status })
export const uploadMockup = (id: number, mockup_url: string) =>
  apiSend<OrderDetail>('POST', `/admin/orders/${id}/mockup`, { mockup_url })

export async function downloadOrdersXlsx(): Promise<void> {
  const res = await fetch(apiUrl('/admin/orders/export.xlsx'), {
    headers: { Authorization: `Bearer ${getToken()}` },
  })
  if (!res.ok) throw new Error(`Экспорт недоступен (${res.status})`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'orders.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}
