import { useEffect, useState } from 'react'

import { ApiError } from '../api'
import {
  type Trash as TrashData,
  fetchTrash,
  purgeClient,
  purgeOrder,
  restoreClient,
  restoreOrder,
} from '../trashApi'

const CHANNEL_LABEL: Record<string, string> = { tg: 'Telegram', max: 'MAX' }
const fmtDate = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '—'

export function Trash() {
  const [data, setData] = useState<TrashData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setData(await fetchTrash())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить корзину')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function run(key: string, fn: () => Promise<void>) {
    setBusy(key)
    try {
      await fn()
      await reload()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось выполнить действие')
    } finally {
      setBusy(null)
    }
  }

  const empty = data && data.clients.length === 0 && data.orders.length === 0

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Корзина</h1>
      </div>
      <p className="page__lead">
        Удалённые клиенты и заказы. Их можно восстановить или удалить окончательно.
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}
      {empty && <div className="empty">Корзина пуста.</div>}

      {data && data.clients.length > 0 && (
        <section className="trash-block">
          <div className="field__label">Клиенты · {data.clients.length}</div>
          <table className="table">
            <thead>
              <tr>
                <th>Клиент</th>
                <th>Канал</th>
                <th className="num">Заказы</th>
                <th>Удалён</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.clients.map((c) => (
                <tr key={c.id}>
                  <td className="strong">{c.nickname || c.phone || `#${c.id}`}</td>
                  <td>{CHANNEL_LABEL[c.channel] ?? c.channel}</td>
                  <td className="num">{c.number_orders}</td>
                  <td className="muted mono">{fmtDate(c.deleted_at)}</td>
                  <td className="row-actions">
                    <button
                      className="btn btn--ghost btn--sm"
                      disabled={busy === `rc${c.id}`}
                      onClick={() => run(`rc${c.id}`, () => restoreClient(c.id))}
                    >
                      Восстановить
                    </button>
                    <button
                      className="btn btn--danger btn--sm"
                      disabled={busy === `pc${c.id}`}
                      onClick={() => {
                        if (confirm(`Удалить клиента «${c.nickname || c.phone || c.id}» навсегда?`))
                          run(`pc${c.id}`, () => purgeClient(c.id))
                      }}
                    >
                      Удалить навсегда
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {data && data.orders.length > 0 && (
        <section className="trash-block">
          <div className="field__label">Заказы · {data.orders.length}</div>
          <table className="table">
            <thead>
              <tr>
                <th>№</th>
                <th>Клиент</th>
                <th>Чехол</th>
                <th>Статус</th>
                <th>Удалён</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {data.orders.map((o) => (
                <tr key={o.id}>
                  <td className="strong mono">#{o.id}</td>
                  <td>{o.client_name || '—'}</td>
                  <td>
                    {o.case_name || '—'}
                    {o.model_name && <span className="muted"> · {o.model_name}</span>}
                  </td>
                  <td className="muted">{o.status_label}</td>
                  <td className="muted mono">{fmtDate(o.deleted_at)}</td>
                  <td className="row-actions">
                    <button
                      className="btn btn--ghost btn--sm"
                      disabled={busy === `ro${o.id}`}
                      onClick={() => run(`ro${o.id}`, () => restoreOrder(o.id))}
                    >
                      Восстановить
                    </button>
                    <button
                      className="btn btn--danger btn--sm"
                      disabled={busy === `po${o.id}`}
                      onClick={() => {
                        if (confirm(`Удалить заказ #${o.id} навсегда?`))
                          run(`po${o.id}`, () => purgeOrder(o.id))
                      }}
                    >
                      Удалить навсегда
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}
