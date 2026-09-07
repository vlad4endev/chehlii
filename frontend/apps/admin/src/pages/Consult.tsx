import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, mediaUrl } from '../api'
import { Icon } from '../icons'
import {
  type ConsultMessage,
  type ConsultTab,
  type ConsultThread,
  type MediaItem,
  closeThread,
  fetchThread,
  fetchThreads,
  markRead,
  reopenThread,
  sendReply,
  uploadConsultMedia,
} from '../consultApi'
import { ChannelChip, initials } from '../ui'

const TABS: { id: ConsultTab; label: string }[] = [
  { id: 'waiting', label: 'Ждут ответа' },
  { id: 'open', label: 'Открытые' },
  { id: 'closed', label: 'Закрытые' },
  { id: 'all', label: 'Все' },
]

const CHANNEL: Record<string, string> = { tg: 'Telegram', max: 'MAX' }

function fmtTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}

function fmtStamp(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function mediaLabel(m: MediaItem): string {
  if (m.type === 'audio') return 'Голосовое'
  if (m.type === 'video') return 'Видео'
  if (m.type === 'file') return m.name || 'Файл'
  return m.name || 'Вложение'
}

export function Consult() {
  const initialId = Number(new URLSearchParams(window.location.search).get('id') || 0) || null
  const [tab, setTab] = useState<ConsultTab>(initialId ? 'all' : 'waiting')
  const [q, setQ] = useState('')
  const [threads, setThreads] = useState<ConsultThread[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<number | null>(initialId)
  const [detail, setDetail] = useState<{ thread: ConsultThread; messages: ConsultMessage[] } | null>(
    null,
  )
  const [draft, setDraft] = useState('')
  const [attach, setAttach] = useState<MediaItem[]>([])
  const [sending, setSending] = useState(false)
  const [busy, setBusy] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const stickBottom = useRef(true)

  const loadList = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const rows = await fetchThreads(tab, q)
      setThreads(rows)
      setError(null)
    } catch (e) {
      if (!silent) setError(e instanceof ApiError ? e.message : 'Не удалось загрузить диалоги')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [tab, q])

  const loadDetail = useCallback(async (id: number, silent = false) => {
    try {
      const data = await fetchThread(id)
      setDetail(data)
      if (data.thread.unread_admin > 0) {
        await markRead(id)
        setThreads((prev) => prev.map((t) => (t.id === id ? { ...t, unread_admin: 0 } : t)))
      }
    } catch (e) {
      if (!silent) setError(e instanceof ApiError ? e.message : 'Не удалось открыть диалог')
    }
  }, [])

  useEffect(() => {
    void loadList()
    // Поиск — по Enter в поле; автообновление списка — при смене вкладки.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  useEffect(() => {
    if (activeId == null) {
      setDetail(null)
      return
    }
    loadDetail(activeId)
  }, [activeId, loadDetail])

  useEffect(() => {
    const t = window.setInterval(() => {
      loadList(true)
      if (activeId != null) loadDetail(activeId, true)
    }, 5000)
    return () => window.clearInterval(t)
  }, [loadList, loadDetail, activeId])

  useEffect(() => {
    if (!stickBottom.current) return
    const el = scroller.current
    if (el) el.scrollTop = el.scrollHeight
  }, [detail?.messages.length, activeId])

  async function onSend() {
    if (!activeId || sending) return
    const text = draft.trim()
    if (!text && attach.length === 0) return
    setSending(true)
    try {
      await sendReply(activeId, text, attach)
      setDraft('')
      setAttach([])
      stickBottom.current = true
      await loadDetail(activeId)
      await loadList(true)
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не отправилось')
    } finally {
      setSending(false)
    }
  }

  async function onAttach(file: File) {
    try {
      const item = await uploadConsultMedia(file)
      setAttach((prev) => [...prev, item].slice(0, 10))
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось загрузить файл')
    }
  }

  async function onClose() {
    if (!activeId) return
    setBusy(true)
    try {
      await closeThread(activeId)
      await loadDetail(activeId)
      await loadList(true)
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось закрыть')
    } finally {
      setBusy(false)
    }
  }

  async function onReopen() {
    if (!activeId) return
    setBusy(true)
    try {
      await reopenThread(activeId)
      await loadDetail(activeId)
      await loadList(true)
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось открыть')
    } finally {
      setBusy(false)
    }
  }

  const thread = detail?.thread
  const showChat = activeId != null

  return (
    <div className={`inbox${showChat ? ' inbox--chat' : ''}`}>
      <aside className="inbox__list">
        <div className="inbox__head">
          <h1 className="page__title">Поможем выбрать</h1>
          <p className="inbox__lead">Переписка с клиентами из бота</p>
          <div className="segmented inbox__tabs">
            {TABS.map((t) => (
              <button
                key={t.id}
                className={`segmented__btn${tab === t.id ? ' segmented__btn--active' : ''}`}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <input
            className="input"
            placeholder="Имя, телефон, текст…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && loadList()}
          />
        </div>
        <div className="inbox__threads">
          {loading && threads.length === 0 && <div className="inbox__empty">Загрузка…</div>}
          {error && threads.length === 0 && <div className="inbox__empty">{error}</div>}
          {!loading && threads.length === 0 && !error && (
            <div className="inbox__empty">
              {tab === 'waiting' ? 'Новых сообщений нет — можно выдохнуть.' : 'Диалогов пока нет.'}
            </div>
          )}
          {threads.map((t) => (
            <button
              key={t.id}
              className={`inbox__row${t.id === activeId ? ' inbox__row--active' : ''}${
                t.unread_admin > 0 ? ' inbox__row--unread' : ''
              }`}
              onClick={() => {
                stickBottom.current = true
                setActiveId(t.id)
              }}
            >
              <span className="inbox__avatar">{initials(t.client_name)}</span>
              <span className="inbox__meta">
                <span className="inbox__row-top">
                  <b>{t.client_name}</b>
                  <span>{fmtTime(t.last_message_at)}</span>
                </span>
                <span className="inbox__preview">{t.last_preview || '—'}</span>
                <span className="inbox__row-tags">
                  <ChannelChip channel={t.channel} />
                  {t.status === 'closed' && <span className="chip">закрыт</span>}
                </span>
              </span>
              {t.unread_admin > 0 && <span className="inbox__unread">{t.unread_admin}</span>}
            </button>
          ))}
        </div>
      </aside>

      <section className="inbox__chat">
        {!thread && (
          <div className="inbox__placeholder">
            <Icon name="chat" size={36} />
            <p>Выберите диалог слева — или дождитесь сообщения из бота.</p>
            <p className="muted">Клиент пишет через кнопку «Поможем выбрать» в Telegram или MAX.</p>
          </div>
        )}
        {thread && detail && (
          <>
            <header className="inbox__chat-head">
              <button className="inbox__back" onClick={() => setActiveId(null)} aria-label="К списку">
                <Icon name="chevron" size={18} />
              </button>
              <span className="inbox__avatar">{initials(thread.client_name)}</span>
              <div className="inbox__who">
                <b>{thread.client_name}</b>
                <span>
                  {CHANNEL[thread.channel]}
                  {thread.client_phone ? ` · ${thread.client_phone}` : ''}
                </span>
              </div>
              {thread.status === 'open' ? (
                <button className="btn btn--ghost btn--sm" disabled={busy} onClick={onClose}>
                  Закрыть
                </button>
              ) : (
                <button className="btn btn--ghost btn--sm" disabled={busy} onClick={onReopen}>
                  Открыть снова
                </button>
              )}
            </header>

            <div
              className="inbox__msgs"
              ref={scroller}
              onScroll={(e) => {
                const el = e.currentTarget
                stickBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
              }}
            >
              {detail.messages.length === 0 && (
                <div className="inbox__empty">Клиент ещё ничего не написал.</div>
              )}
              {detail.messages.map((m) => (
                <article
                  key={m.id}
                  className={`bubble bubble--${m.sender === 'admin' ? 'out' : 'in'}`}
                >
                  {m.text && <p>{m.text}</p>}
                  {m.media.length > 0 && (
                    <div className="bubble__media">
                      {m.media.map((item, i) =>
                        item.type === 'image' ? (
                          <a key={i} href={mediaUrl(item.url)} target="_blank" rel="noreferrer">
                            <img src={mediaUrl(item.url)} alt="" />
                          </a>
                        ) : item.type === 'audio' ? (
                          <audio key={i} controls src={mediaUrl(item.url)} />
                        ) : item.type === 'video' ? (
                          <video key={i} controls src={mediaUrl(item.url)} />
                        ) : (
                          <a
                            key={i}
                            className="bubble__file"
                            href={mediaUrl(item.url)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {mediaLabel(item)}
                          </a>
                        ),
                      )}
                    </div>
                  )}
                  <time>{fmtStamp(m.created_at)}</time>
                </article>
              ))}
            </div>

            {thread.status === 'closed' ? (
              <div className="inbox__closed">Диалог закрыт. Откройте снова, чтобы ответить.</div>
            ) : (
              <form
                className="inbox__composer"
                onSubmit={(e) => {
                  e.preventDefault()
                  onSend()
                }}
              >
                {attach.length > 0 && (
                  <div className="inbox__attach-row">
                    {attach.map((a, i) => (
                      <span key={i} className="inbox__chip">
                        {a.type === 'image' ? (
                          <img src={mediaUrl(a.url)} alt="" />
                        ) : (
                          mediaLabel(a)
                        )}
                        <button
                          type="button"
                          onClick={() => setAttach((prev) => prev.filter((_, j) => j !== i))}
                          aria-label="Убрать"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
                <div className="inbox__compose-row">
                  <input
                    ref={fileRef}
                    type="file"
                    hidden
                    accept="image/*,video/*,.pdf,audio/*"
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      e.target.value = ''
                      if (f) onAttach(f)
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn--ghost"
                    onClick={() => fileRef.current?.click()}
                    title="Вложение"
                  >
                    +
                  </button>
                  <textarea
                    className="input textarea inbox__input"
                    rows={2}
                    placeholder="Ответ клиенту…"
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                        e.preventDefault()
                        onSend()
                      }
                    }}
                  />
                  <button
                    className="btn btn--primary"
                    disabled={sending || (!draft.trim() && attach.length === 0)}
                  >
                    {sending ? '…' : 'Отправить'}
                  </button>
                </div>
              </form>
            )}
          </>
        )}
      </section>
    </div>
  )
}
