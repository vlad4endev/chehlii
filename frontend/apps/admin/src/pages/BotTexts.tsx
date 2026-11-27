import { useEffect, useRef, useState } from 'react'

import { ApiError, apiUpload, mediaUrl } from '../api'
import { type BotMessage, fetchBotMessages, updateBotMessage } from '../botTextsApi'
import { StatLine } from '../ui'

const MEDIA_FORMATS: { value: string; label: string }[] = [
  { value: 'text', label: 'Только текст' },
  { value: 'video_note', label: 'Кружок + подсказка' },
  { value: 'video_note_text', label: 'Кружок + текст сообщения' },
]

const MEDIA_CODES = new Set(['msg_001', 'welcome_back'])

export function BotTexts({ embedded = false }: { embedded?: boolean } = {}) {
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
      {!embedded && (
        <div className="page__head">
          <h1 className="page__title">Тексты бота</h1>
        </div>
      )}
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
        <div className="tablewrap"><table className="table">
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
                  {m.media_format && m.media_format !== 'text' && (
                    <span className="chip" style={{ marginLeft: 6 }}>кружок</span>
                  )}
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
        </table></div>
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
  const [mediaFormat, setMediaFormat] = useState(message.media_format || 'text')
  const [mediaUrlVal, setMediaUrlVal] = useState(message.media_url)
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const showMedia = MEDIA_CODES.has(message.code)

  async function onVideo(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setUploading(true)
    setError(null)
    try {
      const r = await apiUpload<{ url: string }>('/admin/media', f)
      setMediaUrlVal(r.url)
      if (mediaFormat === 'text') setMediaFormat('video_note')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить видео')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function save() {
    setError(null)
    setBusy(true)
    try {
      const body: Parameters<typeof updateBotMessage>[1] = {
        text,
        channel_tg: tg,
        channel_max: max,
      }
      if (showMedia) {
        body.media_format = mediaFormat
        body.media_url = mediaUrlVal
        if (mediaFormat === 'text' || !mediaUrlVal) {
          body.clear_media = mediaFormat === 'text'
        }
      }
      await updateBotMessage(message.code, body)
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
          <button className="modal__close" onClick={onClose} aria-label="Закрыть">
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
          {showMedia && (
            <>
              <label className="field">
                <span className="field__label">Формат при /start</span>
                <select
                  className="input"
                  value={mediaFormat}
                  onChange={(e) => setMediaFormat(e.target.value)}
                >
                  {MEDIA_FORMATS.map((f) => (
                    <option key={f.value} value={f.value}>
                      {f.label}
                    </option>
                  ))}
                </select>
              </label>
              {mediaFormat !== 'text' && (
                <div className="field">
                  <span className="field__label">Видео для кружка (Telegram)</span>
                  {mediaUrlVal ? (
                    <div className="miniapp-hero__preview">
                      <video src={mediaUrl(mediaUrlVal) ?? mediaUrlVal} muted playsInline controls />
                      <button
                        className="btn btn--ghost btn--sm"
                        type="button"
                        onClick={() => setMediaUrlVal(null)}
                      >
                        Убрать
                      </button>
                    </div>
                  ) : (
                    <input
                      ref={fileRef}
                      type="file"
                      accept="video/*"
                      onChange={onVideo}
                      className="input"
                      disabled={uploading}
                    />
                  )}
                  <span className="field__hint">
                    В MAX уйдёт как обычное видео. Кружок готовится автоматически (квадрат 384×384).
                  </span>
                </div>
              )}
            </>
          )}
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
          <button className="btn btn--primary" onClick={save} disabled={busy || uploading}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}
