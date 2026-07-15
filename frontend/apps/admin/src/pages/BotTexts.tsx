import { useEffect, useState } from 'react'

import { ApiError } from '../api'
import { type BotMessage, fetchBotMessages, updateBotMessage } from '../botTextsApi'
import { StatLine } from '../ui'

export function BotTexts() {
  const [items, setItems] = useState<BotMessage[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<BotMessage | null>(null)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setItems(await fetchBotMessages())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить тексты')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Тексты бота</h1>
      </div>
      <p className="page__lead">
        Редактируются без перепрограммирования. Плейсхолдеры вида {'{price}'} подставляются ботом.
      </p>

      {!loading && !error && items.length > 0 && (
        <StatLine
          items={[
            { label: 'Сообщений', value: items.length },
            { label: 'В Telegram', value: items.filter((m) => m.channel_tg).length },
            { label: 'В MAX', value: items.filter((m) => m.channel_max).length },
          ]}
        />
      )}

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && (
        <table className="table">
          <thead>
            <tr>
              <th>Код</th>
              <th>Когда отправляется</th>
              <th>Текст</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((m) => (
              <tr key={m.code} onClick={() => setEditing(m)}>
                <td>
                  <span className="chip chip--code">{m.code}</span>
                </td>
                <td className="muted">{m.trigger}</td>
                <td className="cell-clip">{m.text}</td>
                <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                  <button className="linkbtn" onClick={() => setEditing(m)}>
                    Изменить
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editing && (
        <MessageEditor
          message={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function MessageEditor({
  message,
  onClose,
  onSaved,
}: {
  message: BotMessage
  onClose: () => void
  onSaved: () => void
}) {
  const [text, setText] = useState(message.text)
  const [tg, setTg] = useState(message.channel_tg)
  const [max, setMax] = useState(message.channel_max)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setError(null)
    setBusy(true)
    try {
      await updateBotMessage(message.code, { text, channel_tg: tg, channel_max: max })
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card modal__card--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title">
            <span className="mono">{message.code}</span>
          </h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal__body">
          <div className="price-note">{message.trigger}</div>
          <label className="field">
            <span className="field__label">Текст сообщения</span>
            <textarea
              className="input textarea"
              rows={5}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <div className="grid2">
            <label className="field field--check">
              <input type="checkbox" checked={tg} onChange={(e) => setTg(e.target.checked)} />
              <span>Telegram</span>
            </label>
            <label className="field field--check">
              <input type="checkbox" checked={max} onChange={(e) => setMax(e.target.checked)} />
              <span>MAX</span>
            </label>
          </div>
          {error && <div className="login__error">{error}</div>}
        </div>
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={save} disabled={busy}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}
