import { apiGet, apiSend, apiUpload } from './api'

export interface ModelAvailability {
  model_name: string
  is_available: boolean
  photo_url: string | null
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
  models: ModelAvailability[]
}

// Загружает изображение и возвращает относительный URL (`/media/catalog/…`).
export const uploadCatalogPhoto = (file: File) =>
  apiUpload<{ url: string }>('/admin/media', file).then((r) => r.url)

export const fetchCaseTypes = () => apiGet<CaseTypeAdmin[]>('/admin/case-types')
export const fetchIphoneModels = () => apiGet<string[]>('/admin/case-types/iphone-models')
export const createCaseType = (body: CaseTypeInput) =>
  apiSend<CaseTypeAdmin>('POST', '/admin/case-types', body)
export const updateCaseType = (id: number, body: CaseTypeInput) =>
  apiSend<CaseTypeAdmin>('PATCH', `/admin/case-types/${id}`, body)
export const deleteCaseType = (id: number) => apiSend<void>('DELETE', `/admin/case-types/${id}`)
