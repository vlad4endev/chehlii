import { useMemo, useState } from 'react'

import type { PlateType, StockComponent, StockKind } from '../warehouseApi'

/** Изделие, по которому фильтруем: всё сразу или одна колонка склада. */
type ItemFilter = 'all' | 'base' | 'silver' | 'black'

const ITEM_FILTERS: { value: ItemFilter; label: string }[] = [
  { value: 'all', label: 'Все изделия' },
  { value: 'base', label: 'Балванки' },
  { value: 'silver', label: 'Пластины · серебро' },
  { value: 'black', label: 'Пластины · чёрные' },
]

// prefix сворачивается в «Пл.» на узких экранах, чтобы три колонки помещались без прокрутки.
const COLUMNS: { key: Exclude<ItemFilter, 'all'>; prefix?: string; short?: string; label: string }[] = [
  { key: 'base', label: 'Балванка' },
  { key: 'silver', prefix: 'Пластина', short: 'Пл.', label: 'серебро' },
  { key: 'black', prefix: 'Пластина', short: 'Пл.', label: 'чёрная' },
]

interface ModelRow {
  model: string
  base?: StockComponent
  silver?: StockComponent
  black?: StockComponent
}

function columnOf(c: StockComponent): Exclude<ItemFilter, 'all'> | null {
  if (c.kind === ('base' satisfies StockKind)) return 'base'
  const plate: PlateType | null = c.plate_type
  return plate === 'silver' || plate === 'black' ? plate : null
}

/** Одна строка на модель: балванка и обе пластины рядом, вместо плоского списка. */
export function groupByModel(components: StockComponent[]): ModelRow[] {
  const rows = new Map<string, ModelRow>()
  for (const c of components) {
    const col = columnOf(c)
    if (!col) continue
    const row = rows.get(c.model_name) ?? { model: c.model_name }
    row[col] = c
    rows.set(c.model_name, row)
  }
  return [...rows.values()]
}

interface Props {
  components: StockComponent[]
  /** Править остаток может только админ; печатнику ячейки доступны только для чтения. */
  canEdit: boolean
  onEdit: (component: StockComponent) => void
}

export function StockMatrix({ components, canEdit, onEdit }: Props) {
  const [item, setItem] = useState<ItemFilter>('all')
  const [model, setModel] = useState('')
  const [search, setSearch] = useState('')
  const [onlyEmpty, setOnlyEmpty] = useState(false)

  const all = useMemo(() => groupByModel(components), [components])
  const columns = COLUMNS.filter((c) => item === 'all' || c.key === item)

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return all.filter((r) => {
      if (model && r.model !== model) return false
      if (needle && !r.model.toLowerCase().includes(needle)) return false
      if (onlyEmpty) {
        const shown = columns.map((c) => r[c.key]).filter((c): c is StockComponent => !!c)
        if (!shown.some((c) => c.qty === 0)) return false
      }
      return true
    })
  }, [all, model, search, onlyEmpty, columns])

  const filtered = item !== 'all' || model !== '' || search !== '' || onlyEmpty
  const reset = () => {
    setItem('all')
    setModel('')
    setSearch('')
    setOnlyEmpty(false)
  }

  return (
    <div>
      <div className="stockfilters">
        <div className="segmented" role="group" aria-label="Изделие">
          {ITEM_FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              className={`segmented__btn${item === f.value ? ' segmented__btn--active' : ''}`}
              aria-pressed={item === f.value}
              onClick={() => setItem(f.value)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <label className="stockfilters__field">
          <span className="stockfilters__label">Модель</span>
          <select className="input" value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="">Все модели</option>
            {all.map((r) => (
              <option key={r.model} value={r.model}>
                {r.model}
              </option>
            ))}
          </select>
        </label>
        <label className="stockfilters__field">
          <span className="stockfilters__label">Поиск</span>
          <input
            className="input"
            type="search"
            placeholder="Например, 15 Pro"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <label className="stockfilters__check">
          <input
            type="checkbox"
            checked={onlyEmpty}
            onChange={(e) => setOnlyEmpty(e.target.checked)}
          />
          Только закончившиеся
        </label>
        {filtered && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={reset}>
            Сбросить
          </button>
        )}
      </div>

      <div className="field__hint" style={{ margin: '4px 0 10px' }} aria-live="polite">
        Показано моделей: {rows.length} из {all.length}
        {canEdit ? '. Нажмите на число, чтобы поправить остаток.' : '.'}
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          {all.length === 0 ? 'На складе пока нет позиций.' : 'По выбранным фильтрам ничего нет.'}
          {filtered && (
            <div style={{ marginTop: 12 }}>
              <button type="button" className="btn btn--ghost btn--sm" onClick={reset}>
                Сбросить фильтры
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="tablewrap">
          <table className="table table--stock">
            <thead>
              <tr>
                <th>Модель</th>
                {columns.map((c) => (
                  <th key={c.key} className="num">
                    {c.prefix && (
                      <>
                        <span className="th-long">{c.prefix}</span>
                        <span className="th-short">{c.short}</span>{' '}
                      </>
                    )}
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.model}>
                  <td className="strong">{r.model}</td>
                  {columns.map((c) => (
                    <td key={c.key} className="num">
                      <QtyCell
                        component={r[c.key]}
                        label={`${c.prefix ? c.prefix + ' ' : ''}${c.label}, ${r.model}`}
                        canEdit={canEdit}
                        onEdit={onEdit}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function QtyCell({
  component,
  label,
  canEdit,
  onEdit,
}: {
  component?: StockComponent
  label: string
  canEdit: boolean
  onEdit: (component: StockComponent) => void
}) {
  if (!component) return <span className="muted">—</span>
  const cls = `mono${component.qty === 0 ? ' stock--empty' : ''}`
  if (!canEdit) return <span className={cls}>{component.qty}</span>
  return (
    <button
      type="button"
      className={`qtybtn ${cls}`}
      aria-label={`${label}: остаток ${component.qty}. Изменить`}
      onClick={() => onEdit(component)}
    >
      {component.qty}
    </button>
  )
}
