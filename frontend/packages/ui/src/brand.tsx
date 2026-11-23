import { useEffect, useState } from 'react'

import { mediaUrl } from './api'

// Логотип задаётся в админке (Настройки → «Логотип»). Пока он не загружен (или сброшен),
// показываем фирменный знак + название. Значение общее для всех мест страницы.
const BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api/v1'

let logo: string | null | undefined // undefined — ещё не узнали
let inflight: Promise<void> | null = null
const subscribers = new Set<() => void>()

const notify = () => subscribers.forEach((fn) => fn())

function load(): void {
  if (logo !== undefined || inflight) return
  inflight = fetch(`${BASE}/brand`)
    .then((r) => (r.ok ? r.json() : null))
    .then((d: { logo_url?: string | null } | null) => {
      logo = d?.logo_url ?? null
    })
    .catch(() => {
      logo = null
    })
    .finally(() => {
      inflight = null
      notify()
    })
}

function useLogoUrl(): string | null | undefined {
  const [, rerender] = useState(0)
  useEffect(() => {
    const fn = () => rerender((n) => n + 1)
    subscribers.add(fn)
    load()
    return () => {
      subscribers.delete(fn)
    }
  }, [])
  return logo
}

export function BrandLogo({ height = 28 }: { height?: number }) {
  const custom = useLogoUrl()
  if (custom) {
    return <img className="brand-logo" src={mediaUrl(custom) ?? ''} alt="casetop" style={{ height }} />
  }
  return (
    <>
      <img
        className="brand-mark"
        src={`${import.meta.env.BASE_URL}favicon.svg`}
        alt=""
        width={height}
        height={height}
      />
      casetop
    </>
  )
}
