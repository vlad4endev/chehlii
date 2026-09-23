import { apiGet, apiSend } from './api'

export interface IntegrationField {
  key: string
  label: string
  secret: boolean
  placeholder: string | null
  is_set: boolean
  value: string | null // для секретов всегда null
}

export interface IntegrationGroup {
  id: string
  title: string
  hint: string
  fields: IntegrationField[]
}

export const fetchIntegrations = () => apiGet<IntegrationGroup[]>('/admin/integrations')

export const saveIntegrations = (values: Record<string, string>) =>
  apiSend<IntegrationGroup[]>('PATCH', '/admin/integrations', { values })

/** Статус живой связи со шлюзом (проба по сохранённым кредам, заказов не создаёт). */
export interface ConnectionStatus {
  ok: boolean
  detail: string
}

export const checkYandexPay = () =>
  apiSend<ConnectionStatus>('POST', '/admin/integrations/yandex-pay/check')

export const checkYandexDelivery = () =>
  apiSend<ConnectionStatus>('POST', '/admin/integrations/yandex-delivery/check')

export interface YandexWarehouse {
  station_id: string | null
  client_warehouse_id: string | null
  name: string | null
  city: string | null
  street: string | null
  house: string | null
}

export interface YandexWarehouseCreated {
  station_id: string
  reused: boolean
  detail: string
}

export const listYandexWarehouses = () =>
  apiGet<YandexWarehouse[]>('/admin/integrations/yandex-delivery/warehouses')

export const createYandexWarehouse = (body?: {
  phone?: string
  contact_name?: string
  email?: string
}) =>
  apiSend<YandexWarehouseCreated>('POST', '/admin/integrations/yandex-delivery/warehouses', body ?? {})

export const checkCdek = () =>
  apiSend<ConnectionStatus>('POST', '/admin/integrations/cdek/check')

export const checkOzon = () =>
  apiSend<ConnectionStatus>('POST', '/admin/integrations/ozon/check')

export const checkYandexDisk = () =>
  apiSend<ConnectionStatus>('POST', '/admin/integrations/yandex-disk/check')

export const yandexDiskOAuthUrl = () =>
  apiGet<{ url: string; response_type: string }>('/admin/integrations/yandex-disk/oauth-url')

export const completeYandexDiskOAuth = (body: {
  access_token?: string
  code?: string
  redirect_uri?: string
}) => apiSend<ConnectionStatus>('POST', '/admin/integrations/yandex-disk/oauth', body)

export const checkRobokassa = () =>
  apiSend<ConnectionStatus>('POST', '/admin/integrations/robokassa/check')
