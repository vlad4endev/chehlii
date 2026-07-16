// Монохромный набор иконок (line, stroke=currentColor). Без иконочных шрифтов.
import type { ReactNode } from 'react'

const P = ({ d }: { d: string }) => (
  <path d={d} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
)

const ICONS: Record<string, ReactNode> = {
  overview: (
    <>
      <P d="M4 13h7V4H4zM13 20h7V4h-7zM4 20h7v-4H4z" />
    </>
  ),
  orders: <P d="M4 7l8-3 8 3-8 3zM4 7v10l8 3 8-3V7M12 10v10" />,
  catalog: <P d="M4 5h16v14H4zM4 10h16M9 5v14" />,
  clients: <P d="M16 19v-1a4 4 0 00-4-4H7a4 4 0 00-4 4v1M9.5 10a3 3 0 100-6 3 3 0 000 6M17 11a3 3 0 000-6M21 19v-1a4 4 0 00-3-3.9" />,
  reviews: <P d="M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4 7.2 18.9l.9-5.4L4.2 9.7l5.4-.8z" />,
  bot: <P d="M12 3v3M8 21h8M5 10h14a2 2 0 012 2v3a2 2 0 01-2 2H5a2 2 0 01-2-2v-3a2 2 0 012-2M9 14h.01M15 14h.01" />,
  broadcast: <P d="M3 11l16-6v14L3 13v-2zM3 11v2M7 12.5V18a2 2 0 002 2h1" />,
  users: <P d="M9 11a4 4 0 100-8 4 4 0 000 8M3 21v-1a5 5 0 015-5h2a5 5 0 015 5v1M17 3.5a4 4 0 010 7M21 21v-1a5 5 0 00-3-4.6" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" strokeWidth="1.7" />
      <P d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
    </>
  ),
  plug: <P d="M9 2v6M15 2v6M7 8h10v3a5 5 0 01-10 0zM12 16v6" />,
  trash: <P d="M4 7h16M10 4h4M6 7l1 13h10l1-13M10 11v6M14 11v6" />,
  restore: <P d="M3 12a9 9 0 109-9 9 9 0 00-6.4 2.6L3 8M3 4v4h4" />,
  logout: <P d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />,
  plus: <P d="M12 5v14M5 12h14" />,
  search: <P d="M11 19a8 8 0 100-16 8 8 0 000 16zM21 21l-4.3-4.3" />,
  chevron: <P d="M9 6l6 6-6 6" />,
  // KPI
  box: <P d="M4 7l8-3 8 3-8 3zM4 7v10l8 3 8-3V7M12 10v10" />,
  pulse: <P d="M3 12h4l2 6 4-14 2 8h6" />,
  calendar: <P d="M4 6h16v14H4zM4 10h16M8 3v4M16 3v4" />,
  ruble: <P d="M8 20V4h5a4 4 0 010 8H8m0-4h9M6 16h6" />,
  client: <P d="M20 21a8 8 0 10-16 0M12 11a4 4 0 100-8 4 4 0 000 8" />,
  star: <P d="M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4 7.2 18.9l.9-5.4L4.2 9.7l5.4-.8z" />,
}

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      style={{ flex: '0 0 auto', display: 'block' }}
    >
      {ICONS[name] ?? ICONS.box}
    </svg>
  )
}
