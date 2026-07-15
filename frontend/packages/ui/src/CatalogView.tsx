import type { CaseType } from './types'
import { formatPrice, mediaUrl } from './api'
import { CaseMockup } from './CaseMockup'

// Общий компонент каталога — рендерится и в Telegram/MAX WebApp, и на лендинге.
// Поведение кнопок задаётся снаружи (в боте — sendData, на лендинге — deep link).
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
        // Обложка карточки: фото типа, иначе первое фото среди моделей.
        const cover = mediaUrl(item.photo_url ?? item.models.find((m) => m.photo_url)?.photo_url)
        return (
          <article className="card" key={item.id}>
            <button
              className="card__media"
              onClick={() => onOpen(item)}
              aria-label={`Открыть ${item.name}`}
            >
              <CaseMockup name={item.name} isCustom={item.is_custom} photoUrl={cover} />
            </button>

            <button
              className={`fav${fav ? ' fav--on' : ''}`}
              onClick={() => onToggleFavorite(item)}
              aria-pressed={fav}
              aria-label={fav ? 'Убрать из избранного' : 'В избранное'}
            >
              <HeartIcon filled={fav} />
            </button>

            <div className="card__body" onClick={() => onOpen(item)}>
              <span className={`meta${item.is_custom ? ' meta--accent' : ''}`}>
                {item.is_custom ? 'Кастом' : 'Стандарт'}
              </span>
              <h3 className="card__name">{item.name}</h3>
              <div className="price card__price">{formatPrice(item.client_price)}</div>
            </div>
          </article>
        )
      })}
    </div>
  )
}

export function HeartIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 20.5 4.2 12.9a4.6 4.6 0 0 1 0-6.6 4.7 4.7 0 0 1 6.6 0l1.2 1.2 1.2-1.2a4.7 4.7 0 0 1 6.6 0 4.6 4.6 0 0 1 0 6.6z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
    </svg>
  )
}
