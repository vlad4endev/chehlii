import { useEffect, useState } from 'react'

import { ApiError } from '../api'
import { Icon } from '../icons'
import {
  checkTgProxy,
  fetchTgProxy,
  patchTgProxy,
  type ProxyCheck,
  type ProxyKey,
  type TgProxyState,
} from '../tgProxyApi'

function kindLabel(key: ProxyKey): string {
  if (key.kind === 'vless') {
    const bits = ['VLESS']
    if (key.security && key.security !== 'none') bits.push(key.security)
    if (key.network && key.network !== 'tcp') bits.push(key.network)
    return bits.join(' · ')
  }
  if (key.kind === 'socks') return 'SOCKS5'
  if (key.kind === 'http') return 'HTTP'
  return key.kind
}

function ago(iso: string | null): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return iso
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000))
  if (sec < 60) return 'только что'
  if (sec < 3600) return `${Math.floor(sec / 60)} мин назад`
  if (sec < 86400) return `${Math.floor(sec / 3600)} ч назад`
  return iso.replace('T', ' ').replace('+00:00', ' UTC')
}

export function ProxyPanel() {
  const [state, setState] = useState<TgProxyState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [adding, setAdding] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [checking, setChecking] = useState(false)
  const [check, setCheck] = useState<ProxyCheck | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  async function reload() {
    const next = await fetchTgProxy()
    setState(next)
    return next
  }

  useEffect(() => {
    let cancelled = false
    fetchTgProxy()
      .then((s) => {
        if (!cancelled) setState(s)
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof ApiError ? e.message : 'Не удалось загрузить')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setError(null)
    try {
      return await fn()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить')
      return undefined
    }
  }

  async function onToggle(enabled: boolean) {
    setToggling(true)
    const next = await run(() => patchTgProxy({ enabled }))
    if (next) setState(next)
    setToggling(false)
  }

  async function onAdd() {
    if (!draft.trim()) return
    setAdding(true)
    setCheck(null)
    const next = await run(() => patchTgProxy({ add: draft }))
    if (next) {
      setState(next)
      setDraft('')
    }
    setAdding(false)
  }

  async function onRemove(key: ProxyKey) {
    if (!window.confirm(`Удалить ключ «${key.label}»? Ссылку придётся вставить заново.`)) return
    setBusyId(key.id)
    const next = await run(() => patchTgProxy({ remove_ids: [key.id] }))
    if (next) setState(next)
    setBusyId(null)
  }

  async function onKeyEnabled(key: ProxyKey, enabled: boolean) {
    setBusyId(key.id)
    const next = await run(() => patchTgProxy({ set_enabled: { [key.id]: enabled } }))
    if (next) setState(next)
    setBusyId(null)
  }

  async function onCheck() {
    setChecking(true)
    setCheck(null)
    const result = await run(() => checkTgProxy())
    if (result) {
      setCheck(result)
      void reload()
    }
    setChecking(false)
  }

  if (loading) return <div className="empty">Загрузка…</div>

  const keys = state?.keys ?? []
  const bot = state?.bot
  const enabled = Boolean(state?.enabled)
  const active = keys.filter((k) => k.enabled)

  return (
    <div>
      <p className="page__lead">
        Telegram-бот ходит в api.telegram.org через прокси. Вставьте ключ{' '}
        <code>vless://</code> (Reality, WS, gRPC) — на сервере поднимется локальный SOCKS
        через xray. Подойдут и <code>socks5://</code> / <code>http://</code>. Несколько
        ключей: бот берёт первый рабочий. Ссылки больше не показываются.
      </p>

      <div className="card intcard">
        <div className="intcard__head">
          <div className="intcard__icon">
            <Icon name="proxy" size={20} />
          </div>
          <div>
            <div className="intcard__title">Прокси для Telegram</div>
            <div className="card__hint">Только канал Telegram. MAX ходит напрямую.</div>
          </div>
          {enabled && active.length > 0 && <span className="badge badge--green">включён</span>}
        </div>

        <label className="switch">
          <input
            type="checkbox"
            checked={enabled}
            disabled={toggling || !state}
            onChange={(e) => void onToggle(e.target.checked)}
          />
          <span>Включить прокси для Telegram-бота</span>
        </label>

        {enabled && keys.length === 0 && (
          <div className="intcard__status intcard__status--bad">
            Прокси включён, но ключей нет — бот не пойдёт в Telegram напрямую и будет
            ждать ссылку.
          </div>
        )}

        {bot && (bot.ok !== null || bot.detail) && (
          <div className={`intcard__status${bot.ok ? '' : ' intcard__status--bad'}`}>
            <b>{bot.ok ? 'Бот в Telegram' : 'Бот не достучался'}</b>
            {bot.detail ? ` · ${bot.detail}` : ''}
            {bot.via ? ` · через ${bot.via}` : ''}
            {bot.updated_at ? ` · ${ago(bot.updated_at)}` : ''}
          </div>
        )}
        {enabled && !bot?.detail && (
          <div className="intcard__status">
            Статус Telegram появится после запуска бота (подхватит ключ за ~20 с, без
            перезапуска контейнера).
          </div>
        )}

        <div className="field">
          <span className="field__label">Новые ключи — по одному на строку или пачкой</span>
          <textarea
            className="input textarea proxy-draft"
            rows={4}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="vless://uuid@host:443?type=tcp&security=reality&pbk=…&fp=chrome&sni=…#NL"
            spellCheck={false}
            autoComplete="off"
          />
        </div>

        {error && <div className="login__error">{error}</div>}

        {check && (
          <div className={`intcard__status${check.ok ? '' : ' intcard__status--bad'}`}>
            <b>{check.ok ? 'Сервер отвечает' : 'Нет связи с прокси'}</b> · {check.detail}
            {check.keys.length > 0 && (
              <ul className="proxy-check">
                {check.keys.map((k) => (
                  <li key={k.id}>
                    {k.ok ? '✓' : '✗'} {k.label}: {k.detail}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="intcard__foot">
          <button className="btn btn--sm" onClick={() => void onCheck()} disabled={checking || keys.length === 0}>
            {checking ? 'Проверяем…' : 'Проверить сервер'}
          </button>
          <button
            className="btn btn--primary btn--sm"
            onClick={() => void onAdd()}
            disabled={adding || !draft.trim()}
          >
            {adding ? 'Добавляем…' : 'Добавить ключ'}
          </button>
        </div>
      </div>

      {keys.length > 0 && (
        <div className="proxy-keys">
          {keys.map((key) => (
            <div className="card proxy-key" key={key.id}>
              <div className="proxy-key__main">
                <div className="proxy-key__title">{key.label}</div>
                <div className="proxy-key__meta">
                  {kindLabel(key)} · {key.host}:{key.port}
                  {!key.enabled && ' · выключен'}
                </div>
              </div>
              <label className="switch switch--sm">
                <input
                  type="checkbox"
                  checked={key.enabled}
                  disabled={busyId === key.id}
                  onChange={(e) => void onKeyEnabled(key, e.target.checked)}
                />
                <span>в работе</span>
              </label>
              <button
                className="btn btn--ghost btn--sm"
                onClick={() => void onRemove(key)}
                disabled={busyId === key.id}
              >
                Удалить
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
