import { apiGet, apiSend } from './api'
import type { Role } from './api'

export interface AdminUserRow {
  id: number
  email: string
  full_name: string | null
  role: Role
  is_active: boolean
  created_at: string
}

export interface UserCreate {
  email: string
  full_name?: string | null
  role: Role
  password: string
}

export interface UserPatch {
  full_name?: string | null
  role?: Role
  is_active?: boolean
  password?: string
}

export const ROLE_LABEL: Record<Role, string> = {
  admin: 'Администратор',
  designer: 'Дизайнер',
}

export const fetchUsers = () => apiGet<AdminUserRow[]>('/admin/users')
export const createUser = (body: UserCreate) => apiSend<AdminUserRow>('POST', '/admin/users', body)
export const updateUser = (id: number, body: UserPatch) =>
  apiSend<AdminUserRow>('PATCH', `/admin/users/${id}`, body)
export const deleteUser = (id: number) => apiSend<void>('DELETE', `/admin/users/${id}`)
