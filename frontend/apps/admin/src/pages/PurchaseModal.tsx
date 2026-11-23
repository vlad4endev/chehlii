import { useEffect, useMemo, useRef, useState } from 'react'

import { ApiError } from '../api'
import { useModalA11y } from '../useModalA11y'
import {
  type PurchaseSuggestion,
  KIND_LABEL,
  PLATE_LABEL,
  downloadPurchaseXlsx,
  fetchPurchaseSuggestion,
} from '../warehouseApi'

interface Props {
  onClose: () => void
}

/** Что докупить: расчёт открывается сразу в окне, а не где-то под таблицей. */
export function PurchaseModal({ onClose }: Props) {
  const [data, setData] = useState<PurchaseSuggestion | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [exporting, setExporting] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const cardRef = useRef<HTMLDivElement>(null)
  useModalA11y(cardRef, onClose)

  useEffect(() => {
    let alive = true
    setData(null)
    setError(null)
    fetchPurchaseSuggestion()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e instanceof ApiError ? e.message : 'Не удалось рассчитать закупку — проверьте соединение'))
    return () => {
      alive = false
    }
  }, [attempt])

  const items = useMemo(() => (data?.items ?? []).filter((r) => r.recommend > 0), [data])
  const total = items.reduce((sum, r) => sum + r.recommend, 0)

  async function exportXlsx() {
    if (exporting) return
    setExporting(true)
    setError(null)
    try {
      await downloadPurchaseXlsx()
    } catch (e) {
      setError(e instanceof Error ? `Не удалось скачать файл: ${e.message}` : 'Не удалось скачать файл')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div
        ref={cardRef}
        tabIndex={-1}
        className="modal__card modal__card--wide"
        role="dialog"
        aria-modal="true"
        aria-labelledby="purchase-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal__head">
          <h2 id="purchase-title" className="modal__title">
            Что докупить
          </h2>
          <button type="button" className="modal__close" onClick={onClose} aria-label="Закрыть">
            ✕
          </button>
        </div>
        <div className="modal__body">
          {!data && !error && <div className="empty">Считаем расход…</div>}

          {data && (
            <>
              <p className="field__hint" style={{ margin: 0 }}>
                Смотрим расход за последние {data.settings.lookback_days} дн. и берём запас на срок поставки (
                {data.settings.lead_days} дн.) плюс страховку ({data.settings.safety_days} дн.). Сроки меняются в
                Настройки → Склад / закупка.
              </p>

              {items.length === 0 ? (
                <div className="empty">Закупка не нужна: остатков хватает на ближайшие недели.</div>
              ) : (
                <>
                  <div className="purchasetotal">
                    Позиций к закупке: <b>{items.length}</b> · всего <b className="mono">{total}</b> шт.
                  </div>
                  <div className="tablewrap invwrap">
                    <table className="table">
                      <thead>
                        <tr>
                          <th>Позиция</th>
                          <th className="num">Остаток</th>
                          <th className="num">Расход за {data.settings.lookback_days} дн.</th>
                          <th className="num">Купить</th>
                        </tr>
                      </thead>
                      <tbody>
                        {items.map((r) => (
                          <tr key={r.component_id}>
                            <td>
                              <span className="strong">{r.model_name}</span>
                              <span className="groupnote">
                                {KIND_LABEL[r.kind] ?? r.kind}
                                {r.plate_type ? ` · ${(PLATE_LABEL[r.plate_type] ?? r.plate_type).toLowerCase()}` : ''}
                              </span>
                            </td>
                            <td className={`num mono${r.stock === 0 ? ' stock--empty' : ''}`}>{r.stock}</td>
                            <td className="num mono">{r.spent_lookback}</td>
                            <td className="num mono strong">{r.recommend}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </>
          )}

          {error && (
            <div className="form-msg form-msg--err" role="alert">
              {error}{' '}
              {!data && (
                <button type="button" className="btn btn--ghost btn--sm" onClick={() => setAttempt((a) => a + 1)}>
                  Повторить
                </button>
              )}
            </div>
          )}
        </div>
        <div className="modal__actions">
          <button type="button" className="btn btn--ghost" onClick={onClose}>
            Закрыть
          </button>
          <button type="button" className="btn btn--primary" disabled={!data || exporting} onClick={() => void exportXlsx()}>
            {exporting ? 'Готовим файл…' : 'Скачать в Excel'}
          </button>
        </div>
      </div>
    </div>
  )
}
