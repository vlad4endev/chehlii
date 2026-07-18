import { useEffect, useMemo, useState } from 'react'

import type { CaseType } from '@ui/types'
import { fetchCatalog, plural } from '@ui/api'
import { CatalogView } from '@ui/CatalogView'

import { useFavorites } from './store'
import { CaseDetail } from './pages/CaseDetail'
import { OrderHandoff } from './pages/OrderHandoff'
import { Why } from './pages/Why'
import { Reviews } from './pages/Reviews'

type Tab = 'catalog' | 'why' | 'reviews' | 'favorites'
type Status = 'loading' | 'error' | 'ready'

// Порядок вкладок: сначала инфо (Зачем вам, Отзывы), затем Каталог, потом Избранное.
const TABS: { id: Tab; label: string }[] = [
  { id: 'why', label: 'Зачем вам' },
  { id: 'reviews', label: 'Отзывы' },
  { id: 'catalog', label: 'Каталог' },
  { id: 'favorites', label: 'Избранное' },
]

export function App() {
  const [tab, setTab] = useState<Tab>('why')
  const [items, setItems] = useState<CaseType[]>([])
  const [status, setStatus] = useState<Status>('loading')
  const [selected, setSelected] = useState<CaseType | null>(null)
  const [ordered, setOrdered] = useState<{ item: CaseType; model: string } | null>(null)
  const favorites = useFavorites()

  useEffect(() => {
    fetchCatalog()
      .then((data) => {
        setItems(data)
        setStatus('ready')
      })
      .catch(() => setStatus('error'))
  }, [])

  const favItems = useMemo(() => items.filter((i) => favorites.ids.has(i.id)), [items, favorites.ids])

  return (
    <div className="app">
      <header className="header">
        <div className="wordmark">casetop</div>
        <p className="tagline">
          Индивидуальные чехлы <span className="serif-it">уникального дизайна</span> для вас и близких
        </p>
      </header>

      <nav className="nav" aria-label="Разделы">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`nav__tab${tab === t.id ? ' nav__tab--active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
            {t.id === 'favorites' && favorites.ids.size > 0 && (
              <span className="nav__count">{favorites.ids.size}</span>
            )}
          </button>
        ))}
      </nav>

      <main className="main">
        {status === 'loading' && <div className="state">Загружаем каталог…</div>}
        {status === 'error' && (
          <div className="state">
            Не удалось загрузить каталог. Проверьте соединение и обновите страницу.
          </div>
        )}

        {status === 'ready' && tab === 'catalog' && (
          <>
            <section className="hero">
              <div className="hero__glow" aria-hidden="true" />
              <div className="hero__orb" aria-hidden="true">
                <span>c</span>
              </div>
              <span className="meta hero__eyebrow">
                {items.length} {plural(items.length, ['тип', 'типа', 'типов'])} · под вас
              </span>
              <h2 className="hero__title">
                Носите то, что <span className="serif-it">только ваше</span>
              </h2>
              <p className="hero__sub">Дизайнерские чехлы с гравировкой и авторским принтом.</p>
            </section>
            <CatalogView
              items={items}
              favorites={favorites.ids}
              onOpen={setSelected}
              onToggleFavorite={(i) => favorites.toggle(i.id)}
            />
          </>
        )}

        {status === 'ready' && tab === 'favorites' && (
          <>
            <div className="pagehead">
              <span className="meta">Избранное · {favItems.length}</span>
              <h2 className="pagehead__title">Сохранённое</h2>
            </div>
            {favItems.length ? (
              <CatalogView
                items={favItems}
                favorites={favorites.ids}
                onOpen={setSelected}
                onToggleFavorite={(i) => favorites.toggle(i.id)}
              />
            ) : (
              <div className="state">
                Пока пусто. Нажмите на сердечко у чехла в каталоге — он появится здесь.
              </div>
            )}
          </>
        )}

        {tab === 'why' && <Why />}
        {tab === 'reviews' && <Reviews />}
      </main>

      {selected && (
        <CaseDetail
          item={selected}
          isFavorite={favorites.ids.has(selected.id)}
          onToggleFavorite={() => favorites.toggle(selected.id)}
          onClose={() => setSelected(null)}
          onOrdered={(model) => {
            setOrdered({ item: selected, model })
            setSelected(null)
          }}
        />
      )}

      {ordered && (
        <OrderHandoff item={ordered.item} model={ordered.model} onBack={() => setOrdered(null)} />
      )}
    </div>
  )
}
