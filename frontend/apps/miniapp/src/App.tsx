import { useEffect, useMemo, useState } from 'react'

import type { CaseType } from '@ui/types'
import { fetchCatalog } from '@ui/api'
import { CatalogView } from '@ui/CatalogView'

import { useFavorites } from './store'
import { CaseDetail } from './pages/CaseDetail'
import { Why } from './pages/Why'
import { Reviews } from './pages/Reviews'

type Tab = 'catalog' | 'why' | 'reviews' | 'favorites'
type Status = 'loading' | 'error' | 'ready'

const TABS: { id: Tab; label: string }[] = [
  { id: 'catalog', label: 'Каталог' },
  { id: 'why', label: 'Зачем вам' },
  { id: 'reviews', label: 'Отзывы' },
  { id: 'favorites', label: 'Избранное' },
]

export function App() {
  const [tab, setTab] = useState<Tab>('catalog')
  const [items, setItems] = useState<CaseType[]>([])
  const [status, setStatus] = useState<Status>('loading')
  const [selected, setSelected] = useState<CaseType | null>(null)
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
        <div className="wordmark">
          ЧЕХЛ<span className="wordmark__accent">ИИ</span>
        </div>
        <p className="tagline">Индивидуальные чехлы на заказ</p>
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
          <CatalogView
            items={items}
            favorites={favorites.ids}
            onOpen={setSelected}
            onToggleFavorite={(i) => favorites.toggle(i.id)}
          />
        )}

        {status === 'ready' && tab === 'favorites' &&
          (favItems.length ? (
            <CatalogView
              items={favItems}
              favorites={favorites.ids}
              onOpen={setSelected}
              onToggleFavorite={(i) => favorites.toggle(i.id)}
            />
          ) : (
            <div className="state">
              Здесь появятся сохранённые чехлы. Нажмите ♡ на карточке в каталоге.
            </div>
          ))}

        {tab === 'why' && <Why />}
        {tab === 'reviews' && <Reviews />}
      </main>

      {selected && (
        <CaseDetail
          item={selected}
          isFavorite={favorites.ids.has(selected.id)}
          onToggleFavorite={() => favorites.toggle(selected.id)}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  )
}
