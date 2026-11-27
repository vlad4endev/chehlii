import { useMemo, useRef, useState } from 'react'

import { ApiError } from '../api'
import { useModalA11y } from '../useModalA11y'
import { type InventoryResult, type StockComponent, MAX_QTY, saveInventory } from '../warehouseApi'
import { type ModelRow, groupByModel } from './StockMatrix'

interface Props {
  components: StockComponent[]
  onClose: () => void
  /** После сохранения: страница перечитывает остатки и показывает итог. */
  onSaved: (result: InventoryResult) => void | Promise<void>
}

const COLUMNS = [
  { key: 'base', label: 'Балванка' },
  { key: 'silver', label: 'Пластина · серебро' },
  { key: 'black', label: 'Пластина · чёрная' },
] as const

/** Разобрать ввод: целое число 0…MAX_QTY, иначе null (пустая строка — «не менять»). */
function parseQty(raw: string): number | null {
  if (!/^\d{1,7}$/.test(raw.trim())) return null
  const n = Number(raw)
  return n <= MAX_QTY ? n : null
}

/** Инвентаризация: вписали фактические остатки, сохранили — меняются только расхождения. */
export function InventoryModal({ components, onClose, onSaved }: Props) {
  const rows = useMemo(() => groupByModel(components), [components])
  const [values, setValues] = useState<Record<number, string>>({})
  const [search, setSearch] = useState('')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cardRef = useRef<HTMLDivElement>(null)
  useModalA11y(cardRef, () => {
    if (!busy) onClose()
  })

  const byId = useMemo(() => new Map(components.map((c) => [c.id, c])), [components])
  const edits = Object.entries(values).map(([id, raw]) => {
    const component = byId.get(Number(id))!
    const qty = parseQty(raw)
    return { component, raw, qty, changed: qty !== null && qty !== component.qty, invalid: raw.trim() !== '' && qty === null }
  })
  const changed = edits.filter((e) => e.changed)
  const invalid = edits.filter((e) => e.invalid)

  const needle = search.trim().toLowerCase()
  const visible = rows.filter(
    (r: ModelRow) => !needle || [r.model, ...r.members].some((n) => n.toLowerCase().includes(needle)),
  )

  async function save() {
    if (busy || changed.length === 0 || invalid.length > 0) return
    setBusy(true)
    setError(null)
    try {
      const result = await saveInventory(
        changed.map((e) => ({ component_id: e.component.id, qty: e.qty as number })),
        comment,
      )
      await onSaved(result)
      onClose()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить — проверьте соединение и попробуйте снова')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={() => !busy && onClose()}>
      <div
        ref={cardRef}
        tabIndex={-1}
        className="modal__card modal__card--wide"
        role="dialog"
        aria-modal="true"
        aria-label="Инвентаризация"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <h2 className="modal__title">Инвентаризация</h2>
          <button type="button" className="modal__close" onClick={onClose} disabled={busy} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="modal__body">
          <p className="field__hint" style={{ margin: 0 }}>
            Впишите, сколько реально лежит на складе. Сохранятся только позиции, где число отличается от учёта: каждая
            станет записью «Корректировка» в журнале. Пустое поле — не менять.
          </p>
          <input
            className="input"
            type="search"
            placeholder="Найти модель"
            aria-label="Найти модель"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <div className="tablewrap invwrap">
            <table className="table table--stock">
              <thead>
                <tr>
                  <th>Модель</th>
                  {COLUMNS.map((c) => (
                    <th key={c.key} className="num">
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visible.map((r) => (
                  <tr key={r.model}>
                    <td className="strong">
                      {r.model}
                      {r.members.length > 0 && <span className="groupnote">Общий остаток</span>}
                    </td>
                    {COLUMNS.map((c) => {
                      const comp = r[c.key]
                      if (!comp) return <td key={c.key} className="num muted">—</td>
                      const raw = values[comp.id] ?? ''
                      const qty = parseQty(raw)
                      const state = raw.trim() === '' ? '' : qty === null ? ' invinput--bad' : qty !== comp.qty ? ' invinput--changed' : ''
                      return (
                        <td key={c.key} className="num">
                          <input
                            className={`input invinput${state}`}
                            inputMode="numeric"
                            placeholder={String(comp.qty)}
                            value={raw}
                            aria-label={`${c.label}, ${r.model}: факт (по учёту ${comp.qty})`}
                            aria-invalid={state.includes('bad') || undefined}
                            onChange={(e) => setValues((v) => ({ ...v, [comp.id]: e.target.value }))}
                          />
                        </td>
                      )
                    })}
                  </tr>
                ))}
                {visible.length === 0 && (
                  <tr>
                    <td colSpan={4} className="muted">
                      Ничего не найдено
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <label className="field">
            <span className="field__label">Комментарий к инвентаризации</span>
            <input
              className="input"
              value={comment}
              maxLength={200}
              onChange={(e) => setComment(e.target.value)}
              placeholder="например: ревизия 30 ноября"
            />
          </label>
          {invalid.length > 0 && (
            <div className="form-msg form-msg--err" role="alert">
              Исправьте {invalid.length} {invalid.length === 1 ? 'поле' : 'полей'}: нужно целое число от 0 до {MAX_QTY.toLocaleString('ru-RU')}.
            </div>
          )}
          {error && (
            <div className="form-msg form-msg--err" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="modal__actions">
          <span className="field__hint" style={{ marginRight: 'auto' }} aria-live="polite">
            Расхождений: {changed.length}
          </span>
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => void save()}
            disabled={busy || changed.length === 0 || invalid.length > 0}
          >
            {busy ? 'Сохранение…' : `Сохранить${changed.length ? ` (${changed.length})` : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}
