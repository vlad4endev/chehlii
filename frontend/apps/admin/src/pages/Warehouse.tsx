import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api'
import { useModalA11y } from '../useModalA11y'
import { useAuth } from '../auth'
import {
  type PlateType,
  type Availability,
  type PendingOrder,
  type PurchaseSuggestion,
  type StockComponent,
  type StockKind,
  KIND_LABEL,
  PLATE_LABEL,
  createComponent,
  downloadPurchaseXlsx,
  fetchComponents,
  fetchAvailability,
  fetchPendingDeductions,
  fetchWarehouseModels,
  fetchPurchaseSuggestion,
} from '../warehouseApi'
import { MovementsLog } from './MovementsLog'
import { PendingDeductions } from './PendingDeductions'
import { StockActionModal } from './StockActionModal'
import { StockGroupsModal } from './StockGroupsModal'
import { StockMatrix } from './StockMatrix'

export function Warehouse() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [components, setComponents] = useState<StockComponent[]>([])
  const [models, setModels] = useState<string[]>([])
  const [refreshKey, setRefreshKey] = useState(0)
  const [pending, setPending] = useState<PendingOrder[]>([])
  const [availability, setAvailability] = useState<Availability | null>(null)
  const [purchase, setPurchase] = useState<PurchaseSuggestion | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const [addOpen, setAddOpen] = useState(false)
  const [groupsOpen, setGroupsOpen] = useState(false)
  const [editRow, setEditRow] = useState<StockComponent | null>(null)

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

  async function onPurchase() {
    setBusy('purchase')
    try {
      setPurchase(await fetchPurchaseSuggestion())
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Не удалось рассчитать закупку')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Склад</h1>
        {isAdmin && (
          <div className="row-actions">
            <button className="btn btn--primary" onClick={() => setAddOpen(true)}>
              + Позиция
            </button>
            <button className="btn btn--ghost" onClick={() => setGroupsOpen(true)}>
              Группы моделей
            </button>
            <button
              className="btn btn--ghost"
              disabled={busy === 'purchase'}
              onClick={onPurchase}
            >
              {busy === 'purchase' ? 'Считаем…' : 'Рассчитать закупку'}
            </button>
            <button
              className="btn btn--ghost"
              onClick={() =>
                downloadPurchaseXlsx().catch((e) => alert(e instanceof Error ? e.message : String(e)))
              }
            >
              Excel закупки
            </button>
          </div>
        )}
      </div>
      <p className="page__lead">
        Балванки и пластины по моделям iPhone. Доступно к продаже = min(балванка, пластина типа
        чехла).{isAdmin ? ' Параметры закупки — в Настройках → Склад / закупка.' : ''}
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}
      {refreshError && (
        <div className="form-msg form-msg--err" role="alert">
          {refreshError}
        </div>
      )}

      {!loading && !error && (
        <>
          <PendingDeductions items={pending} onChanged={reload} />

          <section className="trash-block">
            <div className="field__label">Остатки по моделям</div>
            <StockMatrix components={components} availability={availability} onOpen={setEditRow} />
          </section>

          {purchase && (
            <section className="trash-block">
              <div className="field__label">
                Закупка · N={purchase.settings.lookback_days}, lead=
                {purchase.settings.lead_days}, safety={purchase.settings.safety_days}
              </div>
              <div className="tablewrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Вид</th>
                      <th>Модель</th>
                      <th>Пластина</th>
                      <th className="num">Остаток</th>
                      <th className="num">Расход</th>
                      <th className="num">В день</th>
                      <th className="num">Купить</th>
                    </tr>
                  </thead>
                  <tbody>
                    {purchase.items
                      .filter((r) => r.recommend > 0 || r.spent_lookback > 0)
                      .map((r) => (
                        <tr key={r.component_id}>
                          <td>{KIND_LABEL[r.kind] ?? r.kind}</td>
                          <td className="strong">{r.model_name}</td>
                          <td>
                            {r.plate_type ? PLATE_LABEL[r.plate_type] ?? r.plate_type : '—'}
                          </td>
                          <td className="num mono">{r.stock}</td>
                          <td className="num mono">{r.spent_lookback}</td>
                          <td className="num mono">{r.spend_per_day}</td>
                          <td className="num mono strong">{r.recommend}</td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
              {purchase.items.every((r) => r.recommend === 0 && r.spent_lookback === 0) && (
                <div className="empty">Нет расхода за период — закупка не нужна.</div>
              )}
            </section>
          )}

          <MovementsLog refreshKey={refreshKey} />
        </>
      )}

      {editRow && (
        <StockActionModal
          row={editRow}
          canAdjust={isAdmin}
          onClose={() => setEditRow(null)}
          onDone={async () => {
            setPurchase(null)
            await reload()
          }}
        />
      )}

      {groupsOpen && (
        <StockGroupsModal
          models={models}
          onClose={() => setGroupsOpen(false)}
          onChanged={async () => {
            setPurchase(null)
            await reload()
          }}
        />
      )}

      {addOpen && (
        <AddPositionModal
          models={models}
          busy={busy === 'add'}
          onClose={() => setAddOpen(false)}
          onSave={async (payload) => {
            setBusy('add')
            try {
              await createComponent(payload)
              setAddOpen(false)
              setPurchase(null)
              await reload()
            } catch (err) {
              alert(err instanceof ApiError ? err.message : 'Не удалось создать позицию')
            } finally {
              setBusy(null)
            }
          }}
        />
      )}
    </div>
  )
}

function AddPositionModal({
  models,
  busy,
  onClose,
  onSave,
}: {
  models: string[]
  busy: boolean
  onClose: () => void
  onSave: (payload: {
    kind: StockKind
    model_name: string
    plate_type?: PlateType | null
    qty: number
    comment?: string
    register_canon?: boolean
  }) => void | Promise<void>
}) {
  const [kind, setKind] = useState<StockKind>('base')
  const [modelName, setModelName] = useState(models[0] ?? '')
  const [plate, setPlate] = useState<PlateType>('black')
  const [qty, setQty] = useState(0)
  const [comment, setComment] = useState('')
  // YOUR TURN: true — неизвестная модель сразу в канон iPhone (+ все 3 компонента на складе).
  // false — только выбранная позиция, без канона (редко нужно).
  const [registerCanon, setRegisterCanon] = useState(true)
  const cardRef = useRef<HTMLDivElement>(null)
  useModalA11y(cardRef, () => {
    if (!busy) onClose()
  })

  return (
    <div className="modal" onClick={onClose}>
      <div
        ref={cardRef}
        tabIndex={-1}
        className="modal__card"
        role="dialog"
        aria-modal="true"
        aria-label="Новая позиция"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <h2 className="modal__title">Новая позиция</h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal__body">
          <label className="field">
            <span className="field__label">Вид</span>
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
              placeholder="iPhone 19 Pro или выберите из списка"
              required
            />
            <datalist id="wh-models">
              {models.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </label>
          {kind === 'plate' && (
            <label className="field">
              <span className="field__label">Тип пластины</span>
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
            <span className="field__label">Начальный остаток</span>
            <input
              className="input"
              type="number"
              min={0}
              value={qty}
              onChange={(e) => setQty(Math.max(0, Number(e.target.value) || 0))}
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
            <span>Добавить модель в канон (если новой ещё нет)</span>
          </label>
        </div>
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Отмена
          </button>
          <button
            className="btn btn--primary"
            disabled={busy || !modelName.trim()}
            onClick={() =>
              void onSave({
                kind,
                model_name: modelName.trim(),
                plate_type: kind === 'plate' ? plate : null,
                qty,
                comment: comment || undefined,
                register_canon: registerCanon,
              })
            }
          >
            {busy ? 'Создание…' : 'Создать'}
          </button>
        </div>
      </div>
    </div>
  )
}
