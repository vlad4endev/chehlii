import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { ApiError } from '../api'
import { useModalA11y } from '../useModalA11y'
import { deleteGroup } from '../warehouseApi'
import {
  type IphoneModelDetail,
  createIphoneModel,
  deleteIphoneModel,
  fetchIphoneModelDetails,
  fetchIphoneModels,
  renameIphoneModel,
} from '../catalogApi'

interface Props {
  onClose: () => void
  /** Список моделей изменился — страница перечитывает каталог и склад. */
  onChanged: (next: string[]) => void | Promise<void>
}

/** Управление моделями iPhone: добавить, переименовать, удалить (если ими ещё не пользовались). */
export function ModelsManager({ onClose, onChanged }: Props) {
  const [details, setDetails] = useState<IphoneModelDetail[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [newName, setNewName] = useState('')
  // false безопаснее: модель появится на складе, а клиентам — после включения в типах чехлов.
  const [enableOnAll, setEnableOnAll] = useState(false)

  const [renaming, setRenaming] = useState<string | null>(null)
  const [renameTo, setRenameTo] = useState('')
  const [deleting, setDeleting] = useState<string | null>(null)
  const [dissolving, setDissolving] = useState<string | null>(null)

  const cardRef = useRef<HTMLDivElement>(null)
  useModalA11y(cardRef, () => {
    if (!busy) onClose()
  })

  const load = useCallback(async () => {
    try {
      setDetails(await fetchIphoneModelDetails())
      setLoadError(null)
    } catch (e) {
      setLoadError(e instanceof ApiError ? e.message : 'Не удалось загрузить модели — проверьте соединение')
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const oldGroups = useMemo(() => {
    const byName = new Map<string, string[]>()
    for (const d of details ?? []) if (d.group_name) byName.set(d.group_name, [...(byName.get(d.group_name) ?? []), d.name])
    return [...byName].map(([name, models]) => ({ name, models }))
  }, [details])

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase()
    return (details ?? []).filter((d) => !needle || d.name.toLowerCase().includes(needle))
  }, [details, search])

  /** Выполнить изменение: показать итог, перечитать список и оповестить страницу. */
  async function run(action: () => Promise<string[]>, done: string): Promise<boolean> {
    if (busy) return false
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const next = await action()
      await onChanged(next)
      await load()
      setNotice(done)
      return true
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не получилось — проверьте соединение и попробуйте снова')
      return false
    } finally {
      setBusy(false)
    }
  }

  async function add() {
    const name = newName.trim()
    if (!name) {
      setError('Укажите название модели')
      return
    }
    if (await run(() => createIphoneModel({ name, enable_on_all: enableOnAll }), `Модель «${name}» добавлена`)) {
      setNewName('')
    }
  }

  async function rename(from: string) {
    const to = renameTo.trim()
    if (!to) {
      setError('Укажите новое название')
      return
    }
    if (to === from) {
      setRenaming(null)
      return
    }
    if (await run(() => renameIphoneModel(from, to), `Переименовано: «${from}» → «${to}»`)) setRenaming(null)
  }

  /** Расформировать старую группу: остаток переходит первой модели группы. */
  async function dissolve(groupName: string) {
    if (await run(async () => { await deleteGroup(groupName); return fetchIphoneModels() }, `Группа «${groupName}» расформирована`)) {
      setDissolving(null)
    }
  }

  async function remove(name: string) {
    if (await run(() => deleteIphoneModel(name), `Модель «${name}» удалена`)) setDeleting(null)
  }

  return (
    <div className="modal" onClick={() => !busy && onClose()}>
      <div
        ref={cardRef}
        tabIndex={-1}
        className="modal__card modal__card--wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="models-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <h2 id="models-title" className="modal__title">
            Модели iPhone
          </h2>
          <button type="button" className="modal__close" onClick={onClose} disabled={busy} aria-label="Закрыть">
            ✕
          </button>
        </div>

        <div className="modal__body">
          <form
            className="modelsadd"
            onSubmit={(e) => {
              e.preventDefault()
              void add()
            }}
          >
            <label className="field modelsadd__name">
              <span className="field__label">Новая модель</span>
              <input
                className="input"
                placeholder="например, iPhone 19 Pro"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                disabled={busy}
              />
            </label>
            <button type="submit" className="btn btn--primary" disabled={busy || !newName.trim()}>
              + Добавить
            </button>
            <p className="field__hint modelsadd__hint">
              Один чехол на две модели? Назовите через вертикальную черту: <b>iPhone 17|18</b>. Остаток на складе
              будет общим, отдельные группы не нужны.
            </p>
            <label className="field field--check modelsadd__check">
              <input type="checkbox" checked={enableOnAll} onChange={(e) => setEnableOnAll(e.target.checked)} />
              <span>Сразу показывать клиентам во всех типах чехлов</span>
            </label>
          </form>

          {oldGroups.length > 0 && (
            <div className="groupsbanner" role="note">
              <b>Старые группы моделей больше не создаются.</b> Один чехол на две модели теперь оформляется одной
              моделью вроде <b>iPhone 17|18</b>. Чтобы перейти: расформируйте группу кнопкой ниже (остаток уйдёт
              первой модели группы), создайте общую модель и оприходуйте на неё остаток.
              <div className="groupsbanner__list">
                {oldGroups.map((g) => (
                  <span key={g.name} className="metachip">
                    «{g.name}»: {g.models.join(', ')}
                  </span>
                ))}
              </div>
            </div>
          )}

          {notice && (
            <div className="toast" role="status">
              <span>✓ {notice}</span>
              <button type="button" className="toast__close" onClick={() => setNotice(null)} aria-label="Скрыть сообщение">
                ✕
              </button>
            </div>
          )}
          {error && (
            <div className="form-msg form-msg--err" role="alert">
              {error}
            </div>
          )}

          <div className="modelslist">
            <div className="modelslist__head">
              <label className="modelslist__search">
                <span className="sr-only">Найти модель</span>
                <input
                  className="input"
                  type="search"
                  placeholder="Найти модель"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </label>
              <span className="field__hint">
                {details ? (shown.length === details.length ? `Всего: ${details.length}` : `${shown.length} из ${details.length}`) : ' '}
              </span>
            </div>

            {!details && !loadError && <div className="empty">Загрузка…</div>}
            {loadError && (
              <div className="form-msg form-msg--err" role="alert">
                {loadError}{' '}
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => void load()}>
                  Повторить
                </button>
              </div>
            )}
            {details && shown.length === 0 && <div className="empty">Ничего не найдено.</div>}

            <ul className="modelsrows">
              {shown.map((d) => (
                <li key={d.name} className="modelsrow">
                  {renaming === d.name ? (
                    <form
                      className="modelsrow__edit"
                      onSubmit={(e) => {
                        e.preventDefault()
                        void rename(d.name)
                      }}
                    >
                      <input
                        className="input"
                        aria-label={`Новое название для ${d.name}`}
                        value={renameTo}
                        onChange={(e) => setRenameTo(e.target.value)}
                        disabled={busy}
                        autoFocus
                      />
                      <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>
                        Сохранить
                      </button>
                      <button type="button" className="btn btn--ghost btn--sm" onClick={() => setRenaming(null)} disabled={busy}>
                        Отмена
                      </button>
                      <p className="field__hint modelsrow__note">
                        Название поменяется везде: в каталоге, на складе и в старых заказах.
                      </p>
                    </form>
                  ) : (
                    <>
                      <div className="modelsrow__info">
                        <span className="strong">{d.name}</span>
                        <span className="modelsrow__meta">
                          {d.orders > 0 && <span className="metachip">заказов: {d.orders}</span>}
                          <span className="metachip">остаток: {d.stock_qty} шт.</span>
                          {d.group_name && <span className="metachip metachip--warn">старая группа «{d.group_name}»</span>}
                        </span>
                      </div>
                      <div className="modelsrow__actions">
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          disabled={busy}
                          onClick={() => {
                            setRenaming(d.name)
                            setRenameTo(d.name)
                            setDeleting(null)
                            setError(null)
                          }}
                        >
                          Переименовать
                        </button>
                        {d.group_name && (
                          <button
                            type="button"
                            className="btn btn--ghost btn--sm"
                            disabled={busy}
                            onClick={() => {
                              setDissolving(dissolving === d.group_name ? null : d.group_name)
                              setDeleting(null)
                              setRenaming(null)
                              setError(null)
                            }}
                          >
                            Расформировать группу
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn--danger btn--sm"
                          disabled={busy}
                          onClick={() => {
                            setDeleting(deleting === d.name ? null : d.name)
                            setRenaming(null)
                            setError(null)
                          }}
                        >
                          Удалить
                        </button>
                      </div>
                      {d.group_name && dissolving === d.group_name && (
                        <div className="modelsrow__confirm modelsrow__confirm--blocked" role="group">
                          <p>
                            Расформировать группу «{d.group_name}»? Весь её остаток перейдёт первой модели группы, остальные
                            модели начнут с нуля. История движений сохранится.
                          </p>
                          <div>
                            <button type="button" className="btn btn--primary btn--sm" disabled={busy} onClick={() => void dissolve(d.group_name!)}>
                              {busy ? 'Расформировываем…' : 'Да, расформировать'}
                            </button>{' '}
                            <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => setDissolving(null)}>
                              Нет
                            </button>
                          </div>
                        </div>
                      )}
                      {deleting === d.name && (
                        <div className={`modelsrow__confirm${d.can_delete ? '' : ' modelsrow__confirm--blocked'}`} role="group">
                          {d.can_delete ? (
                            <>
                              <p>
                                Удалить «{d.name}»? Модель исчезнет из каталога и со склада. Это нельзя отменить.
                              </p>
                              <div>
                                <button type="button" className="btn btn--danger btn--sm" disabled={busy} onClick={() => void remove(d.name)}>
                                  {busy ? 'Удаляем…' : 'Да, удалить'}
                                </button>{' '}
                                <button type="button" className="btn btn--ghost btn--sm" disabled={busy} onClick={() => setDeleting(null)}>
                                  Нет
                                </button>
                              </div>
                            </>
                          ) : (
                            <>
                              <p>Удалить нельзя. {d.delete_blocker}</p>
                              <button type="button" className="btn btn--ghost btn--sm" onClick={() => setDeleting(null)}>
                                Понятно
                              </button>
                            </>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="modal__actions">
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Закрыть
          </button>
        </div>
      </div>
    </div>
  )
}
