import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../api'
import {
  type MovementFilters,
  type StockMovement,
  KIND_LABEL,
  PLATE_LABEL,
  REASON_LABEL,
  downloadMovementsXlsx,
  fetchMovements,
} from '../warehouseApi'

const PAGE = 50

const REASONS = ['supply', 'defect_supplier', 'defect_print', 'defect_glue', 'order', 'adjust']

const fmtDate = (iso: string) =>
  new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })

interface Props {
  /** Меняется после каждой операции на складе — журнал подтягивает свежие записи. */
  refreshKey: number
}

/** Журнал движений: фильтры, «показать ещё», Excel. Фильтры живут здесь и не сбрасываются. */
export function MovementsLog({ refreshKey }: Props) {
  const [filters, setFilters] = useState<MovementFilters>({})
  const [model, setModel] = useState('') // поиск по названию применяется с задержкой
  const [items, setItems] = useState<StockMovement[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const request = useRef(0)

  const load = useCallback(
    async (append: boolean, offset: number) => {
      const id = ++request.current
      setLoading(true)
      setError(null)
      try {
        const page = await fetchMovements(PAGE, offset, filters)
        if (id !== request.current) return // пришёл устаревший ответ
        setItems((prev) => (append ? [...prev, ...page.items] : page.items))
        setTotal(page.total)
      } catch (e) {
        if (id !== request.current) return
        setError(e instanceof ApiError ? e.message : 'Не удалось загрузить журнал — проверьте соединение')
      } finally {
        if (id === request.current) setLoading(false)
      }
    },
    [filters],
  )

  // Первая страница: при смене фильтров и после операций на складе.
  useEffect(() => {
    void load(false, 0)
  }, [load, refreshKey])

  // Поиск по модели — через 300 мс после последней буквы, чтобы не слать запрос на каждую.
  useEffect(() => {
    const t = window.setTimeout(() => setFilters((f) => (f.model === (model || undefined) ? f : { ...f, model: model || undefined })), 300)
    return () => window.clearTimeout(t)
  }, [model])

  const set = (patch: Partial<MovementFilters>) => setFilters((f) => ({ ...f, ...patch }))
  const filtered = Object.values(filters).some(Boolean) || model !== ''

  async function exportXlsx() {
    if (exporting) return
    setExporting(true)
    setError(null)
    try {
      await downloadMovementsXlsx(filters)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось скачать журнал')
    } finally {
      setExporting(false)
    }
  }

  return (
    <section className="trash-block">
      <div className="field__label">Движения · {total}</div>

      <div className="stockfilters">
        <label className="stockfilters__field">
          <span className="stockfilters__label">Модель</span>
          <input
            className="input"
            type="search"
            placeholder="Например, 15 Pro"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          />
        </label>
        <label className="stockfilters__field">
          <span className="stockfilters__label">Вид</span>
          <select className="input" value={filters.kind ?? ''} onChange={(e) => set({ kind: e.target.value as MovementFilters['kind'] })}>
            <option value="">Все</option>
            <option value="base">{KIND_LABEL.base}</option>
            <option value="plate">{KIND_LABEL.plate}</option>
          </select>
        </label>
        <label className="stockfilters__field">
          <span className="stockfilters__label">Причина</span>
          <select className="input" value={filters.reason ?? ''} onChange={(e) => set({ reason: e.target.value || undefined })}>
            <option value="">Все</option>
            {REASONS.map((r) => (
              <option key={r} value={r}>
                {REASON_LABEL[r]}
              </option>
            ))}
          </select>
        </label>
        <label className="stockfilters__field">
          <span className="stockfilters__label">С даты</span>
          <input className="input" type="date" value={filters.date_from ?? ''} max={filters.date_to || undefined} onChange={(e) => set({ date_from: e.target.value || undefined })} />
        </label>
        <label className="stockfilters__field">
          <span className="stockfilters__label">По дату</span>
          <input className="input" type="date" value={filters.date_to ?? ''} min={filters.date_from || undefined} onChange={(e) => set({ date_to: e.target.value || undefined })} />
        </label>
        {filtered && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => {
              setFilters({})
              setModel('')
            }}
          >
            Сбросить
          </button>
        )}
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => void exportXlsx()} disabled={exporting || total === 0}>
          {exporting ? 'Готовим файл…' : 'Excel'}
        </button>
      </div>

      {error && (
        <div className="form-msg form-msg--err" role="alert">
          {error}
        </div>
      )}

      <div className="tablewrap">
        <table className="table">
          <thead>
            <tr>
              <th>Когда</th>
              <th>Позиция</th>
              <th className="num">Δ</th>
              <th>Причина</th>
              <th>Кто</th>
              <th>Заказ</th>
              <th>Комментарий</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="muted">
                  {filtered ? 'По выбранным фильтрам движений нет' : 'Пока нет движений'}
                </td>
              </tr>
            )}
            {items.map((m) => (
              <tr key={m.id}>
                <td className="muted mono">{fmtDate(m.created_at)}</td>
                <td>
                  {KIND_LABEL[m.kind] ?? m.kind} · {m.model_name}
                  {m.plate_type ? ` · ${PLATE_LABEL[m.plate_type] ?? m.plate_type}` : ''}
                </td>
                <td className={`num mono${m.delta < 0 ? ' stock--empty' : ''}`}>{m.delta > 0 ? `+${m.delta}` : m.delta}</td>
                <td>{REASON_LABEL[m.reason] ?? m.reason}</td>
                <td className="muted">{m.admin_name ?? '—'}</td>
                <td>{m.order_id ? <Link to={`/orders?open=${m.order_id}`}>#{m.order_id}</Link> : '—'}</td>
                <td className="muted">{m.comment || '—'}</td>
              </tr>
            ))}
            {loading && (
              <tr>
                <td colSpan={7} className="muted">
                  Загрузка…
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {items.length < total && !loading && (
        <div style={{ marginTop: 10 }}>
          <button type="button" className="btn btn--ghost btn--sm" onClick={() => void load(true, items.length)}>
            Показать ещё · {Math.min(PAGE, total - items.length)} из {total - items.length}
          </button>
        </div>
      )}
    </section>
  )
}
