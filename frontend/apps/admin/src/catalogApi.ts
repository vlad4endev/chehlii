import { apiGet, apiSend, apiUpload } from './api'

export interface ModelAvailability {
  model_name: string
  is_available: boolean
  photo_url: string | null
  stock: number
}

export interface CaseTypeAdmin {
  id: number
  name: string
  is_custom: boolean
  description: string | null
  photo_url: string | null
  cost: number
  margin: number
  client_price: number
  is_active: boolean
  plate_type: 'silver' | 'black' | null
  orders_count: number
  models: ModelAvailability[]
}

export interface CaseTypeInput {
  name: string
  is_custom: boolean
  description: string | null
  photo_url: string | null
  cost: number
  margin: number
  is_active: boolean
  plate_type: 'silver' | 'black'
  models: ModelAvailability[]
}

// Загружает изображение и возвращает относительный URL (`/media/catalog/…`).
export const uploadCatalogPhoto = (file: File) =>
  apiUpload<{ url: string }>('/admin/media', file).then((r) => r.url)

export const fetchCaseTypes = () => apiGet<CaseTypeAdmin[]>('/admin/case-types')
export const fetchIphoneModels = () => apiGet<string[]>('/admin/case-types/iphone-models')
export const createIphoneModel = (body: { name: string; enable_on_all?: boolean }) =>
  apiSend<string[]>('POST', '/admin/case-types/iphone-models', body)

/** Модель со сводкой: сколько заказов и остатка, можно ли удалить (и если нет — почему). */
export interface IphoneModelDetail {
  name: string
  orders: number
  stock_qty: number
  group_name: string | null
  can_delete: boolean
  delete_blocker: string | null
}

export const fetchIphoneModelDetails = () =>
  apiGet<IphoneModelDetail[]>('/admin/case-types/iphone-models/details')

// Имя может содержать «|» и «/» (модель с двойным названием) — кодируем целиком.
const modelPath = (name: string) => `/admin/case-types/iphone-models/${encodeURIComponent(name)}`

export const renameIphoneModel = (name: string, newName: string) =>
  apiSend<string[]>('PATCH', modelPath(name), { name: newName })

export const deleteIphoneModel = (name: string) => apiSend<string[]>('DELETE', modelPath(name))
export const createCaseType = (body: CaseTypeInput) =>
  apiSend<CaseTypeAdmin>('POST', '/admin/case-types', body)
export const updateCaseType = (id: number, body: CaseTypeInput) =>
  apiSend<CaseTypeAdmin>('PATCH', `/admin/case-types/${id}`, body)
export const deleteCaseType = (id: number) => apiSend<void>('DELETE', `/admin/case-types/${id}`)
