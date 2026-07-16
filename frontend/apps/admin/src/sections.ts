import type { Role } from './api'

// Разделы AdminUI, иконки и доступ по ролям (ТЗ: у Дизайнера — только Заказы).
export interface Section {
  path: string
  label: string
  icon: string
  roles: Role[]
  /** Ключ метрики из /admin/stats для бейджа в меню (например «на модерации»). */
  badge?: 'reviews_pending' | 'broadcasts_drafts' | 'orders_active'
}

export const OVERVIEW: Section = {
  path: '/',
  label: 'Обзор',
  icon: 'overview',
  roles: ['admin', 'designer'],
}

// Разделы-страницы (используются и для роутинга в App.tsx).
// «Тексты бота» переехали в Настройки → вкладка «Боты», поэтому в меню их нет.
export const SECTIONS: Section[] = [
  { path: '/orders', label: 'Заказы', icon: 'orders', roles: ['admin', 'designer'], badge: 'orders_active' },
  { path: '/catalog', label: 'Каталог', icon: 'catalog', roles: ['admin'] },
  { path: '/clients', label: 'Клиенты', icon: 'clients', roles: ['admin'] },
  { path: '/reviews', label: 'Отзывы', icon: 'reviews', roles: ['admin'], badge: 'reviews_pending' },
  { path: '/broadcasts', label: 'Рассылки', icon: 'broadcast', roles: ['admin'], badge: 'broadcasts_drafts' },
  { path: '/users', label: 'Пользователи', icon: 'users', roles: ['admin'] },
  { path: '/trash', label: 'Корзина', icon: 'trash', roles: ['admin'] },
  { path: '/settings', label: 'Настройки', icon: 'settings', roles: ['admin'] },
]

const byPath = (p: string): Section => {
  const s = SECTIONS.find((x) => x.path === p)
  if (!s) throw new Error(`Unknown section ${p}`)
  return s
}

export interface NavGroup {
  label: string | null
  items: Section[]
}

// Сгруппированная навигация для сайдбара (явные группы — без хрупких срезов).
const GROUPS: NavGroup[] = [
  { label: null, items: [OVERVIEW] },
  { label: 'Работа', items: [byPath('/orders'), byPath('/catalog'), byPath('/clients')] },
  { label: 'Контент', items: [byPath('/reviews'), byPath('/broadcasts')] },
  { label: 'Система', items: [byPath('/users'), byPath('/trash'), byPath('/settings')] },
]

export function sectionsFor(role: Role): Section[] {
  return SECTIONS.filter((s) => s.roles.includes(role))
}

export function groupsFor(role: Role): NavGroup[] {
  return GROUPS.map((g) => ({ ...g, items: g.items.filter((s) => s.roles.includes(role)) })).filter(
    (g) => g.items.length > 0,
  )
}

export function sectionByPath(pathname: string): Section | undefined {
  if (pathname === '/' || pathname === '') return OVERVIEW
  return SECTIONS.find((s) => pathname.startsWith(s.path))
}
