// «Отзывы» — сетка карточек (как каталог). Эндпоинт отзывов с модерацией — Спринт 6;
// пока образцы для вёрстки. Структура карточки соответствует ТЗ (текст, автор, фото).
const SAMPLES = [
  { id: 1, name: 'Марина', text: 'Заказывала кастом по своему рисунку — попали точь-в-точь. Качество печати супер.', letter: 'М' },
  { id: 2, name: 'Илья', text: 'Гравировка буквы аккуратная, чехол приятный на ощупь. Пришло быстро.', letter: 'И' },
  { id: 3, name: 'Sofia', text: 'Дизайнер помог доработать макет, всё согласовали в переписке. Рекомендую.', letter: 'S' },
  { id: 4, name: 'Артём', text: 'Взял в подарок с инициалами — реакция была именно та, на которую рассчитывал.', letter: 'А' },
]

export function Reviews() {
  return (
    <div className="grid">
      {SAMPLES.map((r) => (
        <figure className="review" key={r.id}>
          <span className="review__avatar">{r.letter}</span>
          <blockquote className="review__text">«{r.text}»</blockquote>
          <figcaption className="review__author">{r.name}</figcaption>
        </figure>
      ))}
    </div>
  )
}
