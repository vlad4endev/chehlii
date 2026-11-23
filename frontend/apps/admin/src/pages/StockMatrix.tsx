import { useMemo, useState } from 'react'

import type { Availability, AvailabilityRow, PlateType, StockComponent, StockKind } from '../warehouseApi'

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

export interface ModelRow {
  model: string
  /** Для «универсальной» группы — модели, делящие этот остаток; у обычной модели пусто. */
  members: string[]
  base?: StockComponent
  silver?: StockComponent
  black?: StockComponent
}

function columnOf(c: StockComponent): Exclude<ItemFilter, 'all'> | null {
  if (c.kind === ('base' satisfies StockKind)) return 'base'
  const plate: PlateType | null = c.plate_type
  return plate === 'silver' || plate === 'black' ? plate : null
}

function modelsWord(n: number): string {
  const tail = n % 100
  const last = n % 10
  if (tail >= 11 && tail <= 14) return `${n} моделей`
  if (last === 1) return `${n} модель`
  if (last >= 2 && last <= 4) return `${n} модели`
  return `${n} моделей`
}

/** Одна строка на модель: балванка и обе пластины рядом, вместо плоского списка. */
export function groupByModel(components: StockComponent[]): ModelRow[] {
  const rows = new Map<string, ModelRow>()
  for (const c of components) {
    const col = columnOf(c)
    if (!col) continue
    const row = rows.get(c.model_name) ?? { model: c.model_name, members: c.members ?? [] }
    row[col] = c
    rows.set(c.model_name, row)
  }
  return [...rows.values()]
}

const isRow = (x: AvailabilityRow | undefined): x is AvailabilityRow => x !== undefined

/** Модели, чей остаток показывает строка: члены группы или сама модель. */
const membersOf = (r: ModelRow): string[] => (r.members.length > 0 ? r.members : [r.model])

const PLATE_NAME: Record<PlateType, string> = { black: 'чёрная', silver: 'серебро' }

/** «Чёрная 4 · серебро 0» только по продаваемым цветам; красный — нет, жёлтый — мало. */
function Sellable({ entries, threshold }: { entries: AvailabilityRow[]; threshold: number }) {
  if (entries.length === 0) return <span className="muted">—</span>
  const used = (['black', 'silver'] as const).filter((p) => entries.some((e) => e.used_plates.includes(p)))
  if (used.length === 0) return <span className="muted">не продаётся</span>
  return (
    <span className="sellable">
      {used.map((p) => {
        const count = Math.min(...entries.map((e) => e[p]))
        const state = count === 0 ? 'out' : count <= threshold ? 'low' : 'ok'
        return (
          <span key={p} className={`sellable__item sellable__item--${state}`}>
            {PLATE_NAME[p]} <b className="mono">{count}</b>
          </span>
        )
      })}
    </span>
  )
}

interface Props {
  components: StockComponent[]
  /** Сколько чехлов можно собрать и что заканчивается; null — ещё не загружено. */
  availability: Availability | null
  /** Нажатие на число открывает действия над позицией (приход, брак, правка). */
  onOpen: (component: StockComponent) => void
}

export function StockMatrix({ components, availability, onOpen }: Props) {
  const [item, setItem] = useState<ItemFilter>('all')
  const [model, setModel] = useState('')
  const [search, setSearch] = useState('')
  const [onlyEmpty, setOnlyEmpty] = useState(false)
  // ?low=1 — переход с обзора («заканчивается на складе»).
  const [onlyLow, setOnlyLow] = useState(() => new URLSearchParams(window.location.search).get('low') === '1')
  const byModel = useMemo(
    () => new Map((availability?.models ?? []).map((m) => [m.model_name, m])),
    [availability],
  )

  const all = useMemo(() => groupByModel(components), [components])
  const columns = COLUMNS.filter((c) => item === 'all' || c.key === item)

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return all.filter((r) => {
      if (model && r.model !== model) return false
      if (needle && ![r.model, ...r.members].some((n) => n.toLowerCase().includes(needle))) return false
      if (onlyLow && !membersOf(r).some((m) => byModel.get(m)?.low || byModel.get(m)?.out)) return false
      if (onlyEmpty) {
        const shown = columns.map((c) => r[c.key]).filter((c): c is StockComponent => !!c)
        if (!shown.some((c) => c.qty === 0)) return false
      }
      return true
    })
  }, [all, model, search, onlyEmpty, onlyLow, byModel, columns])

  const filtered = item !== 'all' || model !== '' || search !== '' || onlyEmpty || onlyLow
  const reset = () => {
    setItem('all')
    setModel('')
    setSearch('')
    setOnlyEmpty(false)
    setOnlyLow(false)
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
        <label className="stockfilters__check">
          <input type="checkbox" checked={onlyLow} onChange={(e) => setOnlyLow(e.target.checked)} />
          Мало или нет{availability ? ` (≤ ${availability.threshold})` : ''}
        </label>
        {filtered && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={reset}>
            Сбросить
          </button>
        )}
      </div>

      <div className="field__hint" style={{ margin: '4px 0 10px' }} aria-live="polite">
        Показано моделей: {rows.length} из {all.length}
        . Нажмите на число — приход, брак или правка остатка.
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
                <th title="Сколько чехлов можно собрать: минимум из балванки и пластины">Можно собрать</th>
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
                  <td className="strong">
                    {r.model}
                    {r.members.length > 0 && (
                      <span className="groupnote" title={r.members.join(', ')}>
                        Универсальная группа · {modelsWord(r.members.length)}
                      </span>
                    )}
                  </td>
                  <td>
                    <Sellable
                      entries={membersOf(r).map((m) => byModel.get(m)).filter(isRow)}
                      threshold={availability?.threshold ?? 0}
                    />
                  </td>
                  {columns.map((c) => (
                    <td key={c.key} className="num">
                      <QtyCell
                        component={r[c.key]}
                        label={`${c.prefix ? c.prefix + ' ' : ''}${c.label}, ${r.model}`}
                        onOpen={onOpen}
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
  onOpen,
}: {
  component?: StockComponent
  label: string
  onOpen: (component: StockComponent) => void
}) {
  if (!component) return <span className="muted">—</span>
  const cls = `mono${component.qty === 0 ? ' stock--empty' : ''}`
  return (
    <button
      type="button"
      className={`qtybtn ${cls}`}
      aria-label={`${label}: остаток ${component.qty}. Приход, брак, правка`}
      onClick={() => onOpen(component)}
    >
      {component.qty}
    </button>
  )
}
