import { useEffect, useState } from 'react'

import { ApiError } from '../api'
import { type JourneyRow, fetchJourneys } from '../journeysApi'

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

export function Journeys() {
  const [items, setItems] = useState<JourneyRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchJourneys()
      .then(setItems)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить'))
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Клиентские пути</h1>
      </div>
      <p className="page__lead">
        Клиенты в диалоге бота: на каком коде сообщения остановились и когда.
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}
      {!loading && !error && items.length === 0 && (
        <div className="empty">Активных сессий пока нет.</div>
      )}

      {!loading && !error && items.length > 0 && (
        <div className="tablewrap">
          <table className="table">
            <thead>
              <tr>
                <th>Клиент</th>
                <th>Канал</th>
                <th>Последнее сообщение</th>
                <th>Код сообщения</th>
                <th>Промокод</th>
              </tr>
            </thead>
            <tbody>
              {items.map((j) => (
                <tr key={j.client_id}>
                  <td className="strong">
                    {j.nickname || j.phone || `#${j.client_id}`}
                    {j.nickname && j.phone && (
                      <span className="muted mono" style={{ marginLeft: 6, fontSize: 12 }}>
                        {j.phone}
                      </span>
                    )}
                  </td>
                  <td>{CHANNEL_LABEL[j.channel] ?? j.channel}</td>
                  <td className="mono muted">{fmtDate(j.last_msg_at)}</td>
                  <td>
                    <span className="chip mono">{j.last_msg_code ?? '—'}</span>
                  </td>
                  <td className="mono">{j.master_code ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
