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

export const fetchComponents = () => apiGet<StockComponent[]>('/admin/warehouse/components')

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

export const fetchMovements = (limit = 50, offset = 0) =>
  apiGet<MovementsPage>(`/admin/warehouse/movements?limit=${limit}&offset=${offset}`)

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
