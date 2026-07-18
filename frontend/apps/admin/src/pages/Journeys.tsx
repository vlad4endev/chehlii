import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'

import { ApiError } from '../api'
import { fetchBotMessages } from '../botTextsApi'
import { type JourneyRow, fetchJourneys } from '../journeysApi'

// Tooltip через portal — не обрезается overflow родителя.
function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  return (
    <>
      <span
        className="chip mono has-tip"
        onMouseEnter={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          setPos({ x: r.left + r.width / 2, y: r.top })
        }}
        onMouseLeave={() => setPos(null)}
      >
        {children}
      </span>
      {pos &&
        createPortal(
          <div className="tip-pop" style={{ left: pos.x, top: pos.y }}>
            {text}
          </div>,
          document.body,
        )}
    </>
  )
}

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
  const [msgText, setMsgText] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([
      fetchJourneys(),
      fetchBotMessages().catch(() => []),
    ])
      .then(([js, msgs]) => {
        setItems(js)
        setMsgText(Object.fromEntries(msgs.map((m) => [m.code, m.text])))
      })
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
                    {j.last_msg_code ? (
                      <Tip text={msgText[j.last_msg_code] ?? '(текст не найден)'}>
                        {j.last_msg_code}
                      </Tip>
                    ) : (
                      <span className="chip mono">—</span>
                    )}
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
