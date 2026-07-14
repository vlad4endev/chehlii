import { apiGet, apiSend } from './api'

export type ReviewStatus = 'pending' | 'published' | 'rejected'

export interface ReviewAdmin {
  id: number
  author_name: string | null
  text: string | null
  photo_url: string | null
  status: ReviewStatus
  status_label: string
  created_at: string
}

export function fetchReviews(status?: ReviewStatus): Promise<ReviewAdmin[]> {
  const qs = status ? `?status=${status}` : ''
  return apiGet<ReviewAdmin[]>(`/admin/reviews${qs}`)
}

export const moderate = (id: number, status: ReviewStatus) =>
  apiSend<ReviewAdmin>('PATCH', `/admin/reviews/${id}`, { status })
