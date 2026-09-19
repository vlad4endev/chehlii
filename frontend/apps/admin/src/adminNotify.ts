/** Уведомления админки: дельта /admin/stats → тосты + Notification + title. */

import type { Stats } from './statsApi'

const BASELINE_KEY = 'casetop:admin:notify-baseline'
const TITLE_BASE = 'casetop · Админка'

export type NotifyKind = 'consult' | 'order'

export interface NotifyEvent {
  id: string
  kind: NotifyKind
  count: number
  href: string
  title: string
  body: string
}

export interface NotifyBaseline {
  consult_unread: number
  orders_total: number
  max_order_id: number
}

function maxOrderId(stats: Stats): number {
  let max = 0
  for (const o of stats.recent_orders || []) {
    if (o.id > max) max = o.id
  }
  return max
}

export function snapshotBaseline(stats: Stats): NotifyBaseline {
  return {
    consult_unread: stats.consult_unread || 0,
    orders_total: stats.orders_total || 0,
    max_order_id: maxOrderId(stats),
  }
}

export function loadBaseline(): NotifyBaseline | null {
  try {
    const raw = sessionStorage.getItem(BASELINE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as NotifyBaseline
    if (
      typeof parsed.consult_unread !== 'number' ||
      typeof parsed.orders_total !== 'number' ||
      typeof parsed.max_order_id !== 'number'
    ) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function saveBaseline(b: NotifyBaseline): void {
  try {
    sessionStorage.setItem(BASELINE_KEY, JSON.stringify(b))
  } catch {
    /* quota / private mode */
  }
}

function pluralRu(n: number, one: string, few: string, many: string): string {
  const n10 = n % 10
  const n100 = n % 100
  if (n10 === 1 && n100 !== 11) return one
  if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return few
  return many
}

function consultCopy(count: number): { title: string; body: string } {
  if (count === 1) {
    return { title: 'Новое сообщение', body: 'Клиент ждёт ответа в Сообщениях' }
  }
  const word = pluralRu(count, 'новое сообщение', 'новых сообщения', 'новых сообщений')
  return { title: `${count} ${word}`, body: 'Откройте раздел Сообщения' }
}

function orderCopy(count: number): { title: string; body: string } {
  if (count === 1) {
    return { title: 'Новый заказ', body: 'Появился заказ в воронке' }
  }
  const word = pluralRu(count, 'новый заказ', 'новых заказа', 'новых заказов')
  return { title: `${count} ${word}`, body: 'Откройте раздел Заказы' }
}

/**
 * Сравнить prev и next. consultOnly=false для дизайнера (только заказы).
 * Первый заход: вызывающий сохраняет baseline и не вызывает diff.
 */
export function diffStats(
  prev: NotifyBaseline,
  next: Stats,
  opts: { includeConsult: boolean },
): NotifyEvent[] {
  const events: NotifyEvent[] = []
  const now = Date.now()

  if (opts.includeConsult) {
    const delta = (next.consult_unread || 0) - prev.consult_unread
    if (delta > 0) {
      const copy = consultCopy(delta)
      events.push({
        id: `consult-${now}`,
        kind: 'consult',
        count: delta,
        href: '/consult',
        title: copy.title,
        body: copy.body,
      })
    }
  }

  const byTotal = (next.orders_total || 0) - prev.orders_total
  const byId = Math.max(0, maxOrderId(next) - prev.max_order_id)
  // Берём max: id ловит «новый заказ» даже если total странно не вырос; total — если recent урезан.
  const orderDelta = Math.max(byTotal, byId)
  if (orderDelta > 0) {
    const copy = orderCopy(orderDelta)
    events.push({
      id: `order-${now}`,
      kind: 'order',
      count: orderDelta,
      href: '/orders',
      title: copy.title,
      body: copy.body,
    })
  }

  return events
}

export function browserPermission(): NotificationPermission | 'unsupported' {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported'
  return Notification.permission
}

export async function ensureBrowserPermission(): Promise<NotificationPermission | 'unsupported'> {
  if (typeof window === 'undefined' || !('Notification' in window)) return 'unsupported'
  if (Notification.permission === 'granted' || Notification.permission === 'denied') {
    return Notification.permission
  }
  return Notification.requestPermission()
}

/** Системное уведомление только когда вкладка в фоне и есть разрешение. */
export function pushBrowser(event: NotifyEvent): void {
  if (typeof window === 'undefined' || !('Notification' in window)) return
  if (!document.hidden) return
  if (Notification.permission !== 'granted') return
  try {
    const n = new Notification(event.title, {
      body: event.body,
      tag: `casetop-${event.kind}`,
      renotify: true,
    })
    n.onclick = () => {
      window.focus()
      n.close()
    }
  } catch {
    /* Safari / insecure context */
  }
}

/** Префикс (N) в title — диалоги, ждущие ответа (для админа). */
export function syncTitle(stats: Stats | null, includeConsult: boolean): void {
  if (typeof document === 'undefined') return
  if (!stats) {
    document.title = TITLE_BASE
    return
  }
  const n = includeConsult ? stats.consult_waiting || 0 : 0
  document.title = n > 0 ? `(${n}) ${TITLE_BASE}` : TITLE_BASE
}

export function permissionLabel(p: NotificationPermission | 'unsupported'): string {
  if (p === 'unsupported') return 'Недоступны'
  if (p === 'granted') return 'Вкл.'
  if (p === 'denied') return 'Запрещены'
  return 'Включить'
}
