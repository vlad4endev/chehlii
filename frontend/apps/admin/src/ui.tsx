import type { ReactNode } from 'react'

// Инициалы из имени/почты для аватара.
export function initials(name: string): string {
  const parts = name.replace(/@.*/, '').split(/[\s._-]+/).filter(Boolean)
  return (
    ((parts[0]?.[0] ?? '') + (parts[1]?.[0] ?? '')).toUpperCase() ||
    name[0]?.toUpperCase() ||
    '·'
  )
}

export function Avatar({ name }: { name: string }) {
  return <span className="avatar">{initials(name)}</span>
}

// Ячейка «человек»: аватар + имя + подпись (телефон/почта).
export function UserCell({ name, sub }: { name: string; sub?: ReactNode }) {
  return (
    <span className="cell-user">
      <Avatar name={name} />
      <span className="cell-user__meta">
        <span className="cell-user__name">{name}</span>
        {sub != null && sub !== '' && <span className="cell-user__sub">{sub}</span>}
      </span>
    </span>
  )
}

export interface Stat {
  label: string
  value: ReactNode
}

// Строка сводных метрик под заголовком раздела.
export function StatLine({ items }: { items: Stat[] }) {
  return (
    <div className="statline">
      {items.map((s, i) => (
        <div className="statchip" key={i}>
          <span className="statchip__value">{s.value}</span>
          <span className="statchip__label">{s.label}</span>
        </div>
      ))}
    </div>
  )
}

export function ChannelChip({ channel }: { channel: string }) {
  const label = channel === 'tg' ? 'Telegram' : channel === 'max' ? 'MAX' : channel
  return <span className="chip">{label}</span>
}
