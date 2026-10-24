import { useEffect, useRef, useState } from 'react'

import { ApiError, apiGet, apiSend, apiUpload, mediaUrl } from '../api'
import { BotTexts } from './BotTexts'
import { IntegrationsPanel } from './Integrations'
import { ProxyPanel } from './ProxySettings'

type SettingsTab = 'integrations' | 'proxy' | 'bots' | 'promo' | 'miniapp'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'integrations', label: 'Интеграции' },
  { id: 'proxy', label: 'Прокси' },
  { id: 'bots', label: 'Боты' },
  { id: 'promo', label: 'Скидки друзей' },
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
      {tab === 'promo' && <PromoPanel />}
      {tab === 'miniapp' && <MiniappPanel />}
    </div>
  )
}

interface PromoSettings {
  friend_discount_pct: number
  inviter_bonus_pct: number
  max_total_discount_pct: number
}

function PromoPanel() {
  const [friend, setFriend] = useState('0')
  const [inviter, setInviter] = useState('0')
  const [maxTotal, setMaxTotal] = useState('0')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<PromoSettings>('/admin/promo-settings')
      .then((s) => {
        setFriend(String(s.friend_discount_pct ?? 0))
        setInviter(String(s.inviter_bonus_pct ?? 0))
        setMaxTotal(String(s.max_total_discount_pct ?? 0))
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : 'Не удалось загрузить'))
      .finally(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await apiSend('PUT', '/admin/promo-settings', {
        friend_discount_pct: Number(friend) || 0,
        inviter_bonus_pct: Number(inviter) || 0,
        max_total_discount_pct: Number(maxTotal) || 0,
      })
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
        <span className="card__title">Автоматические скидки за друзей</span>
        <span className="card__hint">
          Дефолты подставляются в карточку клиента, если поля ещё 0. Ручные значения в «Клиентах» важнее.
        </span>
      </div>

      <div className="field">
        <span className="field__label">Скидка другу по промокоду, %</span>
        <input
          className="input"
          type="number"
          min={0}
          max={100}
          step={1}
          value={friend}
          onChange={(e) => {
            setFriend(e.target.value)
            setSaved(false)
          }}
        />
      </div>
      <div className="field">
        <span className="field__label">Бонус пригласившему за оплаченный заказ друга, %</span>
        <input
          className="input"
          type="number"
          min={0}
          max={100}
          step={1}
          value={inviter}
          onChange={(e) => {
            setInviter(e.target.value)
            setSaved(false)
          }}
        />
      </div>
      <div className="field">
        <span className="field__label">Потолок скидки за друзей (discount_for_slave), %</span>
        <input
          className="input"
          type="number"
          min={0}
          max={100}
          step={1}
          value={maxTotal}
          onChange={(e) => {
            setMaxTotal(e.target.value)
            setSaved(false)
          }}
        />
        <span className="field__hint">0 = без ограничения</span>
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

function MiniappPanel() {
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [glbUrl, setGlbUrl] = useState<string | null>(null)
  const [title, setTitle] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const glbRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    apiGet<{ image_url: string | null; title: string | null; glb_url: string | null }>(
      '/admin/miniapp/hero',
    )
      .then((h) => {
        setImageUrl(h.image_url)
        setTitle(h.title ?? '')
        setGlbUrl(h.glb_url)
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

  async function onGlb(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setError(null)
    try {
      const r = await apiUpload<{ url: string }>('/admin/media', f)
      setGlbUrl(r.url)
      setSaved(false)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось загрузить GLB')
    } finally {
      if (glbRef.current) glbRef.current.value = ''
    }
  }

  async function save() {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      await apiSend('PUT', '/admin/miniapp/hero', {
        image_url: imageUrl,
        title,
        glb_url: glbUrl,
      })
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
        <span className="card__hint">Первый экран лендинга / «Зачем вам»</span>
      </div>

      <div className="field">
        <span className="field__label">Картинка чехла (poster)</span>
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
        <span className="field__label">3D-модель GLB (опционально)</span>
        {glbUrl ? (
          <div className="miniapp-hero__preview">
            <code className="mono">{glbUrl}</code>
            <button className="btn btn--ghost btn--sm" onClick={() => setGlbUrl(null)}>
              Убрать
            </button>
          </div>
        ) : (
          <input
            ref={glbRef}
            type="file"
            accept=".glb,model/gltf-binary"
            onChange={onGlb}
            className="input"
          />
        )}
        <span className="field__hint">
          Требования: docs/GLB_REQUIREMENTS.md. На лендинге — model-viewer; без файла — фото.
        </span>
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
