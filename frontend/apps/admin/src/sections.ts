import type { Role } from './api'

// Разделы AdminUI и доступ по ролям (ТЗ: у Дизайнера — только Заказы).
export interface Section {
  path: string
  label: string
  roles: Role[]
}

export const SECTIONS: Section[] = [
  { path: '/orders', label: 'Заказы', roles: ['admin', 'designer'] },
  { path: '/catalog', label: 'Каталог', roles: ['admin'] },
  { path: '/clients', label: 'Клиенты', roles: ['admin'] },
  { path: '/reviews', label: 'Отзывы', roles: ['admin'] },
  { path: '/bot-texts', label: 'Тексты бота', roles: ['admin'] },
  { path: '/broadcasts', label: 'Рассылки', roles: ['admin'] },
  { path: '/users', label: 'Пользователи', roles: ['admin'] },
]

export function sectionsFor(role: Role): Section[] {
  return SECTIONS.filter((s) => s.roles.includes(role))
}
