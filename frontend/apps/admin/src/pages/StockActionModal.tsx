import { useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../api'
import { useModalA11y } from '../useModalA11y'
import {
  type DefectReason,
  type StockComponent,
  KIND_LABEL,
  PLATE_LABEL,
  adjustComponent,
  postDefect,
  postSupply,
} from '../warehouseApi'

type Action = 'supply' | 'defect' | 'adjust'

const ACTION_LABEL: Record<Action, string> = {
  supply: '+ Приход',
  defect: 'Брак',
  adjust: 'Правка',
}

const DEFECT_OPTIONS: { value: DefectReason; label: string }[] = [
  { value: 'defect_supplier', label: 'Брак поставщика' },
  { value: 'defect_print', label: 'Брак печати' },
  { value: 'defect_glue', label: 'Брак склейки' },
]

interface Props {
  row: StockComponent
  /** Ручная правка остатка доступна только админу; приход и брак — и печатнику. */
  canAdjust: boolean
  onClose: () => void
  /** Вызывается после успешной операции: страница перечитывает остатки и показывает итог. */
  onDone: (summary: string) => void | Promise<void>
}

/** Действия над одной складской позицией: приход, брак, правка остатка. */
export function StockActionModal({ row, canAdjust, onClose, onDone }: Props) {
  const actions: Action[] = canAdjust ? ['supply', 'defect', 'adjust'] : ['supply', 'defect']
  const [action, setAction] = useState<Action>('supply')
  const [qty, setQty] = useState(1)
  const [newQty, setNewQty] = useState(row.qty)
  const [reason, setReason] = useState<DefectReason>('defect_print')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  // Пока идёт запись, закрывать нельзя: иначе человек не узнает, сохранилось ли.
  useModalA11y(cardRef, () => {
    if (!busy) onClose()
  })

  const title =
    `${KIND_LABEL[row.kind] ?? row.kind} · ${row.model_name}` +
    (row.plate_type ? ` · ${PLATE_LABEL[row.plate_type] ?? row.plate_type}` : '')

  function switchAction(next: Action) {
    setAction(next)
    setError(null)
  }

  // Что мешает отправить форму — показываем сразу, до запроса на сервер.
  function validate(): string | null {
    if (action === 'adjust') {
      return newQty === row.qty ? 'Остаток не изменился' : null
    }
    if (!Number.isInteger(qty) || qty < 1) return 'Укажите количество — целое число от 1'
    if (action === 'defect' && qty > row.qty) return `На складе только ${row.qty} шт.`
    return null
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy) return
    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    const base = {
      kind: row.kind,
      model_name: row.model_name,
      plate_type: row.plate_type,
      comment: comment.trim() || undefined,
    }
    const what = `${KIND_LABEL[row.kind] ?? row.kind}${row.plate_type ? ' ' + (PLATE_LABEL[row.plate_type] ?? '').toLowerCase() : ''}, ${row.model_name}`
    let summary: string
    try {
      if (action === 'supply') {
        await postSupply({ ...base, qty })
        summary = `Приход записан: ${what} +${qty}`
      } else if (action === 'defect') {
        await postDefect({ ...base, qty, reason })
        summary = `Брак списан: ${what} −${qty}`
      } else {
        await adjustComponent(row.id, { qty: newQty, comment: base.comment })
        summary = `Остаток исправлен: ${what} ${row.qty} → ${newQty}`
      }
      await onDone(summary)
      onClose()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить — проверьте соединение и попробуйте снова')
    } finally {
      setBusy(false)
    }
  }

  const submitLabel = busy ? 'Сохранение…' : action === 'supply' ? 'Записать приход' : action === 'defect' ? 'Списать брак' : 'Сохранить остаток'

  return (
    <div className="modal" onClick={onClose}>
      <div
        ref={cardRef}
        tabIndex={-1}
        className="modal__card"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <form className="modal__form" onSubmit={submit}>
        <div className="modal__head">
          <h2 className="modal__title">{title}</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="modal__body">
          <p className="field__hint" style={{ margin: 0 }}>
            Сейчас на складе: <b className="mono">{row.qty}</b> шт.
          </p>

          <div className="segmented" role="group" aria-label="Действие">
            {actions.map((a) => (
              <button
                key={a}
                type="button"
                className={`segmented__btn${action === a ? ' segmented__btn--active' : ''}`}
                aria-pressed={action === a}
                onClick={() => switchAction(a)}
              >
                {ACTION_LABEL[a]}
              </button>
            ))}
          </div>

          {action === 'adjust' ? (
            <label className="field">
              <span className="field__label">Новый остаток</span>
              <input
                className="input"
                type="number"
                min={0}
                inputMode="numeric"
                value={newQty}
                onChange={(e) => setNewQty(Math.max(0, Math.trunc(Number(e.target.value) || 0)))}
                autoFocus
              />
              <span className="field__hint">Разница уйдёт в журнал как «Корректировка».</span>
            </label>
          ) : (
            <label className="field">
              <span className="field__label">{action === 'supply' ? 'Сколько пришло' : 'Сколько в брак'}, шт.</span>
              <input
                className="input"
                type="number"
                min={1}
                inputMode="numeric"
                value={qty}
                onChange={(e) => setQty(Math.trunc(Number(e.target.value) || 0))}
                autoFocus
              />
              <span className="quickqty" role="group" aria-label="Быстрый выбор количества">
                {[1, 5, 10, 50].map((n) => (
                  <button key={n} type="button" className="chipbtn" onClick={() => setQty(n)}>
                    {n}
                  </button>
                ))}
              </span>
              <span className="field__hint">
                {Number.isInteger(qty) && qty > 0
                  ? `Станет: ${action === 'supply' ? row.qty + qty : Math.max(0, row.qty - qty)} шт.`
                  : ' '}
              </span>
            </label>
          )}

          {action === 'defect' && (
            <label className="field">
              <span className="field__label">Причина</span>
              <select className="input" value={reason} onChange={(e) => setReason(e.target.value as DefectReason)}>
                {DEFECT_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label className="field">
            <span className="field__label">Комментарий</span>
            <input
              className="input"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={action === 'adjust' ? 'инвентаризация, пересчёт…' : 'необязательно'}
            />
          </label>

          {error && (
            <div className="form-msg form-msg--err" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="modal__actions">
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {submitLabel}
          </button>
        </div>
        </form>
      </div>
    </div>
  )
}
