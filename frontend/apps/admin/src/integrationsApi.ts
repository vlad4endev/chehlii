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

export const checkCdek = () =>
  apiSend<ConnectionStatus>('POST', '/admin/integrations/cdek/check')
