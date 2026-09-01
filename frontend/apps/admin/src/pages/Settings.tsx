import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiError, apiGet, apiSend, apiUpload, mediaUrl } from '../api'
import { Icon } from '../icons'
import {
  type ConnectionStatus,
  type IntegrationGroup,
  checkYandexDelivery,
  checkYandexPay,
  fetchIntegrations,
  saveIntegrations,
} from '../integrationsApi'
import { BotTexts } from './BotTexts'

const GROUP_ICON: Record<string, string> = {
  yandex_disk: 'box',
  yandex_delivery: 'orders',
  cdek: 'broadcast',
  ozon: 'broadcast',
  payment: 'ruble',
  yandex_pay: 'ruble',
}

// Шлюзы, у которых есть проба живой связи (см. admin/integrations.py).
const GROUP_CHECK: Record<string, () => Promise<ConnectionStatus>> = {
  yandex_pay: checkYandexPay,
  yandex_delivery: checkYandexDelivery,
}

type SettingsTab = 'integrations' | 'bots' | 'miniapp'

export function Settings() {
  const [tab, setTab] = useState<SettingsTab>('integrations')

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Настройки</h1>
      </div>
      <div className="segmented">
        <button
          className={`segmented__btn${tab === 'integrations' ? ' segmented__btn--active' : ''}`}
          onClick={() => setTab('integrations')}
        >
          Интеграции
        </button>
        <button
          className={`segmented__btn${tab === 'bots' ? ' segmented__btn--active' : ''}`}
          onClick={() => setTab('bots')}
        >
          Боты
        </button>
        <button
          className={`segmented__btn${tab === 'miniapp' ? ' segmented__btn--active' : ''}`}
          onClick={() => setTab('miniapp')}
        >
          Мини-приложение
        </button>
      </div>

      {tab === 'integrations' && <IntegrationsPanel />}
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

function IntegrationsPanel() {
  const [groups, setGroups] = useState<IntegrationGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Введённые/изменённые значения по ключу (только то, что админ трогал).
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [savingId, setSavingId] = useState<string | null>(null)
  const [savedId, setSavedId] = useState<string | null>(null)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setGroups(await fetchIntegrations())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить настройки')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function saveGroup(g: IntegrationGroup) {
    const values: Record<string, string> = {}
    for (const f of g.fields) {
      if (f.key in edits) values[f.key] = edits[f.key]
    }
    if (Object.keys(values).length === 0) return
    setSavingId(g.id)
    setSavedId(null)
    try {
      const next = await saveIntegrations(values)
      setGroups(next)
      // очистить введённые значения этой группы
      setEdits((prev) => {
        const copy = { ...prev }
        for (const f of g.fields) delete copy[f.key]
        return copy
      })
      setSavedId(g.id)
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось сохранить')
    } finally {
      setSavingId(null)
    }
  }

  return (
    <div>
      <p className="page__lead">
        Данные для подключения внешних сервисов. Секретные значения не показываются — если
        задано, отображается «задан»; чтобы изменить, введите новое.
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && (
        <div className="integrations">
          {groups.map((g) => (
            <GroupCard
              key={g.id}
              group={g}
              icon={GROUP_ICON[g.id] ?? 'plug'}
              check={GROUP_CHECK[g.id]}
              edits={edits}
              onEdit={(k, v) => setEdits((p) => ({ ...p, [k]: v }))}
              onSave={() => saveGroup(g)}
              saving={savingId === g.id}
              saved={savedId === g.id}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function GroupCard({
  group,
  icon,
  check,
  edits,
  onEdit,
  onSave,
  saving,
  saved,
}: {
  group: IntegrationGroup
  icon: string
  check?: () => Promise<ConnectionStatus>
  edits: Record<string, string>
  onEdit: (key: string, value: string) => void
  onSave: () => void
  saving: boolean
  saved: boolean
}) {
  const [checking, setChecking] = useState(false)
  const [status, setStatus] = useState<ConnectionStatus | null>(null)

  async function runCheck() {
    if (!check) return
    setChecking(true)
    setStatus(null)
    try {
      setStatus(await check())
    } catch (e) {
      setStatus({ ok: false, detail: e instanceof ApiError ? e.message : 'Проверка не удалась' })
    } finally {
      setChecking(false)
    }
  }

  const dirty = useMemo(
    () => group.fields.some((f) => f.key in edits),
    [group.fields, edits],
  )
  // «Подключено» = задан ключевой секрет (или, если секретов нет, любое поле).
  const connected = useMemo(() => {
    const secrets = group.fields.filter((f) => f.secret)
    return secrets.length > 0
      ? secrets.some((f) => f.is_set)
      : group.fields.some((f) => f.is_set)
  }, [group.fields])

  return (
    <div className="card intcard">
      <div className="intcard__head">
        <div className="intcard__icon">
          <Icon name={icon} size={20} />
        </div>
        <div>
          <div className="intcard__title">{group.title}</div>
          <div className="card__hint">{group.hint}</div>
        </div>
        {connected && <span className="badge badge--green">подключено</span>}
      </div>

      <div className="intcard__fields">
        {group.fields.map((f) => (
          <label className="field" key={f.key}>
            <span className="field__label">
              {f.label}
              {f.secret && f.is_set && <span className="muted"> · задан</span>}
            </span>
            <input
              className="input"
              type={f.secret ? 'password' : 'text'}
              placeholder={
                f.secret && f.is_set ? '•••••• (введите, чтобы изменить)' : f.placeholder || ''
              }
              value={f.key in edits ? edits[f.key] : f.secret ? '' : (f.value ?? '')}
              onChange={(e) => onEdit(f.key, e.target.value)}
              autoComplete="off"
            />
          </label>
        ))}
      </div>

      <div className="intcard__foot">
        {status && (
          <span
            className={`badge ${status.ok ? 'badge--green' : 'badge--red'}`}
            title={status.detail}
          >
            {status.ok ? 'связь есть' : 'нет связи'} · {status.detail}
          </span>
        )}
        {saved && <span className="badge badge--green">Сохранено</span>}
        {check && (
          <button className="btn btn--sm" onClick={runCheck} disabled={checking}>
            {checking ? 'Проверяем…' : 'Проверить связь'}
          </button>
        )}
        <button className="btn btn--primary btn--sm" onClick={onSave} disabled={saving || !dirty}>
          {saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </div>
    </div>
  )
}
