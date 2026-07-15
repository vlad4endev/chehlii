import { useCallback, useEffect, useMemo, useState } from 'react'

import { getTelegramUser } from './telegram'

// Избранное. По ТЗ хранится на сервере и привязано к клиенту (tg_id/max_id) — серверные
// эндпоинты появятся позже. Пока используем localStorage, но ключ уже привязан к клиенту
// (у каждого Telegram-аккаунта своё избранное). Интерфейс хука не изменится при переходе
// на серверное хранилище.
function storageKey(): string {
  const user = getTelegramUser()
  return user ? `casetop:favorites:${user.id}` : 'casetop:favorites'
}

function read(key: string): number[] {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as number[]) : []
  } catch {
    return []
  }
}

export function useFavorites() {
  const key = useMemo(storageKey, [])
  const [ids, setIds] = useState<Set<number>>(() => new Set(read(key)))

  useEffect(() => {
    localStorage.setItem(key, JSON.stringify([...ids]))
  }, [key, ids])

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
