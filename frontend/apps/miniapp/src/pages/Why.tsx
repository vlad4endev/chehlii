// «Зачем вам индивидуальный чехол»: главная картинка (из AdminUI) + ценность + «О нас».
import { useEffect, useState } from 'react'

import { mediaUrl } from '@ui/api'

const API_BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api/v1'

interface Hero {
  image_url: string | null
  title: string | null
}

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
  const [hero, setHero] = useState<Hero | null>(null)
  useEffect(() => {
    fetch(`${API_BASE}/miniapp/hero`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setHero)
      .catch(() => {})
  }, [])
  const heroUrl = hero?.image_url ? mediaUrl(hero.image_url) : null

  return (
    <div className="why">
      {heroUrl && (
        <div className="hero-image">
          <img src={heroUrl} alt={hero?.title ?? ''} />
          {hero?.title && <div className="hero-image__caption">{hero.title}</div>}
        </div>
      )}
      <div className="pagehead">
        <span className="meta">Почему мы</span>
        <h1 className="pagehead__title pagehead__title--xl">
          Зачем вам <span className="serif-it">индивидуальный</span> чехол
        </h1>
        <p className="why__lead">
          Чехол — то, что вы держите в руках сотни раз в день. Пусть он будет про вас, а не про
          завод, где его отштамповали тысячным тиражом.
        </p>
      </div>

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
        <span className="meta">О нас</span>
        <p className="about__lead">
          Небольшая мастерская, которая делает чехлы под каждого клиента — от лаконичной гравировки
          до полностью авторского дизайна.
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
