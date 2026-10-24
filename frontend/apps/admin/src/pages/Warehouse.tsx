import { useEffect, useState, type FormEvent } from 'react'

import { ApiError } from '../api'
import { fetchIphoneModels } from '../catalogApi'
import {
  type DefectReason,
  type PlateType,
  type PurchaseSuggestion,
  type StockComponent,
  type StockKind,
  type StockMovement,
  KIND_LABEL,
  PLATE_LABEL,
  REASON_LABEL,
  downloadPurchaseXlsx,
  fetchComponents,
  fetchMovements,
  fetchPurchaseSuggestion,
  postDefect,
  postSupply,
} from '../warehouseApi'

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })

const DEFECT_OPTIONS: { value: DefectReason; label: string }[] = [
  { value: 'defect_supplier', label: 'Брак поставщика' },
  { value: 'defect_print', label: 'Брак печати' },
  { value: 'defect_glue', label: 'Брак склейки' },
]

export function Warehouse() {
  const [components, setComponents] = useState<StockComponent[]>([])
  const [models, setModels] = useState<string[]>([])
  const [movements, setMovements] = useState<StockMovement[]>([])
  const [movTotal, setMovTotal] = useState(0)
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

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      const [comps, mdl, mov] = await Promise.all([
        fetchComponents(),
        fetchIphoneModels(),
        fetchMovements(50, 0),
      ])
      setComponents(comps)
      setModels(mdl)
      setMovements(mov.items)
      setMovTotal(mov.total)
      if (!supplyModel && mdl[0]) setSupplyModel(mdl[0])
      if (!defectModel && mdl[0]) setDefectModel(mdl[0])
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить склад')
    } finally {
      setLoading(false)
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
        <div className="row-actions">
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
      </div>
      <p className="page__lead">
        Балванки и пластины по моделям iPhone. Доступно к продаже = min(балванка, пластина типа
        чехла). Параметры закупки — в Настройках → Склад / закупка.
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && (
        <>
          <section className="trash-block">
            <div className="field__label">Компоненты · {components.length}</div>
            <div className="tablewrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Вид</th>
                    <th>Модель</th>
                    <th>Пластина</th>
                    <th className="num">Остаток</th>
                  </tr>
                </thead>
                <tbody>
                  {components.map((c) => (
                    <tr key={c.id}>
                      <td>{KIND_LABEL[c.kind] ?? c.kind}</td>
                      <td className="strong">{c.model_name}</td>
                      <td>
                        {c.plate_type ? PLATE_LABEL[c.plate_type] ?? c.plate_type : '—'}
                      </td>
                      <td className={`num mono${c.qty === 0 ? ' stock--empty' : ''}`}>{c.qty}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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

          <section className="trash-block">
            <div className="field__label">Движения · {movTotal}</div>
            <div className="tablewrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Когда</th>
                    <th>Вид</th>
                    <th>Модель</th>
                    <th>Δ</th>
                    <th>Причина</th>
                    <th>Комментарий</th>
                  </tr>
                </thead>
                <tbody>
                  {movements.length === 0 && (
                    <tr>
                      <td colSpan={6} className="muted">
                        Пока нет движений
                      </td>
                    </tr>
                  )}
                  {movements.map((m) => (
                    <tr key={m.id}>
                      <td className="muted mono">{fmtDate(m.created_at)}</td>
                      <td>
                        {KIND_LABEL[m.kind] ?? m.kind}
                        {m.plate_type
                          ? ` · ${PLATE_LABEL[m.plate_type] ?? m.plate_type}`
                          : ''}
                      </td>
                      <td>{m.model_name}</td>
                      <td className={`num mono${m.delta < 0 ? ' stock--empty' : ''}`}>
                        {m.delta > 0 ? `+${m.delta}` : m.delta}
                      </td>
                      <td>{REASON_LABEL[m.reason] ?? m.reason}</td>
                      <td className="muted">{m.comment || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  )
}
