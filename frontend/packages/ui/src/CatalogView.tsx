import type { CaseType } from './types'
import { formatPrice } from './api'
import { MonogramImage } from './MonogramImage'

// Общий компонент каталога — рендерится и в Telegram/MAX WebApp, и на лендинге.
// Поведение кнопок задаётся снаружи через колбэки (в боте — sendData, на лендинге — deep link).
export interface CatalogViewProps {
  items: CaseType[]
  favorites: Set<number>
  onOpen: (item: CaseType) => void
  onToggleFavorite: (item: CaseType) => void
}

export function CatalogView({ items, favorites, onOpen, onToggleFavorite }: CatalogViewProps) {
  return (
    <div className="grid">
      {items.map((item) => {
        const fav = favorites.has(item.id)
        return (
          <article className="card" key={item.id}>
            <button
              className="card__media"
              onClick={() => onOpen(item)}
              aria-label={`Открыть ${item.name}`}
            >
              <MonogramImage src={item.photo_url} name={item.name} />
            </button>

            <span className={`tag card__tag${item.is_custom ? ' tag--custom' : ''}`}>
              {item.is_custom ? 'Кастом' : 'Стандарт'}
            </span>

            <button
              className={`heart${fav ? ' heart--on' : ''}`}
              onClick={() => onToggleFavorite(item)}
              aria-pressed={fav}
              aria-label={fav ? 'Убрать из избранного' : 'В избранное'}
            >
              {fav ? '♥' : '♡'}
            </button>

            <div className="card__body" onClick={() => onOpen(item)}>
              <h3 className="card__name">{item.name}</h3>
              <div className="price card__price">{formatPrice(item.client_price)}</div>
            </div>
          </article>
        )
      })}
    </div>
  )
}
