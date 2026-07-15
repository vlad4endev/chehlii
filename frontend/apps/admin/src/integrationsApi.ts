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
