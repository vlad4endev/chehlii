import { useRef, useEffect, useState } from 'react'

import { ApiError, mediaUrl } from '../api'
import {
  type CaseTypeAdmin,
  type CaseTypeInput,
  createCaseType,
  deleteCaseType,
  fetchCaseTypes,
  fetchIphoneModels,
  updateCaseType,
  uploadCatalogPhoto,
} from '../catalogApi'

const money = (n: number) => new Intl.NumberFormat('ru-RU').format(n) + ' ₽'

export function Catalog() {
  const [items, setItems] = useState<CaseTypeAdmin[]>([])
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<CaseTypeAdmin | 'new' | null>(null)

  async function reload() {
    setLoading(true)
    try {
      const [list, mdl] = await Promise.all([fetchCaseTypes(), fetchIphoneModels()])
      setItems(list)
      setModels(mdl)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить каталог')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function onDelete(item: CaseTypeAdmin) {
    if (!confirm(`Удалить тип «${item.name}»?`)) return
    try {
      await deleteCaseType(item.id)
      await reload()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось удалить')
    }
  }

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Каталог</h1>
        <button className="btn btn--primary" onClick={() => setEditing('new')}>
          + Добавить тип
        </button>
      </div>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && (
        <table className="table">
          <thead>
            <tr>
              <th className="th-thumb"></th>
              <th>Название</th>
              <th>Тип</th>
              <th className="num">Себес</th>
              <th className="num">Маржа</th>
              <th className="num">Цена</th>
              <th className="num">Модели</th>
              <th className="num">Заказы</th>
              <th>Статус</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((it) => (
              <tr key={it.id} onClick={() => setEditing(it)}>
                <td className="td-thumb">
                  {(() => {
                    const cover =
                      it.photo_url ?? it.models.find((m) => m.photo_url)?.photo_url ?? null
                    const withPhoto = it.models.filter((m) => m.photo_url).length
                    return cover ? (
                      <span className="cthumb">
                        <img src={mediaUrl(cover)} alt="" />
                        {withPhoto > 0 && <span className="cthumb__badge">{withPhoto}</span>}
                      </span>
                    ) : (
                      <span className="cthumb cthumb--empty">—</span>
                    )
                  })()}
                </td>
                <td className="strong">{it.name}</td>
                <td>
                  <span className={`chip${it.is_custom ? ' chip--accent' : ''}`}>
                    {it.is_custom ? 'Кастом' : 'Стандарт'}
                  </span>
                </td>
                <td className="num mono">{money(it.cost)}</td>
                <td className="num mono">{money(it.margin)}</td>
                <td className="num mono strong">{money(it.client_price)}</td>
                <td className="num">{it.models.filter((m) => m.is_available).length}/{it.models.length}</td>
                <td className="num">{it.orders_count}</td>
                <td>
                  <span className={`dot ${it.is_active ? 'dot--on' : 'dot--off'}`} />
                  {it.is_active ? 'Активен' : 'Отключён'}
                </td>
                <td className="row-actions" onClick={(e) => e.stopPropagation()}>
                  <button className="linkbtn" onClick={() => setEditing(it)}>
                    Изменить
                  </button>
                  <button className="linkbtn linkbtn--danger" onClick={() => onDelete(it)}>
                    Удалить
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={10} className="table__empty">
                  Типов пока нет. Добавьте первый.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      {editing && (
        <CaseTypeEditor
          item={editing === 'new' ? null : editing}
          models={models}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function CaseTypeEditor({
  item,
  models,
  onClose,
  onSaved,
}: {
  item: CaseTypeAdmin | null
  models: string[]
  onClose: () => void
  onSaved: () => void
}) {
  const [name, setName] = useState(item?.name ?? '')
  const [isCustom, setIsCustom] = useState(item?.is_custom ?? false)
  const [description, setDescription] = useState(item?.description ?? '')
  const [photoUrl, setPhotoUrl] = useState(item?.photo_url ?? '')
  const [cost, setCost] = useState(item?.cost ?? 0)
  const [margin, setMargin] = useState(item?.margin ?? 0)
  const [isActive, setIsActive] = useState(item?.is_active ?? true)
  const [available, setAvailable] = useState<Set<string>>(
    () =>
      new Set(
        item
          ? item.models.filter((m) => m.is_available).map((m) => m.model_name)
          : models, // новый тип — по умолчанию все модели доступны
      ),
  )
  const [modelPhotos, setModelPhotos] = useState<Record<string, string | null>>(() =>
    Object.fromEntries((item?.models ?? []).map((m) => [m.model_name, m.photo_url])),
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function toggleModel(m: string) {
    setAvailable((prev) => {
      const next = new Set(prev)
      if (next.has(m)) next.delete(m)
      else next.add(m)
      return next
    })
  }

  function setModelPhoto(m: string, url: string | null) {
    setModelPhotos((prev) => ({ ...prev, [m]: url }))
  }

  async function save() {
    setError(null)
    if (!name.trim()) {
      setError('Укажите название')
      return
    }
    setBusy(true)
    const body: CaseTypeInput = {
      name: name.trim(),
      is_custom: isCustom,
      description: description.trim() || null,
      photo_url: photoUrl.trim() || null,
      cost: Number(cost) || 0,
      margin: Number(margin) || 0,
      is_active: isActive,
      models: models.map((m) => ({
        model_name: m,
        is_available: available.has(m),
        photo_url: modelPhotos[m] ?? null,
      })),
    }
    try {
      if (item) await updateCaseType(item.id, body)
      else await createCaseType(body)
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title">{item ? 'Изменить тип' : 'Новый тип'}</h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal__body">
          <label className="field">
            <span className="field__label">Название</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </label>

          <div className="grid2">
            <label className="field">
              <span className="field__label">Тип</span>
              <select
                className="input"
                value={isCustom ? 'custom' : 'standard'}
                onChange={(e) => setIsCustom(e.target.value === 'custom')}
              >
                <option value="standard">Стандарт</option>
                <option value="custom">Кастом</option>
              </select>
            </label>
            <label className="field field--check">
              <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
              <span>Активен (показывать в каталоге)</span>
            </label>
          </div>

          <label className="field">
            <span className="field__label">Описание</span>
            <textarea
              className="input textarea"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
            />
          </label>

          <div className="field">
            <span className="field__label">Обложка типа</span>
            <div className="field__hint">Показывается в сетке каталога и как запасное фото, если у модели нет своего.</div>
            <PhotoUpload url={photoUrl || null} onChange={(u) => setPhotoUrl(u ?? '')} size="cover" />
          </div>

          <div className="grid2">
            <label className="field">
              <span className="field__label">Себестоимость, ₽</span>
              <input
                className="input"
                type="number"
                value={cost}
                onChange={(e) => setCost(Number(e.target.value))}
              />
            </label>
            <label className="field">
              <span className="field__label">Маржа, ₽</span>
              <input
                className="input"
                type="number"
                value={margin}
                onChange={(e) => setMargin(Number(e.target.value))}
              />
            </label>
          </div>
          <div className="price-note">
            Цена для клиента: <b>{money((Number(cost) || 0) + (Number(margin) || 0))}</b>
          </div>

          <div className="field">
            <span className="field__label">Модели iPhone и фото под каждую</span>
            <div className="field__hint">Отметьте доступные модели. Загрузите фото чехла на конкретной модели — оно покажется в мини-аппе при её выборе.</div>
            <div className="modelrows">
              {models.map((m) => {
                const on = available.has(m)
                return (
                  <div key={m} className={`modelrow${on ? '' : ' modelrow--off'}`}>
                    <label className="modelrow__check">
                      <input type="checkbox" checked={on} onChange={() => toggleModel(m)} />
                      <span className="modelrow__name">{m}</span>
                    </label>
                    <PhotoUpload
                      url={modelPhotos[m] ?? null}
                      onChange={(u) => setModelPhoto(m, u)}
                      size="model"
                    />
                  </div>
                )
              })}
            </div>
          </div>

          {error && <div className="login__error">{error}</div>}
        </div>

        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={save} disabled={busy}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}

// Загрузка изображения: клик по плитке открывает выбор файла, превью — сразу
// после загрузки. size='cover' — крупнее (обложка), 'model' — компактно в строке.
function PhotoUpload({
  url,
  onChange,
  size = 'model',
}: {
  url: string | null
  onChange: (url: string | null) => void
  size?: 'cover' | 'model'
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function pick(file?: File) {
    if (!file) return
    setErr(null)
    setBusy(true)
    try {
      onChange(await uploadCatalogPhoto(file))
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Не удалось загрузить')
    } finally {
      setBusy(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <div className={`photoup photoup--${size}`}>
      <button
        type="button"
        className="photoup__thumb"
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        title={url ? 'Заменить фото' : 'Загрузить фото'}
      >
        {url ? (
          <img src={mediaUrl(url)} alt="" />
        ) : (
          <span className="photoup__ph">{busy ? '…' : '+'}</span>
        )}
      </button>
      {url && !busy && (
        <button
          type="button"
          className="photoup__rm"
          onClick={() => onChange(null)}
          aria-label="Удалить фото"
        >
          ✕
        </button>
      )}
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/gif"
        hidden
        onChange={(e) => pick(e.target.files?.[0])}
      />
      {err && <span className="photoup__err">{err}</span>}
    </div>
  )
}
