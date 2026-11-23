import { useEffect, useMemo, useRef, useState } from 'react'

import type { Availability, AvailabilityRow, PlateType, StockComponent, StockKind } from '../warehouseApi'

/** Состояние модели с точки зрения продаж: можно ли собрать чехол и надолго ли хватит. */
type Status = 'out' | 'low' | 'ok'

const STATUS_TILES: { key: Status; title: string }[] = [
  { key: 'out', title: 'Нельзя продать' },
  { key: 'low', title: 'Заканчивается' },
  { key: 'ok', title: 'В достатке' },
]

type Column = 'base' | 'silver' | 'black'

const COLUMNS: { key: Column; title: string; sub?: string }[] = [
  { key: 'base', title: 'Балванка' },
  { key: 'silver', title: 'Пластина', sub: 'серебро' },
  { key: 'black', title: 'Пластина', sub: 'чёрная' },
]

export interface ModelRow {
  model: string
  /** Для «универсальной» группы — модели, делящие этот остаток; у обычной модели пусто. */
  members: string[]
  base?: StockComponent
  silver?: StockComponent
  black?: StockComponent
}

function columnOf(c: StockComponent): Column | null {
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

const PLATE_NAME: Record<PlateType, string> = { black: 'Чёрная', silver: 'Серебро' }

type CountState = 'out' | 'low' | 'ok'

const countState = (count: number, threshold: number): CountState =>
  count === 0 ? 'out' : count <= threshold ? 'low' : 'ok'

/** Статус строки по данным «можно собрать»; null — по модели нет данных (не участвует в счётчиках). */
function statusOf(entries: AvailabilityRow[]): Status | null {
  if (entries.length === 0) return null
  if (entries.some((e) => e.out)) return 'out'
  if (entries.some((e) => e.low)) return 'low'
  return 'ok'
}

/** «Чёрная 4 · Серебро 0» только по продаваемым цветам; красный — нельзя, жёлтый — мало. */
function Sellable({ entries, threshold }: { entries: AvailabilityRow[]; threshold: number }) {
  if (entries.length === 0) return <span className="muted">нет данных</span>
  const used = (['black', 'silver'] as const).filter((p) => entries.some((e) => e.used_plates.includes(p)))
  if (used.length === 0) return <span className="muted">не продаётся</span>
  return (
    <span className="sellable">
      {used.map((p) => {
        const count = Math.min(...entries.map((e) => e[p]))
        return (
          <span key={p} className={`sellchip sellchip--${countState(count, threshold)}`}>
            <i className={`dot dot--${p}`} aria-hidden="true" />
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
  /** «+ Приход» в строке: открыть приход поставки по этой модели. */
  onSupply: (model: string) => void
  /** Модель, по которой только что записали операцию: строка подсвечивается и показывается. */
  highlight?: string | null
}

export function StockMatrix({ components, availability, onOpen, onSupply, highlight }: Props) {
  const flashRef = useRef<HTMLTableRowElement | null>(null)
  useEffect(() => {
    flashRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [highlight])
  const [search, setSearch] = useState('')
  // ?low=1 — переход с обзора («заканчивается на складе»): сразу показываем проблемные модели.
  const [statuses, setStatuses] = useState<Set<Status>>(() =>
    new URLSearchParams(window.location.search).get('low') === '1' ? new Set<Status>(['out', 'low']) : new Set(),
  )
  const threshold = availability?.threshold ?? 0

  const byModel = useMemo(
    () => new Map((availability?.models ?? []).map((m) => [m.model_name, m])),
    [availability],
  )
  const entriesOf = (r: ModelRow): AvailabilityRow[] => membersOf(r).map((m) => byModel.get(m)).filter(isRow)

  const all = useMemo(() => groupByModel(components), [components])

  const counts = useMemo(() => {
    const c: Record<Status, number> = { out: 0, low: 0, ok: 0 }
    for (const r of all) {
      const s = statusOf(membersOf(r).map((m) => byModel.get(m)).filter(isRow))
      if (s) c[s] += 1
    }
    return c
  }, [all, byModel])

  const rows = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return all.filter((r) => {
      if (needle && ![r.model, ...r.members].some((n) => n.toLowerCase().includes(needle))) return false
      if (statuses.size > 0) {
        const s = statusOf(membersOf(r).map((m) => byModel.get(m)).filter(isRow))
        if (!s || !statuses.has(s)) return false
      }
      return true
    })
  }, [all, search, statuses, byModel])

  const filtered = search !== '' || statuses.size > 0
  const reset = () => {
    setSearch('')
    setStatuses(new Set())
  }
  const toggle = (s: Status) =>
    setStatuses((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })

  return (
    <div>
      <div className="stocktiles" role="group" aria-label="Фильтр по состоянию">
        {STATUS_TILES.map((t) => {
          const active = statuses.has(t.key)
          return (
            <button
              key={t.key}
              type="button"
              className={`stocktile stocktile--${t.key}${active ? ' stocktile--active' : ''}`}
              aria-pressed={active}
              disabled={!availability}
              onClick={() => toggle(t.key)}
            >
              <span className="stocktile__num mono">{availability ? counts[t.key] : '—'}</span>
              <span className="stocktile__text">
                <span className="stocktile__title">{t.title}</span>
                <span className="stocktile__sub">
                  {t.key === 'out' && 'не хватает балванки или пластины'}
                  {t.key === 'low' && `можно собрать ≤ ${threshold} шт.`}
                  {t.key === 'ok' && 'хватает с запасом'}
                </span>
              </span>
            </button>
          )
        })}
      </div>

      <div className="stocksearch">
        <label className="stocksearch__field">
          <span className="sr-only">Найти модель</span>
          <input
            className="input"
            type="search"
            placeholder="Найти модель, например 15 Pro"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        {filtered && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={reset}>
            Сбросить
          </button>
        )}
        <span className="field__hint stocksearch__count" aria-live="polite">
          Моделей: {rows.length === all.length ? all.length : `${rows.length} из ${all.length}`}
        </span>
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
                {COLUMNS.map((c) => (
                  <th key={c.key} className="cell-qty">
                    {c.title}
                    {c.sub && <span className="th-sub">{c.sub}</span>}
                  </th>
                ))}
                <th title="Сколько чехлов можно продать: меньшее из балванки и пластины нужного цвета">
                  Можно собрать
                  <span className="th-sub">чехлов</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const entries = entriesOf(r)
                const status = statusOf(entries)
                return (
                  <tr
                    key={r.model}
                    ref={r.model === highlight ? flashRef : undefined}
                    className={`stockrow${status ? ` stockrow--${status}` : ''}${r.model === highlight ? ' stockrow--flash' : ''}`}
                  >
                    <td className="strong stockrow__model">
                      {r.model}
                      {status === 'out' && <span className="statuspill statuspill--out">Нельзя продать</span>}
                      {status === 'low' && <span className="statuspill statuspill--low">Заканчивается</span>}
                      {r.members.length > 0 && (
                        <span className="groupnote" title={r.members.join(', ')}>
                          Универсальная группа · {modelsWord(r.members.length)}
                        </span>
                      )}
                      <button
                        type="button"
                        className={`rowaction${status === 'out' || status === 'low' ? ' rowaction--hot' : ''}`}
                        aria-label={`Принять поставку: ${r.model}`}
                        onClick={() => onSupply(r.model)}
                      >
                        + Приход
                      </button>
                    </td>
                    {COLUMNS.map((c) => (
                      <td key={c.key} className="cell-qty" data-label={c.sub ? `${c.title} · ${c.sub}` : c.title}>
                        <QtyCell
                          component={r[c.key]}
                          threshold={threshold}
                          label={`${c.title}${c.sub ? ' ' + c.sub : ''}, ${r.model}`}
                          onOpen={onOpen}
                        />
                      </td>
                    ))}
                    <td className="stockrow__sell" data-label="Можно собрать">
                      <Sellable entries={entries} threshold={threshold} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="field__hint" style={{ margin: '10px 0 0' }}>
        Нажмите на число в таблице — откроется приход, брак или правка остатка.
      </p>
    </div>
  )
}

function QtyCell({
  component,
  threshold,
  label,
  onOpen,
}: {
  component?: StockComponent
  threshold: number
  label: string
  onOpen: (component: StockComponent) => void
}) {
  if (!component) return <span className="muted">—</span>
  const state = countState(component.qty, threshold)
  return (
    <button
      type="button"
      className={`qtybtn mono qtybtn--${state}`}
      title="Приход, брак, правка"
      aria-label={`${label}: остаток ${component.qty}. Приход, брак, правка`}
      onClick={() => onOpen(component)}
    >
      {component.qty}
    </button>
  )
}
