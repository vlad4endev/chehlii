import { useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api'
import {
  type PendingOrder,
  PLATE_LABEL,
  deductAvailablePending,
  deductPendingOrder,
} from '../warehouseApi'

interface Props {
  items: PendingOrder[]
  /** Перечитать склад и очередь после списания. */
  onChanged: () => void | Promise<void>
}

const daysAgo = (iso: string): string => {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (days <= 0) return 'сегодня'
  return `${days} дн. назад`
}

/** Оплаченные заказы, по которым склад не списан: оприходовали — спишите одним нажатием. */
export function PendingDeductions({ items, onChanged }: Props) {
  const [busy, setBusy] = useState<number | 'all' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  if (items.length === 0) return null
  const ready = items.filter((i) => i.can_deduct).length

  async function run(key: number | 'all', action: () => Promise<{ deducted: number }>) {
    if (busy !== null) return
    setBusy(key)
    setError(null)
    setNote(null)
    try {
      const res = await action()
      await onChanged() // сначала свежие цифры, потом сообщение — они не должны расходиться
      setNote(res.deducted > 0 ? `Списано заказов: ${res.deducted}` : null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось списать — проверьте соединение и попробуйте снова')
      await onChanged()
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="pendingbox" aria-labelledby="pending-title">
      <div className="pendingbox__head">
        <div>
          <h2 id="pending-title" className="pendingbox__title">
            Оплачено, но не списано со склада · {items.length}
          </h2>
          <p className="field__hint" style={{ margin: '2px 0 0' }}>
            Когда заказ оплатили, нужной балванки или пластины не было. Оприходуйте их и спишите.
            {ready > 0 && ` Сейчас можно списать: ${ready}.`}
          </p>
        </div>
        <button
          className="btn btn--primary btn--sm"
          disabled={ready === 0 || busy !== null}
          onClick={() => void run('all', deductAvailablePending)}
        >
          {busy === 'all' ? 'Списываем…' : `Списать всё, где хватает${ready ? ` (${ready})` : ''}`}
        </button>
      </div>

      <ul className="pendingbox__list">
        {items.map((o) => (
          <li key={o.order_id} className="pendingbox__row">
            <div className="pendingbox__info">
              <Link className="strong" to={`/orders?open=${o.order_id}`}>
                Заказ #{o.order_id}
              </Link>
              <span className="field__hint">
                {o.case_name} · {o.model_name} · пластина {PLATE_LABEL[o.plate_type]?.toLowerCase() ?? o.plate_type}
                {' · '}
                {daysAgo(o.created_at)}
              </span>
            </div>
            <button
              className="btn btn--ghost btn--sm"
              disabled={!o.can_deduct || busy !== null}
              title={o.can_deduct ? undefined : 'Не хватает остатка — сначала приход'}
              onClick={() => void run(o.order_id, () => deductPendingOrder(o.order_id))}
            >
              {busy === o.order_id ? 'Списываем…' : o.can_deduct ? 'Списать' : 'Нет остатка'}
            </button>
          </li>
        ))}
      </ul>

      {note && (
        <div className="form-msg form-msg--ok" role="status">
          {note}
        </div>
      )}
      {error && (
        <div className="form-msg form-msg--err" role="alert">
          {error}
        </div>
      )}
    </section>
  )
}
