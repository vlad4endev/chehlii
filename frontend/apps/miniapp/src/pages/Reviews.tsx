import { useEffect, useState } from 'react'

import { fetchReviews, type ReviewItem } from '@ui/api'
import { CaseMockup } from '@ui/CaseMockup'

// «Отзывы» — сетка карточек. Карточка по ТЗ: текст, фото чехла (опц.), имя, дата.
// Пытаемся взять опубликованные отзывы из API; при отсутствии эндпоинта — образцы.
// В образцах «фото чехла» показываем мокапом заказанного типа.
interface Displayable extends ReviewItem {
  mockup?: { name: string; isCustom: boolean }
}

const SAMPLES: Displayable[] = [
  { id: 1, name: 'Марина', date: '12.06', text: 'Заказывала кастом по своему рисунку — попали точь-в-точь. Качество печати супер.', mockup: { name: 'Арт-кастом', isCustom: true } },
  { id: 2, name: 'Илья', date: '03.06', text: 'Гравировка буквы аккуратная, чехол приятный на ощупь. Пришло быстро.', mockup: { name: 'Классика', isCustom: false } },
  { id: 3, name: 'Sofia', date: '28.05', text: 'Дизайнер помог доработать макет, всё согласовали в переписке. Рекомендую.' },
  { id: 4, name: 'Артём', date: '19.05', text: 'Взял в подарок с инициалами — реакция была именно та, на которую рассчитывал.', mockup: { name: 'Минимал', isCustom: false } },
]

export function Reviews() {
  const [items, setItems] = useState<Displayable[]>(SAMPLES)

  useEffect(() => {
    fetchReviews()
      .then((r) => {
        if (r.length) setItems(r)
      })
      .catch(() => {
        /* эндпоинта ещё нет — остаёмся на образцах */
      })
  }, [])

  return (
    <>
      <div className="pagehead">
        <span className="meta">Отзывы · {items.length}</span>
        <h2 className="pagehead__title">
          Что говорят <span className="serif-it">о нас</span>
        </h2>
      </div>

      <div className="grid">
        {items.map((r) => (
          <figure className="review" key={r.id}>
            {r.photoUrl ? (
              <div className="review__photo">
                <img src={r.photoUrl} alt="Фото чехла" />
              </div>
            ) : r.mockup ? (
              <div className="review__photo">
                <CaseMockup name={r.mockup.name} isCustom={r.mockup.isCustom} />
              </div>
            ) : null}

            <blockquote className="review__text">«{r.text}»</blockquote>
            <figcaption className="review__foot">
              <span className="review__avatar">{(r.name[0] ?? '?').toUpperCase()}</span>
              <span className="review__who">
                <span className="review__name">{r.name}</span>
                <span className="meta review__date">{r.date}</span>
              </span>
            </figcaption>
          </figure>
        ))}
      </div>
    </>
  )
}
