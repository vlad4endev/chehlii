import { useEffect, useState } from 'react'

import { ApiError } from '../api'
import {
  type Client,
  type Contact,
  type ContactChannel,
  fetchClient,
  fetchContacts,
  updateDiscounts,
} from '../clientsApi'
import { StatLine, UserCell } from '../ui'

const CHANNEL_LABEL: Record<string, string> = { tg: 'Telegram', max: 'MAX' }
const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: '2-digit' }) : '—'

function openChat(url: string | null) {
  if (url) window.open(url, '_blank', 'noopener,noreferrer')
}

function hasChannel(c: Contact, ch: 'tg' | 'max'): boolean {
  return c.channels.some((x) => x.channel === ch)
}

// Бейдж канала: кликабельный → открывает чат в мессенджере.
function ChatBadge({ ch, stop }: { ch: ContactChannel; stop?: boolean }) {
  const label = CHANNEL_LABEL[ch.channel] ?? ch.channel
  if (ch.chat_url) {
    return (
      <button
        className="chatbadge"
        title={`Открыть чат в ${label}`}
        onClick={(e) => {
          if (stop) e.stopPropagation()
          openChat(ch.chat_url)
        }}
      >
        {label} ↗
      </button>
    )
  }
  return (
    <span className="chip" title="Прямая ссылка на профиль недоступна">
      {label}
    </span>
  )
}

export function Clients() {
  const [items, setItems] = useState<Contact[]>([])
  const [q, setQ] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openContact, setOpenContact] = useState<Contact | null>(null)
  const [editId, setEditId] = useState<number | null>(null)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setItems(await fetchContacts(q.trim() || undefined))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить клиентов')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Клиенты</h1>
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
            placeholder="Поиск по телефону или нику"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </form>
      </div>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && items.length > 0 && (
        <StatLine
          items={[
            { label: 'Контактов', value: items.length },
            { label: 'В двух каналах', value: items.filter((c) => c.channels.length > 1).length },
            { label: 'Telegram', value: items.filter((c) => hasChannel(c, 'tg')).length },
            { label: 'MAX', value: items.filter((c) => hasChannel(c, 'max')).length },
          ]}
        />
      )}

      {!loading && !error && (
        <table className="table">
          <thead>
            <tr>
              <th>Клиент</th>
              <th>Каналы · открыть чат</th>
              <th className="num">Заказы</th>
              <th className="num">Скидка</th>
            </tr>
          </thead>
          <tbody>
            {items.map((c) => (
              <tr key={c.key} onClick={() => setOpenContact(c)}>
                <td>
                  <UserCell
                    name={c.display_name || 'Без ника'}
                    sub={
                      c.phone
                        ? c.channels.length > 1
                          ? `${c.phone} · один контакт`
                          : c.phone
                        : undefined
                    }
                  />
                </td>
                <td>
                  <span className="chatcell">
                    {c.channels.map((ch) => (
                      <ChatBadge key={ch.client_id} ch={ch} stop />
                    ))}
                  </span>
                </td>
                <td className="num">{c.total_orders}</td>
                <td className="num">
                  {c.max_discount > 0 ? (
                    <span className="chip chip--accent">{c.max_discount}%</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={4} className="table__empty">
                  Клиентов не найдено.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {openContact && (
        <ContactModal
          contact={openContact}
          onClose={() => setOpenContact(null)}
          onEdit={(clientId) => {
            setOpenContact(null)
            setEditId(clientId)
          }}
        />
      )}
      {editId != null && (
        <ClientModal id={editId} onClose={() => setEditId(null)} onSaved={reload} />
      )}
    </div>
  )
}

function ContactModal({
  contact,
  onClose,
  onEdit,
}: {
  contact: Contact
  onClose: () => void
  onEdit: (clientId: number) => void
}) {
  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title">{contact.display_name || 'Контакт'}</h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal__body">
          {contact.phone && (
            <div className="price-note">
              Телефон: <b>{contact.phone}</b>
              {contact.channels.length > 1 && ' · объединён по номеру (TG + MAX)'}
            </div>
          )}
          <div className="field__label">Каналы</div>
          {contact.channels.map((ch) => (
            <div className="contact-ch" key={ch.client_id}>
              <div className="contact-ch__main">
                <span className="chip">{CHANNEL_LABEL[ch.channel] ?? ch.channel}</span>
                <span className="contact-ch__nick">{ch.nickname || 'без ника'}</span>
                <span className="contact-ch__meta">
                  {ch.number_orders} зак. · скидка {ch.total_discount}%
                </span>
              </div>
              <div className="contact-ch__actions">
                {ch.chat_url ? (
                  <button className="btn btn--ghost btn--sm" onClick={() => openChat(ch.chat_url)}>
                    Открыть чат ↗
                  </button>
                ) : (
                  <span className="muted" style={{ fontSize: 12 }}>
                    ссылка недоступна
                  </span>
                )}
                <button className="btn btn--primary btn--sm" onClick={() => onEdit(ch.client_id)}>
                  Скидки
                </button>
              </div>
            </div>
          ))}
        </div>
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  )
}

function ClientModal({ id, onClose, onSaved }: { id: number; onClose: () => void; onSaved: () => void }) {
  const [client, setClient] = useState<Client | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loyal, setLoyal] = useState(0)
  const [forSlave, setForSlave] = useState(0)
  const [master, setMaster] = useState(0)
  const [slaveDisc, setSlaveDisc] = useState(0)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    fetchClient(id)
      .then((c) => {
        setClient(c)
        setLoyal(c.loyal_discount)
        setForSlave(c.discount_for_slave)
        setMaster(c.discount_master_code)
        setSlaveDisc(c.discount_slave_code)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить'))
  }, [id])

  const total = (Number(loyal) || 0) + (Number(forSlave) || 0) + (Number(master) || 0)

  async function save() {
    setBusy(true)
    try {
      await updateDiscounts(id, {
        loyal_discount: Number(loyal) || 0,
        discount_for_slave: Number(forSlave) || 0,
        discount_master_code: Number(master) || 0,
        discount_slave_code: Number(slaveDisc) || 0,
      })
      onSaved()
      onClose()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card modal__card--wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title">{client?.nickname || `Клиент #${id}`}</h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>

        {!client ? (
          <div className="modal__body">{error ?? 'Загрузка…'}</div>
        ) : (
          <div className="modal__body">
            <div className="deflist">
              <Row label="Телефон" value={client.phone || '—'} />
              <Row label="Канал" value={CHANNEL_LABEL[client.channel] ?? client.channel} />
              <Row label="ID в канале" value={client.channel_user_id} />
              <Row label="Первый запуск" value={fmtDate(client.date_start)} />
              <Row label="Заказов" value={String(client.number_orders)} />
              <Row label="Промокод для друга" value={client.slave_code || '—'} />
              <Row label="Введённый промокод" value={client.master_code || '—'} />
              <Row label="Привлечено друзей" value={String(client.number_slave)} />
            </div>

            <div className="block">
              <div className="field__label">Скидки (задаются вручную, %)</div>
              <div className="grid2">
                <NumField label="Лояльность" value={loyal} onChange={setLoyal} />
                <NumField label="За друзей" value={forSlave} onChange={setForSlave} />
                <NumField label="По промокоду" value={master} onChange={setMaster} />
                <NumField label="Скидка его промокода" value={slaveDisc} onChange={setSlaveDisc} />
              </div>
              <div className="price-note">
                Итоговая скидка (лояльность + друзья + промокод): <b>{total}%</b>
              </div>
            </div>
          </div>
        )}

        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={save} disabled={busy || !client}>
            {busy ? 'Сохраняем…' : 'Сохранить скидки'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="deflist__row">
      <span className="deflist__label">{label}</span>
      <span className="deflist__value">{value}</span>
    </div>
  )
}

function NumField({ label, value, onChange }: { label: string; value: number; onChange: (n: number) => void }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      <input
        className="input"
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}
