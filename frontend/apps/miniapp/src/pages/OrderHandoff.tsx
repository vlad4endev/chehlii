import { useEffect } from 'react'

import type { CaseType } from '@ui/types'

import { isMax, MAX_BOT_USERNAME } from '../max'
import { backButton, botStartLink } from '../telegram'

// Экран после «Выбрать для заказа» вне Telegram/MAX WebApp (лендинг/браузер):
// подтверждает выбор и ведёт в бот. В самом Telegram этот экран не нужен —
// там sendData сразу передаёт выбор боту. В MAX заказ создаётся в CaseDetail
// и открывается deep-link order_<id>; сюда попадаем только из браузера.
//
// Воронка кастома (как в боте): материалы → предоплата → макет → остаток.
const STEPS_STANDARD = ['Напишете имя или букву', 'Внесёте предоплату', 'Выберете доставку']
const STEPS_CUSTOM = [
  'Пришлёте фото и пожелания',
  'Внесёте предоплату',
  'Согласуете макет — затем остаток и доставка',
]

export function OrderHandoff({
  item,
  model,
  onBack,
}: {
  item: CaseType
  model: string
  onBack: () => void
}) {
  const caseType = item.is_custom ? 'custom' : 'standard'
  const steps = item.is_custom ? STEPS_CUSTOM : STEPS_STANDARD
  const modelIndex = item.models.findIndex((m) => m.model_name === model)

  function openBot() {
    if (isMax()) {
      const url = `https://max.ru/${MAX_BOT_USERNAME}`
      const w = (window as unknown as { WebApp?: { openLink?(u: string): void } }).WebApp
      if (w?.openLink) w.openLink(url)
      else window.open(url, '_blank')
      return
    }
    window.open(botStartLink(item.id, caseType, modelIndex), '_blank')
  }

  useEffect(() => {
    const bb = backButton()
    if (!bb) return
    bb.show()
    bb.onClick(onBack)
    return () => {
      bb.offClick(onBack)
      bb.hide()
    }
  }, [onBack])

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="Заказ выбран">
      <div className="sheet__scroll handoff">
        <div className="handoff__mark" aria-hidden="true">
          <svg width="30" height="30" viewBox="0 0 24 24">
            <path d="M5 12.5l4.5 4.5L19 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>

        <span className="meta meta--accent">Чехол выбран</span>
        <h1 className="handoff__title">{item.name}</h1>
        <div className="handoff__model">
          <span className="meta">Модель</span>
          <span className="chip chip--on">{model}</span>
        </div>
        <p className="handoff__text">
          Дальше оформление продолжится в чате бота — это займёт пару минут:
        </p>

        <ol className="steps">
          {steps.map((s, i) => (
            <li className="step" key={s}>
              <span className="step__n">{i + 1}</span>
              <span className="step__t">{s}</span>
            </li>
          ))}
        </ol>
      </div>

      <div className="sheet__actions">
        <button className="btn btn--ghost" onClick={onBack}>
          В каталог
        </button>
        <button className="btn btn--primary" onClick={openBot}>
          Открыть бот
        </button>
      </div>
    </div>
  )
}
