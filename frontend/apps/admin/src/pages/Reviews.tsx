import { useEffect, useState } from 'react'

import { ApiError } from '../api'
import { type ReviewAdmin, type ReviewStatus, fetchReviews, moderate } from '../reviewsApi'
import { Avatar, StatLine } from '../ui'

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' })

const FILTERS: { value: '' | ReviewStatus; label: string }[] = [
  { value: '', label: 'Все' },
  { value: 'pending', label: 'На модерации' },
  { value: 'published', label: 'Опубликованные' },
  { value: 'rejected', label: 'Отклонённые' },
]

function badgeClass(s: ReviewStatus): string {
  if (s === 'published') return 'badge badge--green'
  if (s === 'rejected') return 'badge badge--red'
  return 'badge'
}

export function Reviews() {
  const [items, setItems] = useState<ReviewAdmin[]>([])
  const [filter, setFilter] = useState<'' | ReviewStatus>('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setItems(await fetchReviews(filter || undefined))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить отзывы')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  async function setStatus(r: ReviewAdmin, status: ReviewStatus) {
    setBusyId(r.id)
    try {
      await moderate(r.id, status)
      await reload()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось изменить статус')
    } finally {
      setBusyId(null)
    }
  }

  const pending = items.filter((r) => r.status === 'pending').length

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">
          Отзывы {pending > 0 && <span className="count-badge">{pending} на модерации</span>}
        </h1>
      </div>

      {!loading && !error && items.length > 0 && (
        <StatLine
          items={[
            { label: 'На модерации', value: items.filter((r) => r.status === 'pending').length },
            { label: 'Опубликовано', value: items.filter((r) => r.status === 'published').length },
            { label: 'Отклонено', value: items.filter((r) => r.status === 'rejected').length },
          ]}
        />
      )}

      <div className="segmented">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            className={`segmented__btn${filter === f.value ? ' segmented__btn--active' : ''}`}
            onClick={() => setFilter(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && (
        <div className="reviews-list">
          {items.map((r) => (
            <div className="rcard" key={r.id}>
              <div className="rcard__body">
                <div className="rcard__top">
                  <Avatar name={r.author_name || 'Аноним'} />
                  <span className="rcard__author">{r.author_name || 'Аноним'}</span>
                  <span className="rcard__date">{fmtDate(r.created_at)}</span>
                  <span className={badgeClass(r.status)}>{r.status_label}</span>
                </div>
                <p className="rcard__text">{r.text}</p>
                {r.photo_url && (
                  <a className="linkbtn" href={r.photo_url} target="_blank" rel="noreferrer">
                    Фото чехла ↗
                  </a>
                )}
              </div>
              <div className="rcard__actions">
                {r.status !== 'published' && (
                  <button
                    className="btn btn--primary btn--sm"
                    disabled={busyId === r.id}
                    onClick={() => setStatus(r, 'published')}
                  >
                    Одобрить
                  </button>
                )}
                {r.status !== 'rejected' && (
                  <button
                    className="btn btn--ghost btn--sm"
                    disabled={busyId === r.id}
                    onClick={() => setStatus(r, 'rejected')}
                  >
                    Отклонить
                  </button>
                )}
              </div>
            </div>
          ))}
          {items.length === 0 && <div className="empty">Отзывов нет.</div>}
        </div>
      )}
    </div>
  )
}
