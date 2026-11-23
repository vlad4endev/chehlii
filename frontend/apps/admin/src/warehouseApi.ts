import { apiGet, apiSend, apiUrl, getToken } from './api'

export type StockKind = 'base' | 'plate'
export type PlateType = 'silver' | 'black'
export type DefectReason = 'defect_supplier' | 'defect_print' | 'defect_glue'

export interface StockComponent {
  id: number
  kind: StockKind
  model_name: string
  plate_type: PlateType | null
  qty: number
  available: number
  /** Модели, делящие этот остаток («универсальная» группа); у обычной модели пусто. */
  members: string[]
}

export type GroupScope = 'both' | 'base' | 'plate'

export interface StockGroup {
  id: number
  name: string
  scope: GroupScope
  models: string[]
}

export interface StockMovement {
  id: number
  component_id: number
  kind: string
  model_name: string
  plate_type: string | null
  delta: number
  reason: string
  comment: string | null
  order_id: number | null
  admin_user_id: number | null
  /** Кто сделал: имя или почта; пусто у автоматических списаний по заказу. */
  admin_name: string | null
  created_at: string
}

export interface MovementsPage {
  items: StockMovement[]
  total: number
  limit: number
  offset: number
}

export interface PurchaseRow {
  component_id: number
  kind: string
  model_name: string
  plate_type: string | null
  stock: number
  spent_lookback: number
  spend_per_day: number
  recommend: number
  lookback_days: number
  lead_days: number
  safety_days: number
}

export interface PurchaseSuggestion {
  settings: { lookback_days: number; lead_days: number; safety_days: number }
  items: PurchaseRow[]
}

export const KIND_LABEL: Record<string, string> = {
  base: 'Балванка',
  plate: 'Пластина',
}

export const PLATE_LABEL: Record<string, string> = {
  silver: 'Серебро',
  black: 'Чёрная',
}

export const REASON_LABEL: Record<string, string> = {
  supply: 'Поставка',
  defect_supplier: 'Брак поставщика',
  defect_print: 'Брак печати',
  defect_glue: 'Брак склейки',
  order: 'Заказ',
  adjust: 'Корректировка',
}

/** Модели iPhone для склада: доступно и админу, и печатнику (каталожный список — только админу). */
export const fetchWarehouseModels = () => apiGet<string[]>('/admin/warehouse/models')

export const fetchComponents = () => apiGet<StockComponent[]>('/admin/warehouse/components')

export const createComponent = (body: {
  kind: StockKind
  model_name: string
  plate_type?: PlateType | null
  qty?: number
  comment?: string
  register_canon?: boolean
}) => apiSend<StockComponent>('POST', '/admin/warehouse/components', body)

export const adjustComponent = (
  id: number,
  body: { qty: number; comment?: string },
) => apiSend<StockComponent>('PATCH', `/admin/warehouse/components/${id}`, body)

export const postSupply = (body: {
  kind: StockKind
  model_name: string
  plate_type?: PlateType | null
  qty: number
  comment?: string
}) => apiSend<StockMovement>('POST', '/admin/warehouse/supply', body)

export const postDefect = (body: {
  kind: StockKind
  model_name: string
  plate_type?: PlateType | null
  qty: number
  reason: DefectReason
  comment?: string
}) => apiSend<StockMovement>('POST', '/admin/warehouse/defect', body)

export interface MovementFilters {
  model?: string
  kind?: StockKind | ''
  reason?: string
  date_from?: string
  date_to?: string
}

function movementQuery(f: MovementFilters, limit?: number, offset?: number): string {
  const q = new URLSearchParams()
  if (limit !== undefined) q.set('limit', String(limit))
  if (offset !== undefined) q.set('offset', String(offset))
  for (const [key, value] of Object.entries(f)) if (value) q.set(key, value)
  return q.toString()
}

export const fetchMovements = (limit = 50, offset = 0, filters: MovementFilters = {}) =>
  apiGet<MovementsPage>(`/admin/warehouse/movements?${movementQuery(filters, limit, offset)}`)

/** Скачать журнал в Excel с теми же фильтрами, что на экране. */
export async function downloadMovementsXlsx(filters: MovementFilters = {}): Promise<void> {
  const res = await fetch(apiUrl(`/admin/warehouse/movements/export.xlsx?${movementQuery(filters)}`), {
    headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
  })
  if (!res.ok) throw new Error(`Не удалось скачать журнал (ошибка ${res.status})`)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = 'stock-movements.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

export const fetchPurchaseSuggestion = () =>
  apiGet<PurchaseSuggestion>('/admin/warehouse/purchase-suggestion')

export async function downloadPurchaseXlsx(): Promise<void> {
  const res = await fetch(apiUrl('/admin/warehouse/purchase-suggestion/export.xlsx'), {
    headers: getToken() ? { Authorization: `Bearer ${getToken()}` } : {},
  })
  if (!res.ok) throw new Error(`Ошибка ${res.status}`)
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'purchase.xlsx'
  a.click()
  URL.revokeObjectURL(url)
}

export const GROUP_SCOPE_LABEL: Record<GroupScope, string> = {
  both: 'Балванка и пластины',
  plate: 'Только пластины',
  base: 'Только балванка',
}

export const fetchGroups = () => apiGet<StockGroup[]>('/admin/warehouse/groups')

export const saveGroup = (body: { name: string; scope: GroupScope; models: string[] }) =>
  apiSend<StockGroup>('POST', '/admin/warehouse/groups', body)

export const deleteGroup = (name: string) =>
  apiSend<void>('DELETE', `/admin/warehouse/groups/${encodeURIComponent(name)}`)

/** Оплаченный заказ, по которому склад ещё не списан (не хватало остатка в момент оплаты). */
export interface PendingOrder {
  order_id: number
  status: string
  model_name: string
  case_name: string
  plate_type: PlateType
  is_custom: boolean
  created_at: string
  /** Хватает ли остатка прямо сейчас (с учётом более ранних заказов в очереди). */
  can_deduct: boolean
}

export const fetchPendingDeductions = () =>
  apiGet<PendingOrder[]>('/admin/warehouse/pending-deductions')

export const deductPendingOrder = (orderId: number) =>
  apiSend<{ deducted: number; remaining: number }>(
    'POST',
    `/admin/warehouse/pending-deductions/${orderId}/deduct`,
  )

export const deductAvailablePending = () =>
  apiSend<{ deducted: number; remaining: number }>(
    'POST',
    '/admin/warehouse/pending-deductions/deduct-available',
  )
