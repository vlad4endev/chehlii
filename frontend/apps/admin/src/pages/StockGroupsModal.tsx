import { useEffect, useMemo, useState } from 'react'

import { ApiError } from '../api'
import {
  GROUP_SCOPE_LABEL,
  type GroupScope,
  type StockGroup,
  deleteGroup,
  fetchGroups,
  saveGroup,
} from '../warehouseApi'

interface Props {
  /** Все модели iPhone из справочника. */
  models: string[]
  onClose: () => void
  /** Вызывается после изменения групп — страница перечитывает остатки. */
  onChanged: () => void | Promise<void>
}

const SCOPES: GroupScope[] = ['both', 'plate', 'base']

/** Группы «универсальных» моделей: у моделей группы общий складской остаток. */
export function StockGroupsModal({ models, onClose, onChanged }: Props) {
  const [groups, setGroups] = useState<StockGroup[] | null>(null)
  const [editing, setEditing] = useState<StockGroup | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function load() {
    try {
      setGroups(await fetchGroups())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить группы')
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function remove(g: StockGroup) {
    const ok = window.confirm(
      `Распустить группу «${g.name}»? Весь её остаток достанется модели ${g.models[0]}, ` +
        'у остальных моделей будет 0.',
    )
    if (!ok || busy) return
    setBusy(true)
    setError(null)
    try {
      await deleteGroup(g.name)
      await load()
      await onChanged()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось распустить группу — попробуйте снова')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div
        className="modal__card"
        role="dialog"
        aria-modal="true"
        aria-label="Группы моделей"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <h2 className="modal__title">Группы моделей</h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>

        {editing ? (
          <GroupForm
            group={editing === 'new' ? null : editing}
            models={models}
            onCancel={() => setEditing(null)}
            onSaved={async () => {
              setEditing(null)
              await load()
              await onChanged()
            }}
          />
        ) : (
          <>
            <div className="modal__body">
              <p className="field__hint" style={{ margin: 0 }}>
                Если одна балванка или пластина подходит к нескольким моделям, соберите их в группу:
                остаток будет общим, а приход, брак и списание по заказу любой из моделей
                поменяют его для всех.
              </p>
              {groups === null && !error && <div className="muted">Загрузка…</div>}
              {groups?.length === 0 && <div className="muted">Групп пока нет.</div>}
              {groups?.map((g) => (
                <div key={g.id} className="grouprow">
                  <div className="grouprow__info">
                    <div className="strong">{g.name}</div>
                    <div className="field__hint">
                      {GROUP_SCOPE_LABEL[g.scope]} · {g.models.join(', ')}
                    </div>
                  </div>
                  <div className="row-actions">
                    <button className="btn btn--ghost btn--sm" onClick={() => setEditing(g)} disabled={busy}>
                      Изменить
                    </button>
                    <button className="btn btn--danger btn--sm" onClick={() => void remove(g)} disabled={busy}>
                      Распустить
                    </button>
                  </div>
                </div>
              ))}
              {error && (
                <div className="form-msg form-msg--err" role="alert">
                  {error}
                </div>
              )}
            </div>
            <div className="modal__actions">
              <button className="btn btn--ghost" onClick={onClose}>
                Закрыть
              </button>
              <button className="btn btn--primary" onClick={() => setEditing('new')}>
                + Новая группа
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function GroupForm({
  group,
  models,
  onCancel,
  onSaved,
}: {
  group: StockGroup | null
  models: string[]
  onCancel: () => void
  onSaved: () => void | Promise<void>
}) {
  const [name, setName] = useState(group?.name ?? '')
  const [scope, setScope] = useState<GroupScope>(group?.scope ?? 'both')
  const [picked, setPicked] = useState<Set<string>>(new Set(group?.models ?? []))
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return models.filter((m) => !needle || m.toLowerCase().includes(needle))
  }, [models, search])

  function toggle(model: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(model)) next.delete(model)
      else next.add(model)
      return next
    })
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (busy) return
    if (!name.trim()) return setError('Укажите название группы')
    if (picked.size < 2) return setError('Выберите минимум две модели')
    setBusy(true)
    setError(null)
    try {
      await saveGroup({ name: name.trim(), scope, models: models.filter((m) => picked.has(m)) })
      await onSaved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось сохранить — проверьте соединение и попробуйте снова')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit}>
      <div className="modal__body">
        <label className="field">
          <span className="field__label">Название группы</span>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Например: Pro Max 15–17"
            maxLength={64}
            disabled={group !== null}
            autoFocus={group === null}
          />
          {group !== null && <span className="field__hint">Название существующей группы не меняется.</span>}
        </label>

        <label className="field">
          <span className="field__label">Что общее</span>
          <select
            className="input"
            value={scope}
            onChange={(e) => setScope(e.target.value as GroupScope)}
            disabled={group !== null}
          >
            {SCOPES.map((s) => (
              <option key={s} value={s}>
                {GROUP_SCOPE_LABEL[s]}
              </option>
            ))}
          </select>
          {group !== null && <span className="field__hint">Область существующей группы не меняется.</span>}
        </label>

        <div className="field">
          <span className="field__label">Модели в группе · выбрано {picked.size}</span>
          <input
            className="input"
            type="search"
            placeholder="Найти модель"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Найти модель"
          />
          <div className="modelpick" role="group" aria-label="Модели">
            {visible.map((m) => (
              <label key={m} className="modelpick__item">
                <input type="checkbox" checked={picked.has(m)} onChange={() => toggle(m)} />
                {m}
              </label>
            ))}
            {visible.length === 0 && <span className="muted">Ничего не найдено</span>}
          </div>
          <span className="field__hint">
            Остатки выбранных моделей сложатся в общий. Модель, которую убрали из группы, начнёт с
            нуля — остаток останется группе.
          </span>
        </div>

        {error && (
          <div className="form-msg form-msg--err" role="alert">
            {error}
          </div>
        )}
      </div>
      <div className="modal__actions">
        <button type="button" className="btn btn--ghost" onClick={onCancel} disabled={busy}>
          Назад
        </button>
        <button type="submit" className="btn btn--primary" disabled={busy}>
          {busy ? 'Сохранение…' : 'Сохранить группу'}
        </button>
      </div>
    </form>
  )
}
