import { useRef, useEffect, useState } from 'react'

import { ApiError, mediaUrl } from '../api'
import {
  type Broadcast,
  type Segment,
  STATUS_OPTIONS,
  createBroadcast,
  fetchBroadcasts,
  previewSegment,
  sendBroadcast,
  uploadBroadcastImage,
} from '../broadcastsApi'
import { StatLine } from '../ui'

const CHANNEL_LABEL: Record<string, string> = { tg: 'Telegram', max: 'MAX' }

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'short' })
}

function segmentSummary(s: Segment): string {
  const parts: string[] = []
  parts.push(s.channel ? CHANNEL_LABEL[s.channel] : 'Все каналы')
  if (s.only_with_orders) parts.push('с заказами')
  if (s.order_status) {
    const label = STATUS_OPTIONS.find((o) => o.value === s.order_status)?.label ?? s.order_status
    parts.push(label)
  }
  if (s.registered_from) parts.push(`с ${s.registered_from}`)
  if (s.registered_to) parts.push(`по ${s.registered_to}`)
  return parts.join(' · ')
}

export function Broadcasts() {
  const [items, setItems] = useState<Broadcast[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [composing, setComposing] = useState(false)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setItems(await fetchBroadcasts())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить рассылки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function onSend(b: Broadcast) {
    const count = b.recipients_count || '?'
    if (!confirm(`Отправить рассылку сегменту (${segmentSummary(b.segment)})? Получателей: ${count}.`))
      return
    try {
      const res = await sendBroadcast(b.id)
      const note = res.note ? `\n${res.note}` : ''
      alert(`Поставлено в очередь: ${res.delivered} получателей.${note}`)
      reload()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось отправить')
    }
  }

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Рассылки</h1>
        <button className="btn btn--primary" onClick={() => setComposing(true)}>
          Новая рассылка
        </button>
      </div>
      <p className="page__lead">
        Ручная отправка сообщения сегменту клиентов. Черновик можно проверить и отправить позже.
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && items.length === 0 && (
        <div className="empty">Рассылок пока нет. Создайте первую.</div>
      )}

      {!loading && !error && items.length > 0 && (
        <StatLine
          items={[
            { label: 'Отправлено', value: items.filter((b) => !b.is_draft).length },
            { label: 'Черновиков', value: items.filter((b) => b.is_draft).length },
            {
              label: 'Всего получателей',
              value: items.reduce((s, b) => s + (b.is_draft ? 0 : b.recipients_count), 0),
            },
          ]}
        />
      )}

      {!loading && !error && items.length > 0 && (
        <div className="tablewrap"><table className="table">
          <thead>
            <tr>
              <th>Сообщение</th>
              <th>Сегмент</th>
              <th>Получателей</th>
              <th>Статус</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((b) => (
              <tr key={b.id}>
                <td className="cell-clip">
                  <span className="bcast-cell">
                    {b.image_url && (
                      <img className="bcast-thumb" src={mediaUrl(b.image_url) ?? b.image_url} alt="" />
                    )}
                    <span className="bcast-cell__text">{b.text}</span>
                  </span>
                </td>
                <td className="muted">{segmentSummary(b.segment)}</td>
                <td className="strong">{b.is_draft ? '—' : b.recipients_count}</td>
                <td>
                  {b.is_draft ? (
                    <span className="badge">Черновик</span>
                  ) : (
                    <span className="badge badge--green">
                      Отправлено {b.sent_at && fmtDate(b.sent_at)}
                    </span>
                  )}
                </td>
                <td className="row-actions">
                  {b.is_draft && (
                    <button className="linkbtn" onClick={() => onSend(b)}>
                      Отправить
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}

      {composing && (
        <Composer
          onClose={() => setComposing(false)}
          onSaved={() => {
            setComposing(false)
            reload()
          }}
        />
      )}
    </div>
  )
}

function Composer({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [text, setText] = useState('')
  const [image, setImage] = useState<string | null>(null)
  const [imgBusy, setImgBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [channel, setChannel] = useState<'' | 'tg' | 'max'>('')
  const [status, setStatus] = useState('')
  const [onlyWithOrders, setOnlyWithOrders] = useState(false)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [count, setCount] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function buildSegment(): Segment {
    return {
      channel: channel || null,
      order_status: status || null,
      only_with_orders: onlyWithOrders,
      registered_from: from ? `${from}T00:00:00` : null,
      registered_to: to ? `${to}T23:59:59` : null,
    }
  }

  async function onPreview() {
    setError(null)
    try {
      const res = await previewSegment(buildSegment())
      setCount(res.recipients_count)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось посчитать аудиторию')
    }
  }

  async function pickImage(file?: File) {
    if (!file) return
    setError(null)
    setImgBusy(true)
    try {
      setImage(await uploadBroadcastImage(file))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить картинку')
    } finally {
      setImgBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function onSave() {
    if (!text.trim()) {
      setError('Введите текст сообщения')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await createBroadcast(text, buildSegment(), image)
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
          <h2 className="modal__title">Новая рассылка</h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal__body">
          <label className="field">
            <span className="field__label">Текст сообщения</span>
            <textarea
              className="input textarea"
              rows={5}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Например: Новая коллекция чехлов уже в каталоге ✨"
            />
          </label>

          <div className="field">
            <span className="field__label">Картинка (необязательно)</span>
            <div className="bcast-img">
              {image ? (
                <div className="bcast-img__preview">
                  <img src={mediaUrl(image) ?? image} alt="" />
                  <button
                    type="button"
                    className="bcast-img__rm"
                    onClick={() => setImage(null)}
                    aria-label="Убрать картинку"
                  >
                    ✕
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  className="btn btn--ghost btn--sm"
                  onClick={() => fileRef.current?.click()}
                  disabled={imgBusy}
                >
                  {imgBusy ? 'Загрузка…' : 'Загрузить картинку'}
                </button>
              )}
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                hidden
                onChange={(e) => pickImage(e.target.files?.[0])}
              />
            </div>
            <div className="field__hint">Уйдёт вложением к сообщению. Текст станет подписью.</div>
          </div>

          <div className="field__label" style={{ marginTop: 8 }}>
            Сегмент
          </div>
          <div className="grid2">
            <label className="field">
              <span className="field__label">Канал</span>
              <select
                className="input"
                value={channel}
                onChange={(e) => setChannel(e.target.value as '' | 'tg' | 'max')}
              >
                <option value="">Все каналы</option>
                <option value="tg">Telegram</option>
                <option value="max">MAX</option>
              </select>
            </label>
            <label className="field">
              <span className="field__label">Статус заказа</span>
              <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
                {STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="field__label">Регистрация с</span>
              <input
                type="date"
                className="input"
                value={from}
                onChange={(e) => setFrom(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="field__label">Регистрация по</span>
              <input
                type="date"
                className="input"
                value={to}
                onChange={(e) => setTo(e.target.value)}
              />
            </label>
          </div>
          <label className="field field--check">
            <input
              type="checkbox"
              checked={onlyWithOrders}
              onChange={(e) => setOnlyWithOrders(e.target.checked)}
            />
            <span>Только клиенты с заказами</span>
          </label>

          <div className="price-note">
            {count === null ? (
              <button className="linkbtn" onClick={onPreview}>
                Посчитать аудиторию
              </button>
            ) : (
              <>
                Аудитория: <strong>{count}</strong> получателей.{' '}
                <button className="linkbtn" onClick={onPreview}>
                  Пересчитать
                </button>
              </>
            )}
          </div>
          {error && <div className="login__error">{error}</div>}
        </div>
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={onSave} disabled={busy}>
            {busy ? 'Сохраняем…' : 'Сохранить черновик'}
          </button>
        </div>
      </div>
    </div>
  )
}
