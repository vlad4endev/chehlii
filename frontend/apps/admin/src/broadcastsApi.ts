import { apiGet, apiSend, apiUpload } from './api'

export type Channel = 'tg' | 'max'

export interface Segment {
  channel?: Channel | null
  registered_from?: string | null
  registered_to?: string | null
  order_status?: string | null
  only_with_orders?: boolean
}

export interface MediaItem {
  url: string
  type: 'image' | 'video'
}

export interface Broadcast {
  id: number
  text: string
  media: MediaItem[]
  segment: Segment
  recipients_count: number
  sent_at: string | null
  created_at: string
  is_draft: boolean
}

export interface PreviewOut {
  recipients_count: number
  by_channel: { tg: number; max: number }
}

export interface SendResult {
  broadcast: Broadcast
  delivered: number
  failed: number
  skipped: number
  note: string | null
}

export const fetchBroadcasts = () => apiGet<Broadcast[]>('/admin/broadcasts')

export const previewSegment = (segment: Segment) =>
  apiSend<PreviewOut>('POST', '/admin/broadcasts/preview', { segment })

export const createBroadcast = (text: string, segment: Segment, media: MediaItem[]) =>
  apiSend<Broadcast>('POST', '/admin/broadcasts', { text, segment, media })

// Загружает фото или видео рассылки, возвращает {url, type}.
export const uploadBroadcastMedia = (file: File) =>
  apiUpload<MediaItem>('/admin/media', file)

export const sendBroadcast = (id: number) =>
  apiSend<SendResult>('POST', `/admin/broadcasts/${id}/send`)

// Статусы заказа, полезные как сегмент рассылки (подмножество модели статусов ТЗ).
export const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'Любой статус' },
  { value: 'prepayment_paid', label: 'Предоплата прошла' },
  { value: 'design_in_progress', label: 'Дизайн в процессе' },
  { value: 'mockup_approval', label: 'Согласование макета' },
  { value: 'postpayment_paid', label: 'Постоплата прошла' },
  { value: 'shipped', label: 'Отправлен' },
  { value: 'delivered', label: 'Получен' },
  { value: 'review_received', label: 'Отзыв получен' },
  { value: 'cancelled', label: 'Отменён' },
]
