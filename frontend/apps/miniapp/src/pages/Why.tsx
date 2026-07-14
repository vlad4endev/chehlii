// Страница «Зачем вам индивидуальный чехол»: ценность (текст + картинки) + раздел «О нас».
// Картинки — плейсхолдеры-монограммы, заменяются реальными фото через AdminUI.
// Картинки — плейсхолдеры в монограммном стиле (буква из заголовка), заменяются
// реальными фото через AdminUI.
const REASONS = [
  {
    title: 'Он только ваш',
    text: 'Имя, буква или свой рисунок — такого чехла нет больше ни у кого. Вещь, которую узнают сразу.',
  },
  {
    title: 'Подарок, который помнят',
    text: 'Персональный чехол под конкретного человека — внимательнее, чем очередной аксессуар с полки.',
  },
  {
    title: 'Защита и характер',
    text: 'Бережёт телефон и говорит о вкусе владельца. Функция и стиль в одном предмете.',
  },
]

export function Why() {
  return (
    <div className="why">
      <header className="why__hero">
        <h1 className="why__title">Зачем вам индивидуальный чехол</h1>
        <p className="why__lead">
          Чехол — это то, что вы держите в руках сотни раз в день. Пусть он будет про вас, а не
          про завод, где его отштамповали тысячным тиражом.
        </p>
      </header>

      <div className="why__reasons">
        {REASONS.map((r) => (
          <article className="reason" key={r.title}>
            <div className="monogram reason__media">
              <span className="monogram__letter">{r.title[0]}</span>
              <span className="monogram__ring" />
            </div>
            <div>
              <h2 className="reason__title">{r.title}</h2>
              <p className="reason__text">{r.text}</p>
            </div>
          </article>
        ))}
      </div>

      <section className="about">
        <h2 className="about__h">О нас</h2>
        <p className="about__lead">
          Небольшая мастерская, которая делает чехлы под каждого клиента — от лаконичной
          гравировки до полностью авторского дизайна.
        </p>

        <div className="about__ways">
          <div className="about__way">
            <div className="monogram about__img">
              <span className="monogram__letter">A</span>
              <span className="monogram__ring" />
            </div>
            <h3 className="about__wayh">Стандарт</h3>
            <p className="about__wayt">Гравировка имени или буквы. Быстрый путь к вещи, которая выглядит как ваша.</p>
          </div>
          <div className="about__way">
            <div className="monogram about__img">
              <span className="monogram__letter">✦</span>
              <span className="monogram__ring" />
            </div>
            <h3 className="about__wayh">Кастом</h3>
            <p className="about__wayt">Присылаете фото и пожелания — дизайнер собирает макет, вы согласовываете.</p>
          </div>
        </div>
      </section>
    </div>
  )
}
