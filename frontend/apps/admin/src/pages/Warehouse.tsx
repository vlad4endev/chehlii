import { useEffect, useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../api'
import { useModalA11y } from '../useModalA11y'
import { useAuth } from '../auth'
import {
  type PlateType,
  type Availability,
  type PendingOrder,
  type StockComponent,
  type StockKind,
  createComponent,
  fetchComponents,
  fetchAvailability,
  fetchPendingDeductions,
  fetchWarehouseModels,
} from '../warehouseApi'
import { InventoryModal } from './InventoryModal'
import { ModelsManager } from './ModelsManager'
import { MovementsLog } from './MovementsLog'
import { PendingDeductions } from './PendingDeductions'
import { PurchaseModal } from './PurchaseModal'
import { StockActionModal } from './StockActionModal'
import { StockGroupsModal } from './StockGroupsModal'
import { StockMatrix } from './StockMatrix'
import { SupplyModal } from './SupplyModal'

export function Warehouse() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [components, setComponents] = useState<StockComponent[]>([])
  const [models, setModels] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [pending, setPending] = useState<PendingOrder[]>([])
  const [availability, setAvailability] = useState<Availability | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [purchaseOpen, setPurchaseOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)

  const [addOpen, setAddOpen] = useState(false)
  const [groupsOpen, setGroupsOpen] = useState(false)
  const [modelsOpen, setModelsOpen] = useState(false)
  const [inventoryOpen, setInventoryOpen] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  // Приход поставки: undefined — окно закрыто, '' — открыто без модели, иначе модель выбрана заранее.
  const [supplyFor, setSupplyFor] = useState<string | undefined>(undefined)
  // Модель, по которой только что записали операцию: строка коротко подсвечивается.
  const [flashModel, setFlashModel] = useState<string | null>(null)
  const [editRow, setEditRow] = useState<StockComponent | null>(null)
  const hasGroups = components.some((c) => (c.members?.length ?? 0) > 0)

  // Спиннер только при первой загрузке. Дальше данные обновляются на месте: иначе таблица
  // размонтировалась бы после каждой операции, сбрасывая фильтры и сообщения об ошибках.
  const loadedOnce = useRef(false)
  const [refreshError, setRefreshError] = useState<string | null>(null)

  async function reload() {
    const firstLoad = !loadedOnce.current
    if (firstLoad) {
      setLoading(true)
      setError(null)
    }
    try {
      const [comps, mdl, waiting, avail] = await Promise.all([
        fetchComponents(),
        fetchWarehouseModels(),
        fetchPendingDeductions(),
        fetchAvailability(),
      ])
      setAvailability(avail)
      setPending(waiting)
      setComponents(comps)
      setModels(mdl)
      setRefreshKey((k) => k + 1) // журнал подтянет новые записи, сохранив свои фильтры
      loadedOnce.current = true
      setRefreshError(null)
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Не удалось загрузить склад'
      if (firstLoad) setError(message)
      else setRefreshError(`${message}. Показаны последние загруженные данные.`)
    } finally {
      if (firstLoad) setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  // Сообщение об успехе само пропадает, чтобы не копились старые.
  useEffect(() => {
    if (!notice) return
    const t = window.setTimeout(() => setNotice(null), 8000)
    return () => window.clearTimeout(t)
  }, [notice])
  useEffect(() => {
    if (!flashModel) return
    const t = window.setTimeout(() => setFlashModel(null), 2500)
    return () => window.clearTimeout(t)
  }, [flashModel])

  function recorded(summary: string, model: string) {
    setNotice(summary)
    setFlashModel(model)
  }

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Склад</h1>
        <div className="row-actions">
          <button className="btn btn--primary" onClick={() => setSupplyFor('')}>
            + Принять поставку
          </button>
          {isAdmin && (
            <>
              <button className="btn btn--ghost" onClick={() => setPurchaseOpen(true)}>
                Что докупить
              </button>
              <button className="btn btn--ghost" onClick={() => setInventoryOpen(true)}>
                Инвентаризация
              </button>
              <ActionsMenu
                open={menuOpen}
                onOpenChange={setMenuOpen}
                items={[
                  { label: 'Модели iPhone: добавить, переименовать, удалить', onSelect: () => setModelsOpen(true) },
                  { label: 'Новая позиция', onSelect: () => setAddOpen(true) },
                  // Группы остались для уже созданных: новым «один чехол на две модели» удобнее
                  // оформлять одной моделью с названием вида «iPhone 17|18».
                  ...(hasGroups ? [{ label: 'Старые группы моделей', onSelect: () => setGroupsOpen(true) }] : []),
                ]}
              />
            </>
          )}
        </div>
      </div>
      <p className="page__lead">
        Сколько балванок и пластин лежит по каждой модели iPhone. Чехол можно продать, когда есть и балванка, и
        пластина нужного цвета.
        {isAdmin ? ' Порог «заканчивается» и сроки закупки — в Настройки → Склад / закупка.' : ''}
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}
      {notice && (
        <div className="toast" role="status">
          <span>✓ {notice}</span>
          <button type="button" className="toast__close" onClick={() => setNotice(null)} aria-label="Скрыть сообщение">
            ✕
          </button>
        </div>
      )}
      {refreshError && (
        <div className="form-msg form-msg--err" role="alert">
          {refreshError}
        </div>
      )}

      {!loading && !error && (
        <>
          <PendingDeductions items={pending} onChanged={reload} />

          <section className="whsection" aria-labelledby="wh-stock-title">
            <h2 id="wh-stock-title" className="whsection__title">
              Остатки по моделям
            </h2>
            <StockMatrix
              components={components}
              availability={availability}
              onOpen={setEditRow}
              onSupply={setSupplyFor}
              highlight={flashModel}
            />
          </section>

          <MovementsLog refreshKey={refreshKey} canReverse={isAdmin} onChanged={reload} />
        </>
      )}

      {editRow && (
        <StockActionModal
          row={editRow}
          canAdjust={isAdmin}
          onClose={() => setEditRow(null)}
          onDone={async (summary) => {
            await reload()
            recorded(summary, editRow.model_name)
          }}
        />
      )}

      {supplyFor !== undefined && (
        <SupplyModal
          components={components}
          initialModel={supplyFor || undefined}
          onClose={() => setSupplyFor(undefined)}
          onRecorded={reload}
          onDone={(summary, model) => recorded(`Приход записан — ${summary}`, model)}
        />
      )}

      {inventoryOpen && (
        <InventoryModal
          components={components}
          onClose={() => setInventoryOpen(false)}
          onSaved={async (result) => {
            await reload()
            setNotice(`Инвентаризация сохранена: изменено позиций — ${result.changed}.`)
          }}
        />
      )}

      {groupsOpen && (
        <StockGroupsModal
          models={models}
          onClose={() => setGroupsOpen(false)}
          onChanged={async () => {
            await reload()
          }}
        />
      )}

      {modelsOpen && (
        <ModelsManager
          onClose={() => setModelsOpen(false)}
          onChanged={async (next) => {
            setModels(next)
            await reload()
          }}
        />
      )}

      {purchaseOpen && <PurchaseModal onClose={() => setPurchaseOpen(false)} />}

      {addOpen && (
        <AddPositionModal
          models={models}
          onClose={() => setAddOpen(false)}
          onSave={async (payload) => {
            await createComponent(payload)
            setAddOpen(false)
            await reload()
            setNotice(`Позиция создана: ${payload.model_name}.`)
          }}
        />
      )}
    </div>
  )
}

interface MenuItem {
  label: string
  onSelect: () => void
}

/** Редкие действия («Ещё»): меню закрывается по Escape, клику снаружи и выбору пункта. */
function ActionsMenu({
  open,
  onOpenChange,
  items,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  items: MenuItem[]
}) {
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) onOpenChange(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onOpenChange(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, onOpenChange])

  return (
    <div className="menu" ref={wrapRef}>
      <button
        type="button"
        className="btn btn--ghost"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
      >
        Ещё ▾
      </button>
      {open && (
        <div className="menu__list" role="menu">
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              className="menu__item"
              onClick={() => {
                onOpenChange(false)
                it.onSelect()
              }}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function AddPositionModal({
  models,
  onClose,
  onSave,
}: {
  models: string[]
  onClose: () => void
  onSave: (payload: {
    kind: StockKind
    model_name: string
    plate_type?: PlateType | null
    qty: number
    comment?: string
    register_canon?: boolean
  }) => Promise<void>
}) {
  const [kind, setKind] = useState<StockKind>('base')
  const [modelName, setModelName] = useState('')
  const [plate, setPlate] = useState<PlateType>('black')
  const [qty, setQty] = useState(0)
  const [comment, setComment] = useState('')
  // true — неизвестная модель сразу попадает в список моделей iPhone, и для неё заводятся
  // все три позиции склада. false — только выбранная позиция (редко нужно).
  const [registerCanon, setRegisterCanon] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cardRef = useRef<HTMLFormElement>(null)
  // Пока идёт запись, закрывать нельзя: иначе человек не узнает, сохранилось ли.
  useModalA11y(cardRef, () => {
    if (!busy) onClose()
  })

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy || !modelName.trim()) return
    setBusy(true)
    setError(null)
    try {
      await onSave({
        kind,
        model_name: modelName.trim(),
        plate_type: kind === 'plate' ? plate : null,
        qty,
        comment: comment.trim() || undefined,
        register_canon: registerCanon,
      })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось создать позицию — проверьте соединение и попробуйте снова')
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={() => !busy && onClose()}>
      <form
        ref={cardRef}
        tabIndex={-1}
        className="modal__card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-position-title"
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
      >
        <div className="modal__head">
          <h2 id="add-position-title" className="modal__title">
            Новая позиция
          </h2>
          <button type="button" className="modal__close" onClick={onClose} disabled={busy} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="modal__body">
          <p className="field__hint" style={{ margin: 0 }}>
            Нужна, когда на склад приходит новая модель. Обычный приход — нажмите на число в таблице остатков.
          </p>
          <label className="field">
            <span className="field__label">Что за изделие</span>
            <select
              className="input"
              value={kind}
              onChange={(e) => setKind(e.target.value as StockKind)}
            >
              <option value="base">Балванка</option>
              <option value="plate">Пластина</option>
            </select>
          </label>
          <label className="field">
            <span className="field__label">Модель</span>
            <input
              className="input"
              list="wh-models"
              value={modelName}
              onChange={(e) => setModelName(e.target.value)}
              placeholder="Выберите из списка или введите, например iPhone 19 Pro"
              required
              autoFocus
            />
            <datalist id="wh-models">
              {models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </label>
          {kind === 'plate' && (
            <label className="field">
              <span className="field__label">Цвет пластины</span>
              <select
                className="input"
                value={plate}
                onChange={(e) => setPlate(e.target.value as PlateType)}
              >
                <option value="black">Чёрная</option>
                <option value="silver">Серебро</option>
              </select>
            </label>
          )}
          <label className="field">
            <span className="field__label">Сколько сейчас на складе, шт.</span>
            <input
              className="input"
              type="number"
              min={0}
              inputMode="numeric"
              value={qty}
              onChange={(e) => setQty(Math.max(0, Math.trunc(Number(e.target.value) || 0)))}
            />
          </label>
          <label className="field">
            <span className="field__label">Комментарий</span>
            <input
              className="input"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder="необязательно"
            />
          </label>
          <label className="field field--check">
            <input
              type="checkbox"
              checked={registerCanon}
              onChange={(e) => setRegisterCanon(e.target.checked)}
            />
            <span>Если такой модели ещё нет в списке iPhone — добавить её</span>
          </label>
          {error && (
            <div className="form-msg form-msg--err" role="alert">
              {error}
            </div>
          )}
        </div>
        <div className="modal__actions">
          <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button type="submit" className="btn btn--primary" disabled={busy || !modelName.trim()}>
            {busy ? 'Создание…' : 'Создать позицию'}
          </button>
        </div>
      </form>
    </div>
  )
}
