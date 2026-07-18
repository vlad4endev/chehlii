import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../api'
import { useAuth } from '../auth'
import { Icon } from '../icons'
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

function money(v: number | null): string {
  if (v == null) return '—'
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
          {isAdmin && (
            <div className="moneyrow">
              <MoneyCard hero label="Выручка" value={money(stats.revenue_paid)} sub="оплаченные заказы" onClick={() => navigate('/orders')} />
              <MoneyCard label="Сумма в работе" value={money(stats.pipeline_value)} sub="активные заказы" onClick={() => navigate('/orders')} />
              <MoneyCard label="Средний чек" value={money(stats.avg_check)} sub="без отменённых" onClick={() => navigate('/orders')} />
            </div>
          )}

          <div className="kpi-grid">
            <Kpi icon="box" label="Заказов всего" value={stats.orders_total} sub="за всё время" onClick={() => navigate('/orders')} />
            <Kpi icon="pulse" label="В работе" value={stats.orders_active} sub="активная воронка" onClick={() => navigate('/orders')} />
            <Kpi icon="check" label="Завершено" value={stats.orders_done} sub="доставлено" onClick={() => navigate('/orders?status=delivered')} />
            <Kpi
              icon="calendar"
              label="Новых за 7 дней"
              value={stats.orders_week}
              sub={`сегодня: ${stats.orders_today}`}
              onClick={() => navigate('/orders')}
            />
            {isAdmin && (
              <Kpi icon="client" label="Клиенты" value={stats.clients_total} sub="в базе" onClick={() => navigate('/clients')} />
            )}
          </div>

          {isAdmin && stats.attention.length > 0 && (
            <div className="card">
              <div className="card__head">
                <span className="card__title">Требует внимания</span>
              </div>
              <div className="attn attn--grid">
                {stats.attention.map((a) => (
                  <button className="attn__item" key={a.key} onClick={() => navigate(a.href)}>
                    <span className="attn__count">{a.count}</span>
                    <span className="attn__label">{a.label}</span>
                    <Icon name="chevron" size={16} />
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="card">
            <div className="card__head">
              <span className="card__title">Заказы по этапам</span>
              <span className="card__hint">{stats.orders_total} всего</span>
            </div>
            {stats.orders_total === 0 ? (
              <div className="card__hint">Заказов пока нет.</div>
            ) : (
              <div className="funnel">
                {stats.stages.map((s) => {
                  const share = stats.orders_total
                    ? Math.round((s.count / stats.orders_total) * 100)
                    : 0
                  return (
                    <div className="funnel__row" key={s.key}>
                      <span className="funnel__head">
                        <span className={`dot dot--${s.key}`} />
                        <span className="funnel__label">{s.label}</span>
                      </span>
                      <span className="funnel__track">
                        <span className="funnel__fill" style={{ width: `${share}%` }} />
                      </span>
                      <span className="funnel__count">
                        {s.count}
                        <span className="funnel__share">{share}%</span>
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div className="card">
            <div className="card__head">
              <span className="card__title">Популярные модели iPhone</span>
              <span className="card__hint">по числу заказов</span>
            </div>
            {stats.popular_models.length === 0 ? (
              <div className="card__hint">Заказов пока нет.</div>
            ) : (
              <div className="funnel">
                {(() => {
                  const max = Math.max(...stats.popular_models.map((p) => p.count), 1)
                  return stats.popular_models.map((p) => {
                    const share = Math.round((p.count / max) * 100)
                    return (
                      <div className="funnel__row" key={p.model_name}>
                        <span className="funnel__head">
                          <span className="funnel__label">{p.model_name}</span>
                        </span>
                        <span className="funnel__track">
                          <span className="funnel__fill" style={{ width: `${share}%` }} />
                        </span>
                        <span className="funnel__count">{p.count}</span>
                      </div>
                    )
                  })
                })()}
              </div>
            )}
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

function MoneyCard({
  label,
  value,
  sub,
  hero,
  onClick,
}: {
  label: string
  value: string
  sub: string
  hero?: boolean
  onClick?: () => void
}) {
  const cls = `money${hero ? ' money--hero' : ''}${onClick ? ' money--link' : ''}`
  if (onClick) {
    return (
      <button type="button" className={cls} onClick={onClick}>
        <div className="money__label">{label}</div>
        <div className="money__value">{value}</div>
        <div className="money__sub">{sub}</div>
      </button>
    )
  }
  return (
    <div className={cls}>
      <div className="money__label">{label}</div>
      <div className="money__value">{value}</div>
      <div className="money__sub">{sub}</div>
    </div>
  )
}

function Kpi({
  icon,
  label,
  value,
  sub,
  onClick,
}: {
  icon: string
  label: string
  value: number | string
  sub: string
  onClick?: () => void
}) {
  const cls = `kpi${onClick ? ' kpi--link' : ''}`
  const inner = (
    <>
      <div className="kpi__icon">
        <Icon name={icon} size={20} />
      </div>
      <div className="kpi__value">{value}</div>
      <div>
        <div className="kpi__label">{label}</div>
        <div className="kpi__sub">{sub}</div>
      </div>
    </>
  )
  return onClick ? (
    <button type="button" className={cls} onClick={onClick}>{inner}</button>
  ) : (
    <div className={cls}>{inner}</div>
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
    <div className="tablewrap"><table className="table table--flush" style={{ marginTop: 12 }}>
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
            {isAdmin && <td className="num mono">{money(o.client_price)}</td>}
            <td className="num muted">{fmtDate(o.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  )
}
