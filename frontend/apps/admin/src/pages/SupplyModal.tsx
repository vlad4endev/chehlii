import { useMemo, useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../api'
import { useModalA11y } from '../useModalA11y'
import { type StockComponent, MAX_QTY, postSupply } from '../warehouseApi'

type Field = 'base' | 'silver' | 'black'

const FIELDS: { key: Field; label: string }[] = [
  { key: 'base', label: 'Балванка' },
  { key: 'silver', label: 'Пластина · серебро' },
  { key: 'black', label: 'Пластина · чёрная' },
]

const fieldOf = (c: StockComponent): Field | null =>
  c.kind === 'base' ? 'base' : c.plate_type === 'silver' || c.plate_type === 'black' ? c.plate_type : null

interface Props {
  components: StockComponent[]
  /** Модель, выбранная заранее (например, нажали «+ Приход» в строке таблицы). */
  initialModel?: string
  onClose: () => void
  /** Перечитать остатки — вызывается, как только хоть что-то записано. */
  onRecorded: () => void | Promise<void>
  /** Всё записано: короткий итог для сообщения на странице. */
  onDone: (summary: string, model: string) => void
}

/** Приход поставки одной моделью: балванка и обе пластины за один раз, без поиска по таблице. */
export function SupplyModal({ components, initialModel, onClose, onRecorded, onDone }: Props) {
  const models = useMemo(() => [...new Set(components.map((c) => c.model_name))], [components])
  const [model, setModel] = useState(initialModel && models.includes(initialModel) ? initialModel : '')
  const [qty, setQty] = useState<Record<Field, string>>({ base: '', silver: '', black: '' })
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cardRef = useRef<HTMLFormElement>(null)
  useModalA11y(cardRef, () => {
    if (!busy) onClose()
  })

  const current = useMemo(() => {
    const map: Partial<Record<Field, StockComponent>> = {}
    for (const c of components) {
      const f = fieldOf(c)
      if (f && c.model_name === model) map[f] = c
    }
    return map
  }, [components, model])

  const parsed = FIELDS.map((f) => ({ ...f, n: qty[f.key] === '' ? 0 : Number(qty[f.key]), component: current[f.key] }))
  const toAdd = parsed.filter((p) => p.n > 0)
  const total = toAdd.reduce((s, p) => s + p.n, 0)

  function validate(): string | null {
    if (!model) return 'Выберите модель'
    if (toAdd.length === 0) return 'Укажите, сколько пришло, хотя бы по одной позиции'
    for (const p of parsed) {
      if (!Number.isInteger(p.n) || p.n < 0) return `${p.label}: нужно целое число от 0`
      if (p.n > 0 && !p.component) return `${p.label}: такой позиции у модели нет`
      if (p.n > MAX_QTY) return `${p.label}: не больше ${MAX_QTY.toLocaleString('ru-RU')} шт.`
    }
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
    const done: string[] = []
    let failed: string | null = null
    for (const p of toAdd) {
      const c = p.component!
      try {
        await postSupply({
          kind: c.kind,
          model_name: c.model_name,
          plate_type: c.plate_type,
          qty: p.n,
          comment: comment.trim() || undefined,
        })
        done.push(`${p.label.toLowerCase()} +${p.n}`)
        // Записанное сбрасываем сразу: при повторной отправке оно не задвоится.
        setQty((prev) => ({ ...prev, [p.key]: '' }))
      } catch (err) {
        failed = `${p.label}: ${err instanceof ApiError ? err.message : 'нет связи с сервером'}`
        break
      }
    }
    if (done.length > 0) await onRecorded()
    setBusy(false)
    if (failed) {
      setError(
        (done.length > 0 ? `Уже записано: ${done.join(', ')}. ` : '') +
          `Не записано — ${failed}. Остальные поля можно отправить ещё раз.`,
      )
      return
    }
    onDone(`${model}: ${done.join(', ')}`, model)
    onClose()
  }

  return (
    <div className="modal" onClick={() => !busy && onClose()}>
      <form
        ref={cardRef}
        tabIndex={-1}
        className="modal__card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="supply-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
      >
        <div className="modal__head">
          <h2 id="supply-title" className="modal__title">
            Принять поставку
          </h2>
          <button type="button" className="modal__close" onClick={onClose} disabled={busy} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="modal__body">
          <label className="field">
            <span className="field__label">Модель</span>
            <select
              className="input"
              value={model}
              onChange={(e) => {
                setModel(e.target.value)
                setError(null)
              }}
              autoFocus={!model}
            >
              <option value="" disabled>
                Выберите модель
              </option>
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>

          <div className="supplygrid">
            {parsed.map((p) => {
              const cur = p.component?.qty
              return (
                <label key={p.key} className="field">
                  <span className="field__label">{p.label}, шт.</span>
                  <input
                    className="input supplygrid__input"
                    type="number"
                    min={0}
                    inputMode="numeric"
                    placeholder="0"
                    value={qty[p.key]}
                    disabled={!model || !p.component || busy}
                    autoFocus={!!model && p.key === 'base'}
                    onChange={(e) => setQty((prev) => ({ ...prev, [p.key]: e.target.value }))}
                  />
                  <span className="field__hint">
                    {!model ? ' ' : cur === undefined ? 'такой позиции нет' : p.n > 0 ? `${cur} → ${cur + p.n}` : `сейчас ${cur}`}
                  </span>
                </label>
              )
            })}
          </div>
          <p className="field__hint" style={{ margin: 0 }}>
            Заполните только то, что пришло: пустые поля не меняются.
          </p>

          <label className="field">
            <span className="field__label">Комментарий</span>
            <input
              className="input"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="например, номер накладной (необязательно)"
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
          <button type="submit" className="btn btn--primary" disabled={busy || total === 0 || !model}>
            {busy ? 'Записываем…' : total > 0 ? `Записать приход · ${total} шт.` : 'Записать приход'}
          </button>
        </div>
      </form>
    </div>
  )
}
