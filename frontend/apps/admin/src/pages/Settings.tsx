import { useEffect, useRef, useState } from 'react'

import { ApiError, apiGet, apiSend, apiUpload, mediaUrl } from '../api'
import { BotTexts } from './BotTexts'
import { IntegrationsPanel } from './Integrations'
import { ProxyPanel } from './ProxySettings'

type SettingsTab = 'integrations' | 'proxy' | 'bots' | 'miniapp'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'integrations', label: 'Интеграции' },
  { id: 'proxy', label: 'Прокси' },
  { id: 'bots', label: 'Боты' },
  { id: 'miniapp', label: 'Мини-приложение' },
]

export function Settings() {
  const [tab, setTab] = useState<SettingsTab>('integrations')

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Настройки</h1>
      </div>
      <div className="segmented">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`segmented__btn${tab === t.id ? ' segmented__btn--active' : ''}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'integrations' && <IntegrationsPanel onOpenProxy={() => setTab('proxy')} />}
      {tab === 'proxy' && <ProxyPanel />}
      {tab === 'bots' && <BotTexts embedded />}
      {tab === 'miniapp' && <MiniappPanel />}
    </div>
  )
}

function MiniappPanel() {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    apiGet<{ image_url: string | null; title: string | null }>('/admin/miniapp/hero')
      .then((h) => {
        setImageUrl(h.image_url)
        setTitle(h.title ?? '')
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить'))
      .finally(() => setLoading(false))
  }, [])

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setError(null)
    try {
      const r = await apiUpload<{ url: string }>('/admin/media', f)
      setImageUrl(r.url)
      setSaved(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить картинку')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function save() {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await apiSend('PUT', '/admin/miniapp/hero', { image_url: imageUrl, title })
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="empty">Загрузка…</div>

  return (
    <div className="card">
      <div className="card__head">
        <span className="card__title">Главная картинка мини-приложения</span>
        <span className="card__hint">Первый экран «Зачем вам»</span>
      </div>

      <div className="field">
        <span className="field__label">Картинка чехла</span>
        {imageUrl ? (
          <div className="miniapp-hero__preview">
            <img src={mediaUrl(imageUrl)} alt="" />
            <button className="btn btn--ghost btn--sm" onClick={() => setImageUrl(null)}>
              Убрать
            </button>
          </div>
        ) : (
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            onChange={onFile}
            className="input"
          />
        )}
      </div>

      <div className="field">
        <span className="field__label">Надпись на картинке</span>
        <input
          className="input"
          value={title}
          onChange={(e) => {
            setTitle(e.target.value)
            setSaved(false)
          }}
          placeholder="Например: Ваш чехол — только ваш"
          maxLength={120}
        />
      </div>

      {error && <div className="login__error">{error}</div>}

      <div className="intcard__foot">
        {saved && <span className="badge badge--green">Сохранено</span>}
        <button className="btn btn--primary btn--sm" onClick={save} disabled={saving}>
          {saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </div>
    </div>
  )
}
