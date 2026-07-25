// Полноразмерный премиум-лендинг casetop для обычного браузера.
// В Telegram/MAX WebApp вместо него показывается табовый интерфейс (см. App.tsx).
import { useEffect, useRef, useState } from 'react'

import type { CaseType } from '@ui/types'
import { fetchReviews, mediaUrl, type ReviewItem } from '@ui/api'

const API_BASE = (import.meta.env.VITE_API_BASE ?? '') + '/api/v1'
// Дефолты — тестовые боты. Заменяются через .env (VITE_TG_URL / VITE_MAX_URL).
const TG_URL = (import.meta.env.VITE_TG_URL as string | undefined) ?? 'https://t.me/chehltest_bot'
const MAX_URL = (import.meta.env.VITE_MAX_URL as string | undefined) ?? 'https://max.ru/id682401246838_bot'

interface Hero {
  image_url: string | null
  title: string | null
}

// Хук: подписка на IntersectionObserver — узнаём когда элемент попал в кадр.
function useReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) if (e.isIntersecting) el.classList.add('is-in')
      },
      { threshold: 0.15 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return ref
}

export function Landing({ items }: { items: CaseType[] }) {
  const [hero, setHero] = useState<Hero | null>(null)
  const [reviews, setReviews] = useState<ReviewItem[]>([])
  const [scrolled, setScrolled] = useState(false)
  const heroCaseRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API_BASE}/miniapp/hero`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setHero)
      .catch(() => {})
    fetchReviews().then(setReviews).catch(() => {})
    const onScroll = () => setScrolled(window.scrollY > 20)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  // Мышь → параллакс героя (лёгкий наклон, без библиотек).
  useEffect(() => {
    const el = heroCaseRef.current
    if (!el) return
    function move(e: MouseEvent) {
      if (!el) return
      const r = el.getBoundingClientRect()
      const cx = r.left + r.width / 2
      const cy = r.top + r.height / 2
      const dx = (e.clientX - cx) / r.width
      const dy = (e.clientY - cy) / r.height
      el.style.setProperty('--rx', `${(-dy * 8).toFixed(2)}deg`)
      el.style.setProperty('--ry', `${(dx * 10).toFixed(2)}deg`)
    }
    window.addEventListener('mousemove', move)
    return () => window.removeEventListener('mousemove', move)
  }, [])

  const heroImg = hero?.image_url ? mediaUrl(hero.image_url) : null
  const withPhoto = items.filter((i) => i.photo_url || i.models.some((m) => m.photo_url))
  const gallery = (withPhoto.length ? withPhoto : items).slice(0, 8)

  const openTg = () => TG_URL && window.open(TG_URL, '_blank', 'noopener')
  const openMax = () => MAX_URL && window.open(MAX_URL, '_blank', 'noopener')

  return (
    <div className="lp">
      {/* ── Навбар ── */}
      <header className={`lp-nav${scrolled ? ' lp-nav--scrolled' : ''}`}>
        <div className="lp-nav__inner">
          <a href="#top" className="lp-nav__brand">casetop</a>
          <nav className="lp-nav__links">
            <a href="#gallery">Каталог</a>
            <a href="#how">Как</a>
            <a href="#reviews">Отзывы</a>
          </nav>
          <div className="lp-nav__cta">
            <button className="lp-btn lp-btn--ghost" onClick={openMax} disabled={!MAX_URL}>MAX</button>
            <button className="lp-btn lp-btn--dark" onClick={openTg} disabled={!TG_URL}>Telegram</button>
          </div>
        </div>
      </header>

      {/* ── Hero ── */}
      <section id="top" className="lp-hero">
        <div className="lp-hero__blob lp-hero__blob--a" />
        <div className="lp-hero__blob lp-hero__blob--b" />
        <div className="lp-hero__grid">
          <div className="lp-hero__copy">
            <span className="lp-eyebrow">
              <span className="lp-dot" /> casetop · индивидуальные чехлы
            </span>
            <h1 className="lp-hero__title">
              <span className="lp-word lp-word--1">Чехол,</span>{' '}
              <span className="lp-word lp-word--2">который</span>{' '}
              <em className="lp-serif lp-word lp-word--3">узнают</em>{' '}
              <span className="lp-word lp-word--4">за секунду.</span>
            </h1>
            <p className="lp-hero__sub lp-word lp-word--5">
              Гравировка, авторский принт, только ваши модели iPhone. Заказ — в{' '}
              <em className="lp-serif">Telegram</em> или <em className="lp-serif">MAX</em>, чехол — у вас.
            </p>
            <div className="lp-hero__cta lp-word lp-word--6">
              <button className="lp-btn lp-btn--dark lp-btn--lg" onClick={openTg} disabled={!TG_URL}>
                Открыть в Telegram <span className="lp-arrow">→</span>
              </button>
              <button className="lp-btn lp-btn--ghost lp-btn--lg" onClick={openMax} disabled={!MAX_URL}>
                Открыть в MAX
              </button>
            </div>
            <div className="lp-hero__meta lp-word lp-word--7">
              <span><b>iPhone 14 — 17 Air</b> · все модели</span>
              <span><b>3–5 дней</b> · от заказа до отправки</span>
            </div>
          </div>

          <div className="lp-hero__visual">
            <div className="lp-hero__stage" ref={heroCaseRef}>
              <div className="lp-hero__glow" />
              {heroImg ? (
                <img className="lp-hero__img" src={heroImg} alt={hero?.title ?? ''} />
              ) : (
                <div className="lp-hero__placeholder">
                  <span className="lp-serif">casetop</span>
                </div>
              )}
              {hero?.title && <div className="lp-hero__caption">{hero.title}</div>}
              <div className="lp-hero__badge">
                <span className="lp-hero__badge-num">01</span>
                <span>ручная работа</span>
              </div>
              <div className="lp-hero__tag">под iPhone</div>
            </div>
          </div>
        </div>

        <div className="lp-scrollhint">
          <span>прокрутите</span>
          <span className="lp-scrollhint__line" />
        </div>
      </section>

      {/* ── Marquee строка ценности ── */}
      <section className="lp-marquee" aria-hidden="true">
        <div className="lp-marquee__row">
          {Array.from({ length: 3 }).map((_, i) => (
            <div className="lp-marquee__group" key={i}>
              <span>Гравировка имени</span><span className="lp-marquee__sep">✦</span>
              <span>Авторский принт</span><span className="lp-marquee__sep">✦</span>
              <span>iPhone 14 — 17 Air</span><span className="lp-marquee__sep">✦</span>
              <span>Ручная сборка</span><span className="lp-marquee__sep">✦</span>
              <span>Матовый и глянец</span><span className="lp-marquee__sep">✦</span>
              <span>Подарок под ключ</span><span className="lp-marquee__sep">✦</span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Bento: почему casetop ── */}
      <Section className="lp-bento">
        <SectionHead eyebrow="почему casetop" title={<>Не аксессуар — <em className="lp-serif">вещь про вас</em>.</>} />
        <div className="lp-bento__grid">
          <BentoCell size="lg" title="Кастом-дизайн" text="Присылаете фото и идею — дизайнер собирает макет, вы согласовываете. Печать по вашему изображению.">
            <div className="lp-bento__art lp-bento__art--sketch" />
          </BentoCell>
          <BentoCell size="md" title="Гравировка" text="Имя, инициал, монограмма. Тонко и навсегда.">
            <div className="lp-bento__art lp-bento__art--engrave" />
          </BentoCell>
          <BentoCell size="sm" title="Все iPhone" text="От 14 до 17 Air — под вашу модель." />
          <BentoCell size="sm" title="Финиши" text="Матовый · Глянец · Тактильный полимер." />
          <BentoCell size="md" title="Быстро" text="3–5 дней от согласования до отправки в СДЭК." />
          <BentoCell size="sm" title="Подарок" text="Красивая упаковка. Открыл — и уже подарок." />
        </div>
      </Section>

      {/* ── How it works ── */}
      <Section id="how" className="lp-how" dark>
        <SectionHead eyebrow="как это работает" title={<>Четыре шага — <em className="lp-serif">и чехол в руках</em>.</>} onDark />
        <ol className="lp-steps">
          {[
            { n: '01', t: 'Открываете бота', d: 'В Telegram или MAX — по кнопке ниже. Показываем каталог, выбираете тип и модель.' },
            { n: '02', t: 'Дизайнер собирает макет', d: 'Присылаете идею — получаете макет за 1–2 дня. Правки — до согласования.' },
            { n: '03', t: 'Оплата и производство', d: 'Предоплата по ссылке из бота. Собираем чехол вручную под вашу модель.' },
            { n: '04', t: 'Доставка СДЭК', d: 'Отправляем по России. Трек-номер приходит в бот, статус — до двери.' },
          ].map((s) => (
            <Reveal as="li" className="lp-step" key={s.n}>
              <span className="lp-step__num">{s.n}</span>
              <div>
                <h3 className="lp-step__title">{s.t}</h3>
                <p className="lp-step__text">{s.d}</p>
              </div>
            </Reveal>
          ))}
        </ol>
      </Section>

      {/* ── Gallery ── */}
      {gallery.length > 0 && (
        <Section id="gallery" className="lp-gallery">
          <SectionHead eyebrow="каталог" title={<>Из тех, что <em className="lp-serif">уже сделали</em>.</>} />
          <div className="lp-gallery__grid">
            {gallery.map((c) => (
              <GalleryCard key={c.id} item={c} />
            ))}
          </div>
          <div className="lp-center">
            <button className="lp-btn lp-btn--dark lp-btn--lg" onClick={openTg} disabled={!TG_URL}>
              Смотреть весь каталог в боте <span className="lp-arrow">→</span>
            </button>
          </div>
        </Section>
      )}

      {/* ── Reviews ── */}
      {reviews.length > 0 && (
        <Section id="reviews" className="lp-reviews">
          <SectionHead eyebrow="отзывы" title={<>Что <em className="lp-serif">говорят</em> клиенты.</>} />
          <div className="lp-reviews__grid">
            {reviews.slice(0, 6).map((r) => (
              <Reveal as="figure" className="lp-review" key={r.id}>
                <blockquote className="lp-review__text">«{r.text}»</blockquote>
                <figcaption className="lp-review__meta">
                  <span className="lp-review__name">{r.name}</span>
                  {r.date && <span className="lp-review__date">{r.date}</span>}
                </figcaption>
              </Reveal>
            ))}
          </div>
        </Section>
      )}

      {/* ── Финальный CTA ── */}
      <section className="lp-cta">
        <div className="lp-cta__inner">
          <h2 className="lp-cta__title">
            Начните с чехла,{' '}
            <em className="lp-serif">который узнают за секунду</em>.
          </h2>
          <div className="lp-cta__buttons">
            <button className="lp-btn lp-btn--light lp-btn--lg" onClick={openTg} disabled={!TG_URL}>
              Открыть в Telegram <span className="lp-arrow">→</span>
            </button>
            <button className="lp-btn lp-btn--outline-light lp-btn--lg" onClick={openMax} disabled={!MAX_URL}>
              Открыть в MAX
            </button>
          </div>
          <p className="lp-cta__note">Бесплатная консультация в чате · Оплата в один клик</p>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="lp-foot">
        <div className="lp-foot__inner">
          <div className="lp-foot__brand">casetop</div>
          <div className="lp-foot__cols">
            <div>
              <div className="lp-foot__head">Продукт</div>
              <a href="#gallery">Каталог</a>
              <a href="#how">Как заказать</a>
              <a href="#reviews">Отзывы</a>
            </div>
            <div>
              <div className="lp-foot__head">Мессенджеры</div>
              {TG_URL && <a href={TG_URL} target="_blank" rel="noreferrer">Telegram</a>}
              {MAX_URL && <a href={MAX_URL} target="_blank" rel="noreferrer">MAX</a>}
            </div>
          </div>
          <div className="lp-foot__copy">© {new Date().getFullYear()} casetop — индивидуальные чехлы</div>
        </div>
      </footer>
    </div>
  )
}

/* ── Мелкие переиспользуемые части ── */

function Section({
  id, className, dark, children,
}: {
  id?: string; className?: string; dark?: boolean; children: React.ReactNode
}) {
  return (
    <section id={id} className={`lp-sec${dark ? ' lp-sec--dark' : ''} ${className ?? ''}`}>
      <div className="lp-sec__inner">{children}</div>
    </section>
  )
}

function SectionHead({
  eyebrow, title, onDark,
}: {
  eyebrow: string; title: React.ReactNode; onDark?: boolean
}) {
  const ref = useReveal<HTMLDivElement>()
  return (
    <div className={`lp-head${onDark ? ' lp-head--dark' : ''} reveal`} ref={ref}>
      <span className="lp-eyebrow">{eyebrow}</span>
      <h2 className="lp-h2">{title}</h2>
    </div>
  )
}

function BentoCell({
  size, title, text, children,
}: {
  size: 'sm' | 'md' | 'lg'; title: string; text: string; children?: React.ReactNode
}) {
  const ref = useReveal<HTMLDivElement>()
  return (
    <div className={`lp-bento__cell lp-bento__cell--${size} reveal`} ref={ref}>
      {children}
      <h3 className="lp-bento__title">{title}</h3>
      <p className="lp-bento__text">{text}</p>
    </div>
  )
}

function Reveal<T extends 'div' | 'li' | 'figure'>({
  as, className, children,
}: {
  as: T; className?: string; children: React.ReactNode
}) {
  const ref = useReveal<HTMLElement>()
  const Tag = as as unknown as React.ElementType
  return (
    <Tag ref={ref} className={`reveal ${className ?? ''}`}>
      {children}
    </Tag>
  )
}

function GalleryCard({ item }: { item: CaseType }) {
  const ref = useReveal<HTMLDivElement>()
  const [tilt, setTilt] = useState({ x: 0, y: 0 })
  const photo =
    mediaUrl(item.photo_url ?? item.models.find((m) => m.photo_url)?.photo_url ?? '')
  return (
    <div
      ref={ref}
      className="lp-gcard reveal"
      onMouseMove={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        setTilt({
          x: ((e.clientY - r.top - r.height / 2) / r.height) * -6,
          y: ((e.clientX - r.left - r.width / 2) / r.width) * 6,
        })
      }}
      onMouseLeave={() => setTilt({ x: 0, y: 0 })}
      style={{ transform: `perspective(900px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)` }}
    >
      <div className="lp-gcard__media">
        {photo ? (
          <img src={photo} alt={item.name} loading="lazy" />
        ) : (
          <div className="lp-gcard__ph"><span className="lp-serif">{item.name[0]}</span></div>
        )}
      </div>
      <div className="lp-gcard__body">
        <span className={`lp-chip${item.is_custom ? ' lp-chip--accent' : ''}`}>
          {item.is_custom ? 'Кастом' : 'Минимализм'}
        </span>
        <h3 className="lp-gcard__name">{item.name}</h3>
      </div>
    </div>
  )
}
