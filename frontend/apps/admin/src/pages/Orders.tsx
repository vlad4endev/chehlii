import { useEffect, useState } from 'react'

import { ApiError, mediaUrl } from '../api'
import { useAuth } from '../auth'
import {
  CHANNELS,
  type OrderDetail,
  type OrderRow,
  STATUSES,
  changeStatus,
  deleteOrder,
  downloadOrdersXlsx,
  fetchOrder,
  fetchOrders,
  uploadMockup,
} from '../ordersApi'
import { StatusPill } from './Dashboard'

const fmtDate = (iso: string) => {
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' })
}
const money = (n: number) => new Intl.NumberFormat('ru-RU').format(n) + ' ₽'
const CHANNEL_LABEL: Record<string, string> = { tg: 'Telegram', max: 'MAX' }

export function Orders() {
  const [items, setItems] = useState<OrderRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Стартовый фильтр статуса можно задать через URL (?status=…) — из «Требует внимания».
  const [status, setStatus] = useState(
    () => new URLSearchParams(window.location.search).get('status') ?? '',
  )
  const [channel, setChannel] = useState('')
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState<number | null>(null)
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setItems(await fetchOrders({ status, channel, q: q.trim() || undefined }))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить заказы')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, channel])

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Заказы</h1>
        {isAdmin && (
          <button className="btn btn--ghost" onClick={() => downloadOrdersXlsx()}>
            Выгрузить в Excel
          </button>
        )}
      </div>

      <div className="filters">
        <form
          className="filters__search"
          onSubmit={(e) => {
            e.preventDefault()
            reload()
          }}
        >
          <input
            className="input"
            placeholder="Поиск: телефон, ник или № заказа"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </form>
        <select className="input filters__sel" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Все статусы</option>
          {STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <select className="input filters__sel" value={channel} onChange={(e) => setChannel(e.target.value)}>
          <option value="">Все каналы</option>
          {CHANNELS.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      </div>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && (
        <table className="table">
          <thead>
            <tr>
              <th>№</th>
              <th>Дата</th>
              <th>Клиент</th>
              <th>Канал</th>
              <th>Чехол</th>
              <th>Статус</th>
              {isAdmin && <th className="num">Итог</th>}
            </tr>
          </thead>
          <tbody>
            {items.map((o) => (
              <tr key={o.id} onClick={() => setOpenId(o.id)}>
                <td className="strong mono">#{o.id}</td>
                <td className="mono">{fmtDate(o.created_at)}</td>
                <td>{o.client_name || o.client_phone || '—'}</td>
                <td>{CHANNEL_LABEL[o.channel] ?? o.channel}</td>
                <td>
                  <span className="ordercase">
                    <OrderThumb photo={o.case_photo_url} isCustom={o.is_custom} />
                    <span className="ordercase__text">
                      <span className="ordercase__name">{o.case_name || '—'}</span>
                      {o.model_name && <span className="muted">{o.model_name}</span>}
                    </span>
                  </span>
                </td>
                <td>
                  <StatusPill status={o.status} label={o.status_label} />
                </td>
                {isAdmin && <td className="num mono">{o.final_price != null ? money(o.final_price) : '—'}</td>}
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={isAdmin ? 7 : 6} className="table__empty">
                  Заказов не найдено.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {openId != null && (
        <OrderModal id={openId} onClose={() => setOpenId(null)} onChanged={reload} />
      )}
    </div>
  )
}

function OrderModal({ id, onClose, onChanged }: { id: number; onClose: () => void; onChanged: () => void }) {
  const [order, setOrder] = useState<OrderDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [nextStatus, setNextStatus] = useState('')
  const [forceStatus, setForceStatus] = useState('')
  const [mockupFile, setMockupFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  async function load() {
    try {
      const d = await fetchOrder(id)
      setOrder(d)
      setMockupFile(null)
      setNextStatus('')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить заказ')
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  async function applyStatus() {
    if (!nextStatus) return
    setBusy(true)
    try {
      const d = await changeStatus(id, nextStatus)
      setOrder(d)
      setNextStatus('')
      onChanged()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось сменить статус')
    } finally {
      setBusy(false)
    }
  }

  // Ручная установка (только Админ): ставит любой статус в обход правила «только вперёд».
  async function applyForce() {
    if (!forceStatus) return
    const label = STATUSES.find((s) => s.value === forceStatus)?.label ?? forceStatus
    if (!confirm(`Установить статус «${label}» вручную, в обход порядка? Действие для исправления ошибок.`))
      return
    setBusy(true)
    try {
      const d = await changeStatus(id, forceStatus, true)
      setOrder(d)
      setForceStatus('')
      onChanged()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось установить статус')
    } finally {
      setBusy(false)
    }
  }

  async function sendMockup() {
    if (!mockupFile) return
    setBusy(true)
    try {
      const d = await uploadMockup(id, mockupFile)
      setOrder(d)
      setMockupFile(null)
      onChanged()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось отправить макет')
    } finally {
      setBusy(false)
    }
  }

  async function removeToTrash() {
    if (!confirm(`Переместить заказ #${id} в корзину? Его можно будет восстановить.`)) return
    setBusy(true)
    try {
      await deleteOrder(id)
      onChanged()
      onClose()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось удалить заказ')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card modal__card--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title">
            Заказ #{id}
            {order && (
              <span style={{ marginLeft: 10 }}>
                <StatusPill status={order.status} label={order.status_label} />
              </span>
            )}
          </h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>

        {!order ? (
          <div className="modal__body">{error ?? 'Загрузка…'}</div>
        ) : (
          <div className="modal__body">
            <div className="orderhero">
              <OrderThumb photo={order.case_photo_url} isCustom={order.is_custom} large />
              <div className="orderhero__info">
                <span className={`chip${order.is_custom ? ' chip--accent' : ''}`}>
                  {order.is_custom ? 'Кастом' : 'Стандарт'}
                </span>
                <h3 className="orderhero__name">{order.case_name || 'Чехол'}</h3>
                {order.model_name && <div className="orderhero__model">{order.model_name}</div>}
                {order.custom_text && (
                  <div className="orderhero__engrave">Гравировка: «{order.custom_text}»</div>
                )}
              </div>
            </div>

            {(order.materials_text ||
              (Array.isArray(order.materials_files) && order.materials_files.length > 0)) && (
              <div className="block">
                <div className="field__label">Материалы от клиента</div>
                {order.materials_text && <p className="clientdesc">{order.materials_text}</p>}
                {Array.isArray(order.materials_files) && order.materials_files.length > 0 && (
                  <div className="photogrid">
                    {order.materials_files.map((f, i) => (
                      <ClientFile key={i} file={f} index={i} />
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="deflist">
              <Row label="Клиент" value={order.client_name || '—'} />
              <Row label="Телефон" value={order.client_phone || '—'} />
              <Row label="Канал" value={CHANNEL_LABEL[order.channel] ?? order.channel} />
              {order.delivery_service && <Row label="Доставка" value={order.delivery_service} />}
              {order.delivery_address && <Row label="Адрес" value={order.delivery_address} />}
              {order.tracking_code && <Row label="Трек" value={order.tracking_code} />}
              {isAdmin && (
                <>
                  <div className="deflist__sep">Финансы</div>
                  <Row label="Себестоимость" value={order.cost != null ? money(order.cost) : '—'} />
                  <Row label="Маржа" value={order.margin != null ? money(order.margin) : '—'} />
                  <Row label="Скидка" value={order.total_discount != null ? `${order.total_discount}%` : '—'} />
                  <Row label="Доставка, ₽" value={order.delivery_cost != null ? money(order.delivery_cost) : '—'} />
                  <Row label="Итог" value={order.final_price != null ? money(order.final_price) : '—'} strong />
                </>
              )}
            </div>

            <div className="block">
              <div className="field__label">Макет</div>
              {order.mockup_url && (
                <a className="linkbtn" href={order.mockup_url} target="_blank" rel="noreferrer">
                  Текущий макет ↗
                </a>
              )}
              <div className="inline-form">
                <input
                  className="input"
                  type="file"
                  accept="image/*,.pdf"
                  onChange={(e) => setMockupFile(e.target.files?.[0] ?? null)}
                />
                <button
                  className="btn btn--primary"
                  onClick={sendMockup}
                  disabled={busy || !mockupFile}
                >
                  Загрузить и отправить
                </button>
              </div>
              <div className="card__hint">
                Файл уйдёт на Яндекс.Диск, статус станет «Отправка макета», а клиент получит его
                в боте с кнопками «Подтвердить / Переделать».
              </div>
            </div>

            <div className="block">
              <div className="field__label">Сменить статус</div>
              {order.allowed_next.length === 0 ? (
                <div className="muted">Нет доступных переходов для вашей роли.</div>
              ) : (
                <div className="inline-form">
                  <select className="input" value={nextStatus} onChange={(e) => setNextStatus(e.target.value)}>
                    <option value="">— выберите —</option>
                    {order.allowed_next.map((s) => (
                      <option key={s.value} value={s.value}>
                        {s.label}
                      </option>
                    ))}
                  </select>
                  <button className="btn btn--primary" onClick={applyStatus} disabled={busy || !nextStatus}>
                    Применить
                  </button>
                </div>
              )}

              {isAdmin && (
                <details className="manual-status">
                  <summary>Ручная установка статуса</summary>
                  <div className="inline-form">
                    <select
                      className="input"
                      value={forceStatus}
                      onChange={(e) => setForceStatus(e.target.value)}
                    >
                      <option value="">— любой статус —</option>
                      {STATUSES.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                    <button
                      className="btn btn--danger btn--sm"
                      onClick={applyForce}
                      disabled={busy || !forceStatus}
                    >
                      Установить
                    </button>
                  </div>
                  <div className="card__hint">
                    Только для админа: ставит любой статус в обход порядка (включая назад). Для
                    исправления ошибок.
                  </div>
                </details>
              )}
            </div>

            <div className="block">
              <div className="field__label">История</div>
              <ol className="timeline">
                {order.history.map((h, i) => (
                  <li key={i} className="timeline__item">
                    <span className="timeline__status">{h.status_label}</span>
                    <span className="timeline__meta">
                      {fmtDate(h.created_at)}
                      {h.trigger ? ` · ${h.trigger}` : ''}
                    </span>
                  </li>
                ))}
              </ol>
            </div>

            {isAdmin && (
              <div className="block trash-action">
                <button className="btn btn--danger btn--sm" onClick={removeToTrash} disabled={busy}>
                  Переместить в корзину
                </button>
                <span className="card__hint">Заказ скроется из списка; восстановить можно в «Корзине».</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function Row({ label, value, strong }: { label: string; value: string; strong?: boolean }) {
  return (
    <div className="deflist__row">
      <span className="deflist__label">{label}</span>
      <span className={`deflist__value${strong ? ' strong' : ''}`}>{value}</span>
    </div>
  )
}

// Миниатюра чехла в заказе: фото из каталога, иначе плейсхолдер (✦ для кастома).
function OrderThumb({
  photo,
  isCustom,
  large,
}: {
  photo: string | null
  isCustom: boolean | null
  large?: boolean
}) {
  const [failed, setFailed] = useState(false)
  const src = mediaUrl(photo || '')
  const cls = `othumb${large ? ' othumb--lg' : ''}`
  if (src && !failed) {
    return (
      <span className={cls}>
        <img src={src} alt="" onError={() => setFailed(true)} />
      </span>
    )
  }
  return (
    <span className={`${cls} othumb--empty`} aria-hidden="true">
      {isCustom ? '✦' : '▢'}
    </span>
  )
}

// Файл клиента: фото показываем миниатюрой (клик — открыть), иначе ссылка.
function ClientFile({ file, index }: { file: unknown; index: number }) {
  const [failed, setFailed] = useState(false)
  const url = typeof file === 'string' ? mediaUrl(file) : null
  const isImage =
    typeof file === 'string' && /\.(jpe?g|png|webp|gif|heic|heif)$/i.test(file.split('?')[0])

  if (url && isImage && !failed) {
    return (
      <a className="photocard" href={url} target="_blank" rel="noreferrer" title={`Фото ${index + 1}`}>
        <img src={url} alt={`Фото ${index + 1}`} onError={() => setFailed(true)} />
      </a>
    )
  }
  if (url) {
    return (
      <a className="photocard photocard--file" href={url} target="_blank" rel="noreferrer">
        <span>Файл {index + 1} ↗</span>
      </a>
    )
  }
  return <span className="photocard photocard--file photocard--muted">Файл {index + 1}</span>
}
