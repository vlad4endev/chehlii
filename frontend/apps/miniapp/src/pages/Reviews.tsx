// «Отзывы» — сетка карточек (как каталог). Карточка по ТЗ: текст, фото (опц.),
// имя, дата. Эндпоинт с модерацией — Спринт 6; пока образцы для вёрстки.
interface Review {
  id: number
  name: string
  text: string
  date: string
  letter: string
}

const SAMPLES: Review[] = [
  { id: 1, name: 'Марина', date: '12.06', text: 'Заказывала кастом по своему рисунку — попали точь-в-точь. Качество печати супер.', letter: 'М' },
  { id: 2, name: 'Илья', date: '03.06', text: 'Гравировка буквы аккуратная, чехол приятный на ощупь. Пришло быстро.', letter: 'И' },
  { id: 3, name: 'Sofia', date: '28.05', text: 'Дизайнер помог доработать макет, всё согласовали в переписке. Рекомендую.', letter: 'S' },
  { id: 4, name: 'Артём', date: '19.05', text: 'Взял в подарок с инициалами — реакция была именно та, на которую рассчитывал.', letter: 'А' },
]

export function Reviews() {
  return (
    <>
      <div className="pagehead">
        <span className="meta">Отзывы · {SAMPLES.length}</span>
        <h2 className="pagehead__title">
          Что говорят <span className="serif-it">о нас</span>
        </h2>
      </div>

      <div className="grid">
        {SAMPLES.map((r) => (
          <figure className="review" key={r.id}>
            <blockquote className="review__text">«{r.text}»</blockquote>
            <figcaption className="review__foot">
              <span className="review__avatar">{r.letter}</span>
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
