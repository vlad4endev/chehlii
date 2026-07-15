import { useEffect, useState } from 'react'

import type { CaseType } from '@ui/types'
import { createOrder, formatPrice, mediaUrl, upsertClient } from '@ui/api'
import { CaseMockup } from '@ui/CaseMockup'
import { HeartIcon } from '@ui/CatalogView'

import { getMaxUser, isMax, openBotWithOrder } from '../max'
import { backButton, isTelegram, mainButton, sendOrder } from '../telegram'

// Экран типа чехла. Модель iPhone выбирается здесь же, в мини-приложении.
// «Выбрать для заказа» доступна только после выбора модели; далее в бот уходит
// {case_id, case_type, model}. В Telegram — sendData + нативная MainButton;
// вне Telegram (лендинг) — экран-хэндофф в бот.
export function CaseDetail({
  item,
  isFavorite,
  onToggleFavorite,
  onClose,
  onOrdered,
}: {
  item: CaseType
  isFavorite: boolean
  onToggleFavorite: () => void
  onClose: () => void
  onOrdered: (model: string) => void
}) {
  const caseType = item.is_custom ? 'custom' : 'standard'
  const available = item.models.filter((m) => m.is_available)
  const [model, setModel] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Фото под выбранную модель → фолбэк на обложку типа. Мокап рисуется, если фото нет.
  const selected = available.find((m) => m.model_name === model)
  const photo = mediaUrl(selected?.photo_url ?? item.photo_url)

  async function order() {
    if (!model || submitting) return
    // Telegram: нативный sendData передаёт выбор боту и закрывает WebApp.
    if (sendOrder(item.id, caseType, model)) return
    // MAX: sendData нет — создаём заказ через backend и открываем бота deep-link'ом.
    if (isMax()) {
      const user = getMaxUser()
      if (user) {
        setSubmitting(true)
        try {
          const client = await upsertClient('max', String(user.id), user.username ?? user.firstName)
          const ord = await createOrder(client.id, item.id, caseType, model)
          openBotWithOrder(ord.id)
          return
        } catch {
          // не вышло — покажем экран-хэндофф ниже
        } finally {
          setSubmitting(false)
        }
      }
    }
    // Лендинг/браузер: экран-хэндофф со ссылкой в бот.
    onOrdered(model)
  }

  // Нативная кнопка «Назад» Telegram закрывает экран типа.
  useEffect(() => {
    const bb = backButton()
    if (!bb) return
    bb.show()
    bb.onClick(onClose)
    return () => {
      bb.offClick(onClose)
      bb.hide()
    }
  }, [onClose])

  // Нативная кнопка Telegram: показываем только когда модель выбрана.
  useEffect(() => {
    const mb = mainButton()
    if (!mb) return
    const handler = () => order()
    mb.setText('Выбрать для заказа')
    if (model) mb.show()
    else mb.hide()
    mb.onClick(handler)
    return () => {
      mb.offClick(handler)
      mb.hide()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item.id, model])

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label={item.name}>
      <div className="sheet__bar">
        <button className="iconbtn" onClick={onClose} aria-label="Назад">
          <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M15 5l-7 7 7 7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
        <span className={`meta${item.is_custom ? ' meta--accent' : ''}`}>
          {item.is_custom ? 'Кастом' : 'Стандарт'}
        </span>
        <button
          className={`iconbtn${isFavorite ? ' iconbtn--on' : ''}`}
          onClick={onToggleFavorite}
          aria-pressed={isFavorite}
          aria-label={isFavorite ? 'Убрать из избранного' : 'В избранное'}
        >
          <HeartIcon filled={isFavorite} />
        </button>
      </div>

      <div className="sheet__scroll">
        <div className="detail__media">
          <CaseMockup
            name={item.name}
            isCustom={item.is_custom}
            photoUrl={photo}
            model={model ?? undefined}
          />
        </div>

        <h1 className="detail__name">{item.name}</h1>
        <div className="price detail__price">{formatPrice(item.client_price)}</div>

        {item.description && <p className="detail__desc">{item.description}</p>}

        <div className="detail__models">
          <div className="meta detail__label">Выберите модель iPhone</div>
          <div className="chips">
            {available.map((m) => (
              <button
                key={m.model_name}
                className={`chip chip--select${model === m.model_name ? ' chip--on' : ''}`}
                onClick={() => setModel(m.model_name)}
                aria-pressed={model === m.model_name}
              >
                {m.model_name}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="sheet__actions">
        <button
          className="btn btn--icon"
          onClick={onToggleFavorite}
          aria-pressed={isFavorite}
          aria-label={isFavorite ? 'Убрать из избранного' : 'В избранное'}
        >
          <HeartIcon filled={isFavorite} />
        </button>
        <button className="btn btn--primary" onClick={order} disabled={!model || submitting}>
          {submitting ? 'Оформляем…' : model ? 'Выбрать для заказа' : 'Выберите модель'}
        </button>
      </div>
      {!isTelegram() && <p className="sheet__hint">Оформление заказа продолжится в боте</p>}
    </div>
  )
}
