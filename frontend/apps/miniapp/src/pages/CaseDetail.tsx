import { useEffect } from 'react'

import type { CaseType } from '@ui/types'
import { formatPrice } from '@ui/api'
import { MonogramImage } from '@ui/MonogramImage'

import { isTelegram, mainButton, sendOrder } from '../telegram'

// Экран карточки чехла. «Выбрать для заказа»: в Telegram — sendData в бот +
// нативная MainButton; вне Telegram (лендинг/превью) — deep link в бот.
export function CaseDetail({
  item,
  isFavorite,
  onToggleFavorite,
  onClose,
}: {
  item: CaseType
  isFavorite: boolean
  onToggleFavorite: () => void
  onClose: () => void
}) {
  const caseType = item.is_custom ? 'custom' : 'standard'

  function order() {
    const sent = sendOrder(item.id, caseType)
    if (!sent) {
      // Лендинг: увести в бот. TODO: подставить реальный username бота.
      const deepLink = `https://t.me/chehlii_bot?start=case_${item.id}_${caseType}`
      window.open(deepLink, '_blank')
    }
  }

  // Нативная кнопка Telegram снизу экрана.
  useEffect(() => {
    const mb = mainButton()
    if (!mb) return
    mb.setText('Выбрать для заказа')
    mb.show()
    mb.onClick(order)
    return () => {
      mb.offClick(order)
      mb.hide()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id])

  const available = item.models.filter((m) => m.is_available)

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label={item.name}>
      <div className="sheet__bar">
        <button className="sheet__close" onClick={onClose} aria-label="Закрыть">
          ←
        </button>
        <button
          className={`heart heart--inline${isFavorite ? ' heart--on' : ''}`}
          onClick={onToggleFavorite}
          aria-pressed={isFavorite}
        >
          {isFavorite ? '♥' : '♡'}
        </button>
      </div>

      <div className="sheet__scroll">
        <div className="detail__media">
          <MonogramImage src={item.photo_url} name={item.name} />
        </div>

        <div className="detail__head">
          <span className={`tag${item.is_custom ? ' tag--custom' : ''}`}>
            {item.is_custom ? 'Кастом' : 'Стандарт'}
          </span>
          <h1 className="detail__name">{item.name}</h1>
          <div className="price detail__price">{formatPrice(item.client_price)}</div>
        </div>

        {item.description && <p className="detail__desc">{item.description}</p>}

        <div className="detail__models">
          <div className="detail__label">Доступные модели</div>
          <div className="chips">
            {available.map((m) => (
              <span className="chip" key={m.model_name}>
                {m.model_name}
              </span>
            ))}
          </div>
        </div>
      </div>

      <div className="sheet__actions">
        <button className="btn btn--ghost" onClick={onToggleFavorite}>
          {isFavorite ? 'В избранном' : 'В избранное'}
        </button>
        <button className="btn btn--primary" onClick={order}>
          Выбрать для заказа
        </button>
      </div>
      {!isTelegram() && (
        <p className="sheet__hint">Оформление заказа продолжится в боте</p>
      )}
    </div>
  )
}
