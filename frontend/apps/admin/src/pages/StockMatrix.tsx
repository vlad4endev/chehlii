import { useEffect, useMemo, useRef, useState } from 'react'

import {
  type Column,
  type Filters,
  type QtyTarget,
  type RowFacts,
  type Sort,
  type Status,
  DEFAULT_SORT,
  QTY_TARGET_LABEL,
  SORT_OPTIONS,
  activeFilterCount,
  emptyFilters,
  facetsOf,
  hasQtyRange,
  isEmptyQuery,
  isSortKey,
  matchesFilters,
  matchesQuery,
  parseQuery,
  sameSort,
  sortId,
  sortRows,
} from './stockQuery'
import type { Availability, AvailabilityRow, PlateType, StockComponent, StockKind } from '../warehouseApi'

const STATUS_TILES: { key: Status; title: string }[] = [
  { key: 'out', title: 'Нельзя продать' },
  { key: 'low', title: 'Заканчивается' },
  { key: 'ok', title: 'В достатке' },
]

const COLUMNS: { key: Column; title: string; sub?: string; short: string }[] = [
  { key: 'base', title: 'Балванка', short: 'Балванка' },
  { key: 'silver', title: 'Пластина', sub: 'серебро', short: 'Пл. серебро' },
  { key: 'black', title: 'Пластина', sub: 'чёрная', short: 'Пл. чёрная' },
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
const PLATE_TIP: Record<PlateType, string> = { black: 'с чёрной пластиной', silver: 'с серебряной пластиной' }

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
          <span
            key={p}
            className={`sellchip sellchip--${countState(count, threshold)}`}
            title={`Можно собрать чехлов ${PLATE_TIP[p]}: ${count}`}
          >
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

const SORT_KEY = 'casetop:admin:warehouse:sort'

function loadSort(): Sort {
  try {
    const [key, dir] = (localStorage.getItem(SORT_KEY) ?? '').split(':')
    if (isSortKey(key) && (dir === 'asc' || dir === 'desc')) return { key, dir }
  } catch {
    /* хранилище недоступно — берём порядок по умолчанию */
  }
  return DEFAULT_SORT
}

const sellableOf = (entries: AvailabilityRow[]): number | null => {
  const used = (['black', 'silver'] as const).filter((p) => entries.some((e) => e.used_plates.includes(p)))
  return used.length === 0 ? null : Math.min(...used.map((p) => Math.min(...entries.map((e) => e[p]))))
}

export function StockMatrix({ components, availability, onOpen, onSupply, highlight }: Props) {
  const flashRef = useRef<HTMLTableRowElement | null>(null)
  useEffect(() => {
    flashRef.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [highlight])
  const searchRef = useRef<HTMLInputElement>(null)

  const [search, setSearch] = useState('')
  // ?low=1 — переход с обзора («заканчивается на складе»): сразу показываем проблемные модели.
  const [filters, setFilters] = useState<Filters>(() => {
    const f = emptyFilters()
    if (new URLSearchParams(window.location.search).get('low') === '1') {
      f.statuses = new Set<Status>(['out', 'low'])
    }
    return f
  })
  const [panelOpen, setPanelOpen] = useState(false)
  const [sort, setSort] = useState<Sort>(loadSort)
  const threshold = availability?.threshold ?? 0

  // «/» — быстрый переход к поиску, как в привычных админках.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const typing = el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
      if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey) {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const byModel = useMemo(
    () => new Map((availability?.models ?? []).map((m) => [m.model_name, m])),
    [availability],
  )
  const entriesOf = (r: ModelRow): AvailabilityRow[] => membersOf(r).map((m) => byModel.get(m)).filter(isRow)

  const all = useMemo(() => groupByModel(components), [components])

  // Всё, что нужно для поиска, фильтров и сортировки, считаем один раз на строку.
  const facts = useMemo(
    () =>
      all.map((r, index): RowFacts & { row: ModelRow } => {
        const entries = membersOf(r).map((m) => byModel.get(m)).filter(isRow)
        return {
          row: r,
          model: r.model,
          members: r.members,
          qty: { base: r.base?.qty ?? null, silver: r.silver?.qty ?? null, black: r.black?.qty ?? null },
          sellable: sellableOf(entries),
          status: statusOf(entries),
          index,
        }
      }),
    [all, byModel],
  )

  const facets = useMemo(() => facetsOf(all.map((r) => r.model)), [all])

  const counts = useMemo(() => {
    const c: Record<Status, number> = { out: 0, low: 0, ok: 0 }
    for (const f of facts) if (f.status) c[f.status] += 1
    return c
  }, [facts])

  const query = useMemo(() => parseQuery(search), [search])

  const rows = useMemo(
    () =>
      sortRows(
        facts.filter((f) => matchesQuery([f.model, ...f.members], query) && matchesFilters(f, filters)),
        sort,
      ),
    [facts, query, filters, sort],
  )

  const filterCount = activeFilterCount(filters)
  const filtered = !isEmptyQuery(query) || filterCount > 0
  const reset = () => {
    setSearch('')
    setFilters(emptyFilters())
  }
  const patch = (p: Partial<Filters>) => setFilters((prev) => ({ ...prev, ...p }))
  const toggleIn = <T,>(set: Set<T>, v: T): Set<T> => {
    const next = new Set(set)
    if (next.has(v)) next.delete(v)
    else next.add(v)
    return next
  }
  const applySort = (next: Sort) => {
    setSort(next)
    try {
      localStorage.setItem(SORT_KEY, sortId(next))
    } catch {
      /* не страшно: просто не запомним */
    }
  }
  // Клик по заголовку: первый раз — от меньшего к большему, второй — наоборот, третий — как в каталоге.
  const clickHeader = (key: Column | 'model' | 'sellable') => {
    if (sort.key !== key) applySort({ key, dir: key === 'model' ? 'desc' : 'asc' })
    else if (sort.dir === (key === 'model' ? 'desc' : 'asc')) applySort({ key, dir: key === 'model' ? 'asc' : 'desc' })
    else applySort(DEFAULT_SORT)
  }
  const ariaSort = (key: Column | 'model' | 'sellable'): 'ascending' | 'descending' | 'none' =>
    sort.key !== key ? 'none' : sort.dir === 'asc' ? 'ascending' : 'descending'
  const arrow = (key: Column | 'model' | 'sellable') =>
    sort.key !== key ? '↕' : sort.dir === 'asc' ? '↑' : '↓'

  // Подписи включённых условий — их можно снять по одному.
  const chips: { id: string; label: string; clear: () => void }[] = []
  if (!isEmptyQuery(query)) chips.push({ id: 'q', label: `Поиск: ${search.trim()}`, clear: () => setSearch('') })
  if (filters.series.size > 0)
    chips.push({ id: 's', label: `Серия: ${[...filters.series].join(', ')}`, clear: () => patch({ series: new Set() }) })
  if (filters.variants.size > 0)
    chips.push({ id: 'v', label: `Вариант: ${[...filters.variants].join(', ')}`, clear: () => patch({ variants: new Set() }) })
  if (filters.statuses.size > 0)
    chips.push({
      id: 'st',
      label: `Состояние: ${STATUS_TILES.filter((t) => filters.statuses.has(t.key)).map((t) => t.title.toLowerCase()).join(', ')}`,
      clear: () => patch({ statuses: new Set() }),
    })
  if (hasQtyRange(filters)) {
    const { qtyMin: lo, qtyMax: hi } = filters
    const range = lo !== '' && hi !== '' ? (lo === hi ? lo : `${lo}–${hi}`) : lo !== '' ? `от ${lo}` : `до ${hi}`
    chips.push({
      id: 'n',
      label: `Остаток ${QTY_TARGET_LABEL[filters.qtyTarget]}: ${range}`,
      clear: () => patch({ qtyMin: '', qtyMax: '' }),
    })
  }
  if (filters.onlyGroups) chips.push({ id: 'g', label: 'Только универсальные группы', clear: () => patch({ onlyGroups: false }) })

  return (
    <div>
      <div className="stocktiles" role="group" aria-label="Фильтр по состоянию">
        {STATUS_TILES.map((t) => {
          const active = filters.statuses.has(t.key)
          return (
            <button
              key={t.key}
              type="button"
              className={`stocktile stocktile--${t.key}${active ? ' stocktile--active' : ''}`}
              aria-pressed={active}
              disabled={!availability}
              onClick={() => patch({ statuses: toggleIn(filters.statuses, t.key) })}
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
            ref={searchRef}
            className="input"
            type="search"
            placeholder="Найти модель, например 15 pro   ( / )"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape' && search) {
                e.stopPropagation()
                setSearch('')
              }
            }}
          />
        </label>
        <button
          type="button"
          className={`btn btn--ghost${panelOpen || filterCount > 0 ? ' btn--on' : ''}`}
          aria-expanded={panelOpen}
          aria-controls="stock-filter-panel"
          onClick={() => setPanelOpen((v) => !v)}
        >
          Фильтры{filterCount > 0 && <span className="btn__badge">{filterCount}</span>}
        </button>
        <label className="stocksort">
          <span className="stocksort__label">Порядок</span>
          <select
            className="input"
            value={sortId(sort)}
            onChange={(e) => {
              const found = SORT_OPTIONS.find((o) => sortId(o) === e.target.value)
              if (found) applySort({ key: found.key, dir: found.dir })
            }}
          >
            {!SORT_OPTIONS.some((o) => sameSort(o, sort)) && <option value={sortId(sort)}>Свой порядок</option>}
            {SORT_OPTIONS.map((o) => (
              <option key={sortId(o)} value={sortId(o)}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {panelOpen && (
        <div id="stock-filter-panel" className="filterpanel">
          <p className="field__hint filterpanel__tip">
            Как искать: несколько слов — найдётся модель со всеми («16 pro»); «-max» — без этого слова; в кавычках —
            фраза; слово «iPhone» писать не нужно, можно по-русски («про макс»).
          </p>
          <fieldset className="filterpanel__group">
            <legend className="filterpanel__legend">Серия</legend>
            <div className="chipset">
              {facets.series.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`chipbtn${filters.series.has(s) ? ' chipbtn--on' : ''}`}
                  aria-pressed={filters.series.has(s)}
                  onClick={() => patch({ series: toggleIn(filters.series, s) })}
                >
                  {/^\d+$/.test(s) ? `iPhone ${s}` : s}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="filterpanel__group">
            <legend className="filterpanel__legend">Вариант</legend>
            <div className="chipset">
              {facets.variants.map((v) => (
                <button
                  key={v}
                  type="button"
                  className={`chipbtn${filters.variants.has(v) ? ' chipbtn--on' : ''}`}
                  aria-pressed={filters.variants.has(v)}
                  onClick={() => patch({ variants: toggleIn(filters.variants, v) })}
                >
                  {v}
                </button>
              ))}
            </div>
          </fieldset>
          <fieldset className="filterpanel__group filterpanel__group--wide">
            <legend className="filterpanel__legend">Остаток, шт.</legend>
            <div className="qtyrange">
              <label className="qtyrange__field">
                <span className="stockfilters__label">Чего</span>
                <select
                  className="input"
                  value={filters.qtyTarget}
                  onChange={(e) => patch({ qtyTarget: e.target.value as QtyTarget })}
                >
                  {(Object.keys(QTY_TARGET_LABEL) as QtyTarget[]).map((k) => (
                    <option key={k} value={k}>
                      {QTY_TARGET_LABEL[k]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="qtyrange__field qtyrange__field--num">
                <span className="stockfilters__label">От</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  inputMode="numeric"
                  value={filters.qtyMin}
                  onChange={(e) => patch({ qtyMin: e.target.value })}
                />
              </label>
              <label className="qtyrange__field qtyrange__field--num">
                <span className="stockfilters__label">До</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  inputMode="numeric"
                  value={filters.qtyMax}
                  onChange={(e) => patch({ qtyMax: e.target.value })}
                />
              </label>
            </div>
            <div className="chipset" style={{ marginTop: 8 }}>
              <button type="button" className="chipbtn" onClick={() => patch({ qtyMin: '0', qtyMax: '0' })}>
                Ноль
              </button>
              <button
                type="button"
                className="chipbtn"
                disabled={threshold === 0}
                onClick={() => patch({ qtyMin: '', qtyMax: String(threshold) })}
              >
                Мало (≤ {threshold})
              </button>
              <button type="button" className="chipbtn" onClick={() => patch({ qtyMin: '', qtyMax: '' })}>
                Любой
              </button>
            </div>
          </fieldset>
          <label className="stockfilters__check">
            <input
              type="checkbox"
              checked={filters.onlyGroups}
              onChange={(e) => patch({ onlyGroups: e.target.checked })}
            />
            Только универсальные группы
          </label>
        </div>
      )}

      <div className="activechips" aria-live="polite">
        <span className="field__hint">Моделей: {rows.length === all.length ? all.length : `${rows.length} из ${all.length}`}</span>
        {chips.map((c) => (
          <button key={c.id} type="button" className="activechip" onClick={c.clear} aria-label={`Убрать: ${c.label}`}>
            {c.label} <span aria-hidden="true">✕</span>
          </button>
        ))}
        {filtered && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={reset}>
            Сбросить всё
          </button>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="empty">
          {all.length === 0 ? 'На складе пока нет позиций.' : 'По выбранным условиям ничего не найдено.'}
          {filtered && (
            <div style={{ marginTop: 12 }}>
              <button type="button" className="btn btn--ghost btn--sm" onClick={reset}>
                Сбросить поиск и фильтры
              </button>
            </div>
          )}
        </div>
      ) : (
        <div className="tablewrap">
          <table className="table table--stock">
            <colgroup>
              <col className="col-model" />
              <col className="col-qty" />
              <col className="col-qty" />
              <col className="col-qty" />
              <col className="col-sell" />
              <col className="col-act" />
            </colgroup>
            <thead>
              <tr>
                <th aria-sort={ariaSort('model')}>
                  <SortHead label="Модель" arrow={arrow('model')} onClick={() => clickHeader('model')} />
                </th>
                {COLUMNS.map((c) => (
                  <th key={c.key} className="cell-qty" aria-sort={ariaSort(c.key)}>
                    <SortHead label={c.title} sub={c.sub} arrow={arrow(c.key)} onClick={() => clickHeader(c.key)} />
                  </th>
                ))}
                <th
                  aria-sort={ariaSort('sellable')}
                  title="Сколько чехлов можно продать: меньшее из балванки и пластины нужного цвета"
                >
                  <SortHead label="Можно собрать" sub="чехлов по цвету пластины" arrow={arrow('sellable')} onClick={() => clickHeader('sellable')} />
                </th>
                <th className="col-act">
                  <span className="sr-only">Действие</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((f) => {
                const r = f.row
                const entries = entriesOf(r)
                const status = f.status
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
                    </td>
                    {COLUMNS.map((c) => (
                      <td key={c.key} className="cell-qty" data-label={c.short}>
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
                    <td className="stockrow__act">
                      <button
                        type="button"
                        className={`btn btn--sm ${status === 'out' || status === 'low' ? 'btn--hot' : 'btn--ghost'}`}
                        aria-label={`Принять поставку: ${r.model}`}
                        onClick={() => onSupply(r.model)}
                      >
                        + Приход
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <p className="field__hint" style={{ margin: '10px 0 0' }}>
        Чёрная и серебро — это цвет пластины: чехол собирается из балванки и пластины нужного цвета. Нажмите на число
        в таблице — откроется приход, брак или правка остатка. Заголовки колонок сортируют.
      </p>
    </div>
  )
}

function SortHead({ label, sub, arrow, onClick }: { label: string; sub?: string; arrow: string; onClick: () => void }) {
  return (
    <button type="button" className="sorthead" onClick={onClick} title="Сортировать">
      <span>
        {label}
        {sub && <span className="th-sub">{sub}</span>}
      </span>
      <span className="sorthead__arrow" aria-hidden="true">
        {arrow}
      </span>
    </button>
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
