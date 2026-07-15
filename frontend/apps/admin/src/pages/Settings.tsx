import { useEffect, useMemo, useState } from 'react'

import { ApiError } from '../api'
import { Icon } from '../icons'
import {
  type IntegrationGroup,
  fetchIntegrations,
  saveIntegrations,
} from '../integrationsApi'

const GROUP_ICON: Record<string, string> = {
  yandex_disk: 'box',
  cdek: 'broadcast',
  ozon: 'broadcast',
  payment: 'ruble',
}

export function Settings() {
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
      <div className="page__head">
        <h1 className="page__title">Настройки</h1>
      </div>
      <div className="segmented">
        <button className="segmented__btn segmented__btn--active">Интеграции</button>
      </div>
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
  edits,
  onEdit,
  onSave,
  saving,
  saved,
}: {
  group: IntegrationGroup
  icon: string
  edits: Record<string, string>
  onEdit: (key: string, value: string) => void
  onSave: () => void
  saving: boolean
  saved: boolean
}) {
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
        {saved && <span className="badge badge--green">Сохранено</span>}
        <button className="btn btn--primary btn--sm" onClick={onSave} disabled={saving || !dirty}>
          {saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </div>
    </div>
  )
}
