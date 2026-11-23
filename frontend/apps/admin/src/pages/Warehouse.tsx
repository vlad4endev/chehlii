import { useEffect, useRef, useState, type FormEvent } from 'react'

import { ApiError } from '../api'
import { useAuth } from '../auth'
import {
  type DefectReason,
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
  postDefect,
  postSupply,
} from '../warehouseApi'
import { MovementsLog } from './MovementsLog'
import { PendingDeductions } from './PendingDeductions'
import { StockActionModal } from './StockActionModal'
import { StockGroupsModal } from './StockGroupsModal'
import { StockMatrix } from './StockMatrix'

const DEFECT_OPTIONS: { value: DefectReason; label: string }[] = [
  { value: 'defect_supplier', label: 'Брак поставщика' },
  { value: 'defect_print', label: 'Брак печати' },
  { value: 'defect_glue', label: 'Брак склейки' },
]

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

  const [supplyKind, setSupplyKind] = useState<StockKind>('base')
  const [supplyModel, setSupplyModel] = useState('')
  const [supplyPlate, setSupplyPlate] = useState<PlateType>('black')
  const [supplyQty, setSupplyQty] = useState(1)
  const [supplyComment, setSupplyComment] = useState('')

  const [defectKind, setDefectKind] = useState<StockKind>('base')
  const [defectModel, setDefectModel] = useState('')
  const [defectPlate, setDefectPlate] = useState<PlateType>('black')
  const [defectQty, setDefectQty] = useState(1)
  const [defectReason, setDefectReason] = useState<DefectReason>('defect_supplier')
  const [defectComment, setDefectComment] = useState('')

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
      if (!supplyModel && mdl[0]) setSupplyModel(mdl[0])
      if (!defectModel && mdl[0]) setDefectModel(mdl[0])
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

  async function onSupply(e: FormEvent) {
    e.preventDefault()
    setBusy('supply')
    try {
      await postSupply({
        kind: supplyKind,
        model_name: supplyModel,
        plate_type: supplyKind === 'plate' ? supplyPlate : null,
        qty: Number(supplyQty) || 0,
        comment: supplyComment || undefined,
      })
      setSupplyQty(1)
      setSupplyComment('')
      setPurchase(null)
      await reload()
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Не удалось оформить поставку')
    } finally {
      setBusy(null)
    }
  }

  async function onDefect(e: FormEvent) {
    e.preventDefault()
    setBusy('defect')
    try {
      await postDefect({
        kind: defectKind,
        model_name: defectModel,
        plate_type: defectKind === 'plate' ? defectPlate : null,
        qty: Number(defectQty) || 0,
        reason: defectReason,
        comment: defectComment || undefined,
      })
      setDefectQty(1)
      setDefectComment('')
      setPurchase(null)
      await reload()
    } catch (err) {
      alert(err instanceof ApiError ? err.message : 'Не удалось списать брак')
    } finally {
      setBusy(null)
    }
  }

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

          <div className="grid2" style={{ display: 'grid', gap: 24, gridTemplateColumns: '1fr 1fr' }}>
            <section className="trash-block">
              <div className="field__label">Поставка</div>
              <form className="form" onSubmit={onSupply}>
                <label className="field">
                  <span className="field__label">Вид</span>
                  <select
                    className="input"
                    value={supplyKind}
                    onChange={(e) => setSupplyKind(e.target.value as StockKind)}
                  >
                    <option value="base">Балванка</option>
                    <option value="plate">Пластина</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field__label">Модель</span>
                  <select
                    className="input"
                    value={supplyModel}
                    onChange={(e) => setSupplyModel(e.target.value)}
                    required
                  >
                    {models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                {supplyKind === 'plate' && (
                  <label className="field">
                    <span className="field__label">Тип пластины</span>
                    <select
                      className="input"
                      value={supplyPlate}
                      onChange={(e) => setSupplyPlate(e.target.value as PlateType)}
                    >
                      <option value="black">Чёрная</option>
                      <option value="silver">Серебро</option>
                    </select>
                  </label>
                )}
                <label className="field">
                  <span className="field__label">Количество</span>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={supplyQty}
                    onChange={(e) => setSupplyQty(Number(e.target.value))}
                    required
                  />
                </label>
                <label className="field">
                  <span className="field__label">Комментарий</span>
                  <input
                    className="input"
                    value={supplyComment}
                    onChange={(e) => setSupplyComment(e.target.value)}
                    placeholder="необязательно"
                  />
                </label>
                <button className="btn btn--primary" type="submit" disabled={busy === 'supply'}>
                  {busy === 'supply' ? 'Сохранение…' : 'Оприходовать'}
                </button>
              </form>
            </section>

            <section className="trash-block">
              <div className="field__label">Списание брака</div>
              <form className="form" onSubmit={onDefect}>
                <label className="field">
                  <span className="field__label">Вид</span>
                  <select
                    className="input"
                    value={defectKind}
                    onChange={(e) => setDefectKind(e.target.value as StockKind)}
                  >
                    <option value="base">Балванка</option>
                    <option value="plate">Пластина</option>
                  </select>
                </label>
                <label className="field">
                  <span className="field__label">Модель</span>
                  <select
                    className="input"
                    value={defectModel}
                    onChange={(e) => setDefectModel(e.target.value)}
                    required
                  >
                    {models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </label>
                {defectKind === 'plate' && (
                  <label className="field">
                    <span className="field__label">Тип пластины</span>
                    <select
                      className="input"
                      value={defectPlate}
                      onChange={(e) => setDefectPlate(e.target.value as PlateType)}
                    >
                      <option value="black">Чёрная</option>
                      <option value="silver">Серебро</option>
                    </select>
                  </label>
                )}
                <label className="field">
                  <span className="field__label">Причина</span>
                  <select
                    className="input"
                    value={defectReason}
                    onChange={(e) => setDefectReason(e.target.value as DefectReason)}
                  >
                    {DEFECT_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span className="field__label">Количество</span>
                  <input
                    className="input"
                    type="number"
                    min={1}
                    value={defectQty}
                    onChange={(e) => setDefectQty(Number(e.target.value))}
                    required
                  />
                </label>
                <label className="field">
                  <span className="field__label">Комментарий</span>
                  <input
                    className="input"
                    value={defectComment}
                    onChange={(e) => setDefectComment(e.target.value)}
                    placeholder="необязательно"
                  />
                </label>
                <button className="btn btn--danger" type="submit" disabled={busy === 'defect'}>
                  {busy === 'defect' ? 'Списание…' : 'Списать брак'}
                </button>
              </form>
            </section>
          </div>

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

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card" onClick={(e) => e.stopPropagation()}>
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
