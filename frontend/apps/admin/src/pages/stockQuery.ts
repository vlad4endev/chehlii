/** Поиск, фильтры и сортировка таблицы остатков — чистые функции без React. */

export type Column = 'base' | 'silver' | 'black'
export type Status = 'out' | 'low' | 'ok'

/** Что известно о строке таблицы для фильтрации и сортировки. */
export interface RowFacts {
  model: string
  members: string[]
  qty: Record<Column, number | null>
  /** Сколько чехлов можно собрать (минимум по продаваемым цветам); null — нет данных/не продаётся. */
  sellable: number | null
  status: Status | null
  /** Порядковый номер в ответе сервера — «как на сервере». */
  index: number
}

/* ── Разбор названия модели ─────────────────────────────── */

export interface ParsedModel {
  /** «15», «SE», «XS»; у нераспознанных — «Другие». */
  series: string
  /** «Базовая», «Plus», «Pro», «Pro Max», «mini», «Air», «e» или «Другое». */
  variant: string
  /** Число для сортировки по поколению; у нераспознанных 0. */
  generation: number
}

const VARIANT_ORDER = ['Базовая', 'mini', 'e', 'Air', 'Plus', 'Pro', 'Pro Max', 'Другое']

export function parseModel(name: string): ParsedModel {
  // «iPhone 17|18» — одна модель на два телефона: серия по первому, вариант общий.
  const first = name.split(/[|/]/)[0].trim()
  const tail = name.includes('|') || name.includes('/') ? name.split(/[|/]/).slice(1).join(' ').replace(/^\s*\d+/, '').trim() : ''
  const m = /^iphone\s+(\d+|se|x[rs]?)\s*(.*)$/i.exec(`${first} ${tail}`.trim())
  if (!m) return { series: 'Другие', variant: 'Другое', generation: 0 }
  const rawSeries = m[1].toUpperCase()
  const rest = m[2].toLowerCase().replace(/\s+/g, ' ').trim()
  const generation = /^\d+$/.test(rawSeries) ? Number(rawSeries) : rawSeries === 'SE' ? 8.5 : 10 // X, XS, XR — между 8 и 11
  const variants: Record<string, string> = {
    '': 'Базовая',
    plus: 'Plus',
    pro: 'Pro',
    'pro max': 'Pro Max',
    mini: 'mini',
    air: 'Air',
    e: 'e',
  }
  return { series: rawSeries, variant: variants[rest] ?? 'Другое', generation }
}

export const variantRank = (v: string): number => {
  const i = VARIANT_ORDER.indexOf(v)
  return i === -1 ? VARIANT_ORDER.length : i
}

/** Названия серий и вариантов, реально встречающиеся в списке, в удобном порядке. */
export function facetsOf(models: string[]): { series: string[]; variants: string[] } {
  const series = new Map<string, number>()
  const variants = new Set<string>()
  for (const name of models) {
    const p = parseModel(name)
    series.set(p.series, p.generation)
    variants.add(p.variant)
  }
  return {
    series: [...series.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([s]) => s),
    variants: [...variants].sort((a, b) => variantRank(a) - variantRank(b)),
  }
}

/* ── Поиск ──────────────────────────────────────────────── */

export interface Query {
  include: string[]
  exclude: string[]
}

const norm = (s: string): string =>
  s
    .toLowerCase()
    .replace(/ё/g, 'е')
    .replace(/[^\p{L}\p{N}+\s]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()

/**
 * «15 pro» — все слова должны встретиться в названии (в любом порядке);
 * «-max» исключает; «"15 pro"» — ищет фразу целиком. «iphone» можно не писать.
 */
/** Как люди пишут по-русски: «айфон 15 про макс» находит «iPhone 15 Pro Max». */
const ALIASES: Record<string, string> = {
  айфон: 'iphone',
  про: 'pro',
  макс: 'max',
  плюс: 'plus',
  мини: 'mini',
  эйр: 'air',
  аир: 'air',
  се: 'se',
}

export function parseQuery(text: string): Query {
  const include: string[] = []
  const exclude: string[] = []
  const re = /(-?)"([^"]+)"|(-?)(\S+)/g
  for (const m of text.matchAll(re)) {
    const neg = (m[1] || m[3]) === '-'
    const word = norm(m[2] ?? m[4] ?? '')
      .split(' ')
      .map((w) => ALIASES[w] ?? w)
      .join(' ')
    if (!word) continue
    ;(neg ? exclude : include).push(word)
  }
  return { include, exclude }
}

export const isEmptyQuery = (q: Query): boolean => q.include.length === 0 && q.exclude.length === 0

/** Слова ищутся как начало слова названия: «pro» находит «Pro Max», но «ro» — нет. */
function hasWord(haystack: string, needle: string): boolean {
  if (needle.includes(' ')) return ` ${haystack}`.includes(` ${needle}`)
  return haystack.split(' ').some((w) => w.startsWith(needle))
}

export function matchesQuery(names: string[], q: Query): boolean {
  if (isEmptyQuery(q)) return true
  const hay = names.map(norm)
  const hit = (w: string) => hay.some((h) => hasWord(h, w))
  return q.include.every(hit) && !q.exclude.some(hit)
}

/* ── Фильтры ────────────────────────────────────────────── */

export type QtyTarget = 'any' | Column | 'sellable'

export const QTY_TARGET_LABEL: Record<QtyTarget, string> = {
  any: 'любой позиции',
  base: 'балванки',
  silver: 'пластины · серебро',
  black: 'пластины · чёрной',
  sellable: '«можно собрать»',
}

export interface Filters {
  series: Set<string>
  variants: Set<string>
  statuses: Set<Status>
  qtyTarget: QtyTarget
  qtyMin: string
  qtyMax: string
}

export const emptyFilters = (): Filters => ({
  series: new Set(),
  variants: new Set(),
  statuses: new Set(),
  qtyTarget: 'any',
  qtyMin: '',
  qtyMax: '',
})

const toNum = (s: string): number | null => (s.trim() === '' || Number.isNaN(Number(s)) ? null : Number(s))

export const hasQtyRange = (f: Filters): boolean => toNum(f.qtyMin) !== null || toNum(f.qtyMax) !== null

/** Сколько отдельных условий включено (для бейджа на кнопке «Фильтры»). */
export function activeFilterCount(f: Filters): number {
  return (
    (f.series.size > 0 ? 1 : 0) +
    (f.variants.size > 0 ? 1 : 0) +
    (f.statuses.size > 0 ? 1 : 0) +
    (hasQtyRange(f) ? 1 : 0)
  )
}

export function matchesFilters(r: RowFacts, f: Filters): boolean {
  const p = parseModel(r.model)
  if (f.series.size > 0 && !f.series.has(p.series)) return false
  if (f.variants.size > 0 && !f.variants.has(p.variant)) return false
  if (f.statuses.size > 0 && (!r.status || !f.statuses.has(r.status))) return false
  const min = toNum(f.qtyMin)
  const max = toNum(f.qtyMax)
  if (min !== null || max !== null) {
    const values: (number | null)[] =
      f.qtyTarget === 'any'
        ? [r.qty.base, r.qty.silver, r.qty.black]
        : f.qtyTarget === 'sellable'
          ? [r.sellable]
          : [r.qty[f.qtyTarget]]
    const ok = values.some((v) => v !== null && (min === null || v >= min) && (max === null || v <= max))
    if (!ok) return false
  }
  return true
}

/* ── Сортировка ─────────────────────────────────────────── */

export type SortKey = 'server' | 'model' | 'status' | 'sellable' | Column
export interface Sort {
  key: SortKey
  dir: 'asc' | 'desc'
}

export const DEFAULT_SORT: Sort = { key: 'server', dir: 'asc' }

export interface SortOption extends Sort {
  label: string
}

export const SORT_OPTIONS: SortOption[] = [
  { key: 'server', dir: 'asc', label: 'Как в каталоге' },
  { key: 'model', dir: 'desc', label: 'Новые модели сверху' },
  { key: 'model', dir: 'asc', label: 'Старые модели сверху' },
  { key: 'status', dir: 'asc', label: 'Сначала проблемные' },
  { key: 'sellable', dir: 'asc', label: 'Можно собрать: меньше → больше' },
  { key: 'sellable', dir: 'desc', label: 'Можно собрать: больше → меньше' },
  { key: 'base', dir: 'asc', label: 'Балванок: меньше → больше' },
  { key: 'base', dir: 'desc', label: 'Балванок: больше → меньше' },
  { key: 'silver', dir: 'asc', label: 'Серебро: меньше → больше' },
  { key: 'silver', dir: 'desc', label: 'Серебро: больше → меньше' },
  { key: 'black', dir: 'asc', label: 'Чёрных: меньше → больше' },
  { key: 'black', dir: 'desc', label: 'Чёрных: больше → меньше' },
]

export const sortId = (s: Sort): string => `${s.key}:${s.dir}`
export const sameSort = (a: Sort, b: Sort): boolean => a.key === b.key && a.dir === b.dir
export const isSortKey = (k: string): k is SortKey =>
  ['server', 'model', 'status', 'sellable', 'base', 'silver', 'black'].includes(k)

const STATUS_RANK: Record<Status, number> = { out: 0, low: 1, ok: 2 }

/** Нет значения — всегда в конце, в какую бы сторону ни сортировали. */
function cmpNullable(a: number | null, b: number | null, dir: 1 | -1): number {
  if (a === null && b === null) return 0
  if (a === null) return 1
  if (b === null) return -1
  return (a - b) * dir
}

function cmpModel(a: string, b: string): number {
  const pa = parseModel(a)
  const pb = parseModel(b)
  return (
    pa.generation - pb.generation ||
    variantRank(pa.variant) - variantRank(pb.variant) ||
    a.localeCompare(b, 'ru', { numeric: true })
  )
}

export function sortRows<T extends RowFacts>(rows: T[], sort: Sort): T[] {
  const dir = sort.dir === 'asc' ? 1 : -1
  const out = [...rows]
  const tie = (a: T, b: T) => a.index - b.index
  switch (sort.key) {
    case 'server':
      return dir === 1 ? out.sort(tie) : out.sort((a, b) => -tie(a, b))
    case 'model':
      return out.sort((a, b) => cmpModel(a.model, b.model) * dir || tie(a, b))
    case 'status':
      // Внутри одного статуса — по возрастанию «можно собрать», чтобы самое горящее было выше.
      return out.sort(
        (a, b) =>
          (a.status ? STATUS_RANK[a.status] : 3) - (b.status ? STATUS_RANK[b.status] : 3) ||
          cmpNullable(a.sellable, b.sellable, 1) ||
          tie(a, b),
      )
    case 'sellable':
      return out.sort((a, b) => cmpNullable(a.sellable, b.sellable, dir) || tie(a, b))
    default: {
      const col = sort.key
      return out.sort((a, b) => cmpNullable(a.qty[col], b.qty[col], dir) || tie(a, b))
    }
  }
}
