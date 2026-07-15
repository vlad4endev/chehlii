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
export const SECTIONS: Section[] = [
  { path: '/orders', label: 'Заказы', icon: 'orders', roles: ['admin', 'designer'], badge: 'orders_active' },
  { path: '/catalog', label: 'Каталог', icon: 'catalog', roles: ['admin'] },
  { path: '/clients', label: 'Клиенты', icon: 'clients', roles: ['admin'] },
  { path: '/reviews', label: 'Отзывы', icon: 'reviews', roles: ['admin'], badge: 'reviews_pending' },
  { path: '/bot-texts', label: 'Тексты бота', icon: 'bot', roles: ['admin'] },
  { path: '/broadcasts', label: 'Рассылки', icon: 'broadcast', roles: ['admin'], badge: 'broadcasts_drafts' },
  { path: '/users', label: 'Пользователи', icon: 'users', roles: ['admin'] },
  { path: '/settings', label: 'Настройки', icon: 'settings', roles: ['admin'] },
]

export interface NavGroup {
  label: string | null
  items: Section[]
}

// Сгруппированная навигация для сайдбара.
const GROUPS: NavGroup[] = [
  { label: null, items: [OVERVIEW] },
  { label: 'Работа', items: SECTIONS.slice(0, 3) }, // Заказы, Каталог, Клиенты
  { label: 'Контент', items: SECTIONS.slice(3, 6) }, // Отзывы, Тексты, Рассылки
  { label: 'Система', items: SECTIONS.slice(6) }, // Пользователи, Настройки
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
