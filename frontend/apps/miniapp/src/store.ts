import { useCallback, useEffect, useState } from 'react'

// Избранное. По ТЗ хранится на сервере (привязка к клиенту) — эндпоинты появятся
// в бэкенде позже; пока используем localStorage, чтобы UX работал. Интерфейс хука
// не изменится при переходе на серверное хранилище.
const KEY = 'chehlii:favorites'

function read(): number[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as number[]) : []
  } catch {
    return []
  }
}

export function useFavorites() {
  const [ids, setIds] = useState<Set<number>>(() => new Set(read()))

  useEffect(() => {
    localStorage.setItem(KEY, JSON.stringify([...ids]))
  }, [ids])

  const toggle = useCallback((id: number) => {
    setIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  return { ids, toggle }
}
