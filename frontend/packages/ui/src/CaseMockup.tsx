import { useState } from 'react'

// Презентационный мокап чехла (SVG): рисует заднюю часть iPhone в чехле.
// Тема (цвет/финиш) — по типу чехла; блок камеры — по модели iPhone (база/Pro/Air).
// Если у типа задано реальное фото (photoUrl) — показываем его; иначе рисуем мокап.
// Векторно → чётко на любой модели и размере, заменяет фото до реальных снимков.

type Tier = 'base' | 'pro' | 'air'

function modelTier(model?: string): Tier {
  if (!model) return 'pro'
  if (/air/i.test(model)) return 'air'
  if (/pro|max/i.test(model)) return 'pro'
  return 'base'
}

function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}

const FINISHES = [
  { body: '#efe7d5', edge: '#e2d8c1', mono: '#b6a47c', dark: false }, // крем
  { body: '#e7e9eb', edge: '#d6dade', mono: '#9aa0a7', dark: false }, // серебро
  { body: '#33353b', edge: '#25272c', mono: '#61646c', dark: true }, // графит
  { body: '#dde7e1', edge: '#ccd9d1', mono: '#7f9a8c', dark: false }, // шалфей
  { body: '#e7dfe9', edge: '#d7ccdb', mono: '#9179a0', dark: false }, // лиловый
]

function Camera({ tier, dark }: { tier: Tier; dark: boolean }) {
  const glass = dark ? '#0c0c0e' : '#1b1b1f'
  const ring = dark ? '#45464c' : '#3a3b41'
  const lens = (cx: number, cy: number, r = 13) => (
    <g key={`${cx}-${cy}`}>
      <circle cx={cx} cy={cy} r={r} fill={ring} />
      <circle cx={cx} cy={cy} r={r - 4} fill={glass} />
      <circle cx={cx - r / 3} cy={cy - r / 3} r={r / 4} fill="#5b6472" opacity="0.7" />
    </g>
  )

  if (tier === 'air') {
    // Горизонтальный «камера-бар» (силуэт iPhone Air).
    return (
      <g>
        <rect x="100" y="52" width="120" height="40" rx="20" fill={glass} />
        {lens(122, 72, 12)}
        {lens(160, 72, 12)}
        <circle cx="198" cy="72" r="5" fill="#c9a23a" />
      </g>
    )
  }

  // Квадратный блок камер (база / Pro).
  const modX = 100
  const modY = 48
  return (
    <g>
      <rect x={modX} y={modY} width="64" height="64" rx="18" fill={dark ? '#26272c' : '#dcdcd6'} />
      {tier === 'pro' ? (
        <>
          {lens(120, 66)}
          {lens(120, 94)}
          {lens(146, 80)}
        </>
      ) : (
        <>
          {lens(122, 66)}
          {lens(122, 94)}
        </>
      )}
      <circle cx="150" cy="66" r="5" fill={dark ? '#3a3b41' : '#c7c7c1'} />
    </g>
  )
}

export function CaseMockup({
  name,
  isCustom,
  model,
  photoUrl,
}: {
  name: string
  isCustom: boolean
  model?: string
  photoUrl?: string | null
}) {
  const [failed, setFailed] = useState(false)
  const letter = (name.trim()[0] ?? '?').toUpperCase()
  const tier = modelTier(model)
  const finish = FINISHES[hashStr(name) % FINISHES.length]
  const gid = `g${hashStr(name) % 1000}`

  if (photoUrl && !failed) {
    return (
      <div className="monogram">
        <img
          src={photoUrl}
          alt={name}
          onError={() => setFailed(true)}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </div>
    )
  }

  const caseFill = isCustom ? `url(#${gid}-art)` : finish.body

  return (
    <div className="monogram" role="img" aria-label={`${name}${model ? `, ${model}` : ''}`}>
      <svg viewBox="0 0 320 400" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
        <defs>
          <linearGradient id={`${gid}-art`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#3a3b3e" />
            <stop offset="0.55" stopColor="#1d1e20" />
            <stop offset="1" stopColor="#0a0a0b" />
          </linearGradient>
          <linearGradient id={`${gid}-gloss`} x1="0" y1="0" x2="0.7" y2="1">
            <stop offset="0" stopColor="#ffffff" stopOpacity="0.5" />
            <stop offset="0.4" stopColor="#ffffff" stopOpacity="0.06" />
            <stop offset="1" stopColor="#ffffff" stopOpacity="0" />
          </linearGradient>
          <filter id={`${gid}-shadow`} x="-30%" y="-20%" width="160%" height="150%">
            <feDropShadow dx="0" dy="14" stdDeviation="16" floodColor="#141414" floodOpacity="0.22" />
          </filter>
        </defs>

        {/* подиум-тень */}
        <ellipse cx="160" cy="372" rx="86" ry="14" fill="#141414" opacity="0.12" />

        <g filter={`url(#${gid}-shadow)`}>
          {/* корпус */}
          <rect x="86" y="30" width="148" height="338" rx="40" fill={caseFill} stroke={finish.edge} strokeWidth="2" />

          {/* боковые кнопки */}
          <rect x="82" y="96" width="4" height="26" rx="2" fill={finish.edge} />
          <rect x="82" y="132" width="4" height="40" rx="2" fill={finish.edge} />
          <rect x="234" y="118" width="4" height="52" rx="2" fill={finish.edge} />

          {/* арт / гравировка-монограмма */}
          {isCustom ? (
            <g opacity="0.9">
              <circle cx="150" cy="250" r="52" fill="#ffffff" opacity="0.14" />
              <circle cx="196" cy="300" r="30" fill="#ffffff" opacity="0.10" />
              <circle cx="120" cy="310" r="20" fill="#000000" opacity="0.18" />
              <text x="160" y="252" textAnchor="middle" fontSize="60" fontFamily="Unbounded, sans-serif" fontWeight="800" fill="#ffffff" opacity="0.9">✦</text>
            </g>
          ) : (
            <text
              x="160"
              y="255"
              textAnchor="middle"
              fontSize="104"
              fontFamily="Unbounded, sans-serif"
              fontWeight="800"
              letterSpacing="-4"
              fill={finish.mono}
              opacity={finish.dark ? 0.85 : 0.5}
            >
              {letter}
            </text>
          )}

          {/* блик */}
          <rect x="86" y="30" width="148" height="338" rx="40" fill={`url(#${gid}-gloss)`} />

          {/* камера по модели */}
          <Camera tier={tier} dark={finish.dark} />
        </g>
      </svg>
    </div>
  )
}
