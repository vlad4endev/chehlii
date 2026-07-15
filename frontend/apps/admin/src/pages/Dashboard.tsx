import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../api'
import { useAuth } from '../auth'
import { Icon } from '../icons'
import { sectionsFor } from '../sections'
import { type RecentOrder, type Stats, fetchStats } from '../statsApi'

const CHANNEL_LABEL: Record<string, string> = { tg: 'Telegram', max: 'MAX' }

// Категория статуса → класс пилюли (цвет точки по этапу воронки).
const CAT: Record<string, string> = {
  case_type_selected: 'new', model_selected: 'new', case_confirmed: 'new', materials_submitted: 'new',
  prepayment_issued: 'pay', prepayment_paid: 'pay', postpayment_issued: 'pay', postpayment_paid: 'pay', delivery_payment: 'pay',
  handed_to_design: 'design', design_in_progress: 'design', mockup_sent: 'design', mockup_approval: 'design', mockup_revision: 'design',
  delivery_service_selection: 'ship', delivery_address_selection: 'ship', shipped: 'ship',
  delivered: 'done', review_offered: 'done', review_received: 'done',
  cancelled: 'cancel',
}

export function StatusPill({ status, label }: { status: string; label: string }) {
  return <span className={`spill spill--${CAT[status] ?? 'new'}`}>{label}</span>
}

function money(v: number): string {
  return new Intl.NumberFormat('ru-RU').format(Math.round(v)) + ' ₽'
}
function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { day: '2-digit', month: 'short' })
}

export function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [error, setError] = useState<string | null>(null)
  const isAdmin = user?.role === 'admin'

  useEffect(() => {
    fetchStats()
      .then(setStats)
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить сводку'))
  }, [])

  const maxCount = useMemo(
    () => Math.max(1, ...(stats?.status_distribution.map((s) => s.count) ?? [1])),
    [stats],
  )

  if (!user) return null
  const greeting = user.full_name || user.email

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">обзор</h1>
      </div>
      <p className="page__lead">{greeting}, вот что происходит в casetop прямо сейчас.</p>

      {error && <div className="empty">{error}</div>}
      {!error && !stats && <div className="empty">Загружаем сводку…</div>}

      {stats && (
        <div className="dash">
          <div className="kpi-grid">
            <Kpi icon="box" label="Заказы всего" value={stats.orders_total} sub="за всё время" />
            <Kpi icon="pulse" label="В работе" value={stats.orders_active} sub="активная воронка" />
            <Kpi icon="calendar" label="Сегодня" value={stats.orders_today} sub="новых за 24 ч" />
            {isAdmin && (
              <Kpi
                icon="ruble"
                label="Сумма заказов"
                value={stats.revenue_active != null ? money(stats.revenue_active) : '—'}
                sub="активные, со скидками"
                dark
              />
            )}
            {isAdmin && (
              <Kpi icon="client" label="Клиенты" value={stats.clients_total} sub="в базе" />
            )}
            {isAdmin && (
              <Kpi icon="star" label="На модерации" value={stats.reviews_pending} sub="отзывов ждут" />
            )}
          </div>

          <div className="dash__cols">
            <div className="card">
              <div className="card__head">
                <span className="card__title">Воронка заказов</span>
                <span className="card__hint">по статусам</span>
              </div>
              {stats.status_distribution.length === 0 ? (
                <div className="card__hint">Заказов пока нет.</div>
              ) : (
                <div className="pipe">
                  {stats.status_distribution.map((s) => (
                    <div className="pipe__row" key={s.status}>
                      <span className="pipe__label">{s.label}</span>
                      <span className="pipe__track">
                        <span
                          className="pipe__fill"
                          style={{ width: `${Math.round((s.count / maxCount) * 100)}%` }}
                        />
                      </span>
                      <span className="pipe__count">{s.count}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="card">
              <div className="card__head">
                <span className="card__title">Быстрые действия</span>
              </div>
              <div className="qa">
                {sectionsFor(user.role).map((s) => (
                  <button className="qa__item" key={s.path} onClick={() => navigate(s.path)}>
                    <Icon name={s.icon} size={18} />
                    {s.label}
                    <Icon name="chevron" size={16} />
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
            <div className="card__head" style={{ padding: '18px 20px 0' }}>
              <span className="card__title">Последние заказы</span>
              <button className="linkbtn" onClick={() => navigate('/orders')}>
                Все заказы →
              </button>
            </div>
            <RecentTable
              orders={stats.recent_orders}
              isAdmin={isAdmin}
              onOpen={() => navigate('/orders')}
            />
          </div>
        </div>
      )}
    </div>
  )
}

function Kpi({
  icon,
  label,
  value,
  sub,
  dark,
}: {
  icon: string
  label: string
  value: number | string
  sub: string
  dark?: boolean
}) {
  return (
    <div className={`kpi${dark ? ' kpi--dark' : ''}`}>
      <div className="kpi__icon">
        <Icon name={icon} size={20} />
      </div>
      <div className="kpi__value">{value}</div>
      <div>
        <div className="kpi__label">{label}</div>
        <div className="kpi__sub">{sub}</div>
      </div>
    </div>
  )
}

function RecentTable({
  orders,
  isAdmin,
  onOpen,
}: {
  orders: RecentOrder[]
  isAdmin: boolean
  onOpen: () => void
}) {
  if (orders.length === 0) {
    return <div className="table__empty">Заказов пока нет.</div>
  }
  return (
    <table className="table table--flush" style={{ marginTop: 12 }}>
      <thead>
        <tr>
          <th>№</th>
          <th>Клиент</th>
          <th>Канал</th>
          <th>Статус</th>
          {isAdmin && <th className="num">Сумма</th>}
          <th className="num">Дата</th>
        </tr>
      </thead>
      <tbody>
        {orders.map((o) => (
          <tr key={o.id} onClick={onOpen}>
            <td className="mono strong">#{o.id}</td>
            <td className="strong">{o.client_name ?? '—'}</td>
            <td className="muted">{CHANNEL_LABEL[o.channel] ?? o.channel}</td>
            <td>
              <StatusPill status={o.status} label={o.label} />
            </td>
            {isAdmin && (
              <td className="num">{o.client_price != null ? money(o.client_price) : '—'}</td>
            )}
            <td className="num muted">{fmtDate(o.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
