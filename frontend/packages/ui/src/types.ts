// Доменные типы каталога — общие для мини-приложения и лендинга.

export interface CaseModel {
  model_name: string
  is_available: boolean
}

export interface CaseType {
  id: number
  name: string
  is_custom: boolean
  description: string | null
  photo_url: string | null
  client_price: number
  models: CaseModel[]
}
