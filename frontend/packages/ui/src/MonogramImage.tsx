import { useState } from 'react'

// Фото типа чехла с изящным фолбэком-монограммой: если картинка не загрузилась
// (или ещё не задана), показываем большую букву-гравировку — это и подпись бренда.
export function MonogramImage({ src, name }: { src: string | null; name: string }) {
  const [failed, setFailed] = useState(false)
  const letter = (name.trim()[0] ?? '?').toUpperCase()

  if (src && !failed) {
    return (
      <div className="monogram" aria-hidden={false}>
        <img
          src={src}
          alt={name}
          onError={() => setFailed(true)}
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
        />
      </div>
    )
  }

  return (
    <div className="monogram" role="img" aria-label={name}>
      <span className="monogram__letter">{letter}</span>
      <span className="monogram__ring" />
    </div>
  )
}
