import { useEffect, useRef, useState } from 'react'

import { ApiError, apiGet, apiSend, apiUpload, mediaUrl } from '../api'
import { setLogoUrl } from '../brand'

const ACCEPT = 'image/png,image/jpeg,image/webp,image/gif'

/** Смена логотипа без разработчика: загрузить файл → сохранить → обновляется везде. */
export function LogoPanel() {
  const [saved, setSaved] = useState<string | null>(null) // что сейчас на сайте
  const [draft, setDraft] = useState<string | null>(null) // что выбрано в форме
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    apiGet<{ logo_url: string | null }>('/admin/brand/logo')
      .then((r) => {
        setSaved(r.logo_url)
        setDraft(r.logo_url)
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить настройки'))
      .finally(() => setLoading(false))
  }, [])

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setDone(null)
    setUploading(true)
    try {
      const r = await apiUpload<{ url: string }>('/admin/media', file)
      setDraft(r.url)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить файл — проверьте соединение и попробуйте снова')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function save() {
    if (saving) return
    setSaving(true)
    setError(null)
    setDone(null)
    try {
      const r = await apiSend<{ logo_url: string | null }>('PUT', '/admin/brand/logo', {
        logo_url: draft,
      })
      setSaved(r.logo_url)
      setDraft(r.logo_url)
      setLogoUrl(r.logo_url)
      setDone(r.logo_url ? 'Логотип обновлён' : 'Возвращён стандартный логотип')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить — проверьте соединение и попробуйте снова')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="empty">Загрузка…</div>

  const changed = draft !== saved
  const preview = draft ? mediaUrl(draft) : null

  return (
    <div className="card">
      <div className="card__head">
        <span className="card__title">Логотип</span>
        <span className="card__hint">Админка, мини-приложение и лендинг</span>
      </div>

      <div className="field">
        <span className="field__label">Сейчас</span>
        <div className="logo-preview" aria-live="polite">
          {preview ? (
            <img className="brand-logo" src={preview} alt="Выбранный логотип" style={{ height: 40 }} />
          ) : (
            <span className="muted">Стандартный знак casetop</span>
          )}
        </div>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="logo-file">
          {draft ? 'Заменить файл' : 'Загрузить логотип'}
        </label>
        <input
          id="logo-file"
          ref={fileRef}
          className="input"
          type="file"
          accept={ACCEPT}
          onChange={onFile}
          disabled={uploading || saving}
        />
        <span className="field__hint">
          PNG, JPG, WEBP или GIF. Лучше PNG с прозрачным фоном, ширина от 400 px. Высота на сайте
          подгоняется сама.
        </span>
        {uploading && <span className="field__hint">Загружаем файл…</span>}
      </div>

      {error && (
        <div className="login__error" role="alert">
          {error}
        </div>
      )}

      <div className="intcard__foot">
        {done && <span className="badge badge--green">{done}</span>}
        {draft && (
          <button
            className="btn btn--ghost btn--sm"
            onClick={() => {
              setDraft(null)
              setDone(null)
            }}
            disabled={saving || uploading}
          >
            Вернуть стандартный
          </button>
        )}
        <button className="btn btn--primary btn--sm" onClick={save} disabled={saving || uploading || !changed}>
          {saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </div>
    </div>
  )
}
