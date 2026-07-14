// API-клиент каталога. База берётся из VITE_API_BASE (по умолчанию — относительный
// путь, который в dev проксируется Vite на живой backend, в prod — тот же origin/NPM).
import type { CaseType } from './types'

const BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api/v1'

export async function fetchCatalog(): Promise<CaseType[]> {
  const res = await fetch(`${BASE}/catalog`)
  if (!res.ok) throw new Error(`Каталог недоступен (${res.status})`)
  return res.json()
}

export function formatPrice(value: number): string {
  return new Intl.NumberFormat('ru-RU').format(value) + ' ₽'
}

// Русская плюрализация: plural(3, ['тип','типа','типов']) → 'типа'.
export function plural(n: number, forms: [string, string, string]): string {
  const abs = Math.abs(n) % 100
  const d = abs % 10
  if (abs > 10 && abs < 20) return forms[2]
  if (d > 1 && d < 5) return forms[1]
  if (d === 1) return forms[0]
  return forms[2]
}
