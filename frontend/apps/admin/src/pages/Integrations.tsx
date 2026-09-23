import { useEffect, useMemo, useState } from 'react'

import { ApiError } from '../api'
import { Icon } from '../icons'
import {
  type ConnectionStatus,
  type IntegrationField,
  type IntegrationGroup,
  checkCdek,
  checkOzon,
  checkRobokassa,
  checkYandexDelivery,
  checkYandexDisk,
  checkYandexPay,
  completeYandexDiskOAuth,
  createYandexWarehouse,
  fetchIntegrations,
  saveIntegrations,
} from '../integrationsApi'
import { StatLine } from '../ui'
import {
  YANDEX_DISK_REDIRECT_URI,
  YANDEX_DISK_SCOPES,
  consumeYandexDiskOAuth,
  yandexDiskAuthorizeUrl,
} from '../yandexDiskOAuth'

type CategoryId = 'files' | 'delivery' | 'payments'
type FilterId = 'all' | CategoryId

const CATEGORIES: { id: CategoryId; label: string }[] = [
  { id: 'files', label: 'Файлы' },
  { id: 'delivery', label: 'Доставка' },
  { id: 'payments', label: 'Оплата' },
]

const FILTERS: { id: FilterId; label: string }[] = [
  { id: 'all', label: 'Все' },
  ...CATEGORIES,
]

interface ServiceMeta {
  category: CategoryId
  icon: string
  blurb: string
  docs?: { label: string; href: string }[]
  accessKeys: string[]
  booleanKeys: string[]
  options?: Record<string, { value: string; label: string }[]>
}

const META: Record<string, ServiceMeta> = {
  yandex_disk: {
    category: 'files',
    icon: 'disk',
    blurb: 'Макеты и файлы клиентов',
    docs: [{ label: 'oauth.yandex.ru', href: 'https://oauth.yandex.ru/client/new' }],
    accessKeys: ['yandex_disk.client_id', 'yandex_disk.client_secret', 'yandex_disk.oauth_token'],
    booleanKeys: [],
  },
  cdek: {
    category: 'delivery',
    icon: 'truck',
    blurb: 'ПВЗ, курьер и ярлыки',
    docs: [{ label: 'ЛК СДЭК', href: 'https://lk.cdek.ru' }],
    accessKeys: ['cdek.account', 'cdek.secret', 'cdek.test'],
    booleanKeys: ['cdek.test'],
  },
  yandex_delivery: {
    category: 'delivery',
    icon: 'box',
    blurb: 'ПВЗ и доставка до двери',
    docs: [
      { label: 'Яндекс Доставка', href: 'https://dostavka.yandex.ru' },
      {
        label: 'Создание склада',
        href: 'https://yandex.ru/support/delivery-profile/ru/api/other-day/ref/6.-Upravlenie-skladami-i-otgruzkami/apib2bplatformwarehousescreate-post',
      },
    ],
    accessKeys: ['yandex.oauth_token', 'yandex.test'],
    booleanKeys: ['yandex.test'],
    options: {
      'yandex.last_mile_policy': [
        { value: 'time_interval', label: 'Курьер (интервал)' },
        { value: 'self_pickup', label: 'Самовывоз / ПВЗ' },
      ],
      'yandex.payment_method': [
        { value: 'already_paid', label: 'Уже оплачено' },
        { value: 'card_on_receipt', label: 'Карта при получении' },
        { value: 'postpay', label: 'Постоплата' },
      ],
    },
  },
  ozon: {
    category: 'delivery',
    icon: 'orders',
    blurb: 'ПВЗ Ozon со своего сайта',
    accessKeys: ['ozon.client_id', 'ozon.client_secret'],
    booleanKeys: [],
  },
  payment: {
    category: 'payments',
    icon: 'ruble',
    blurb: 'Robokassa: предоплата и постоплата',
    accessKeys: [
      'payment.robokassa_login',
      'payment.robokassa_pass1',
      'payment.robokassa_pass2',
      'payment.robokassa_test',
    ],
    booleanKeys: ['payment.robokassa_test'],
    options: {
      'payment.provider': [
        { value: 'robokassa', label: 'Robokassa первой' },
        { value: 'yandex_pay', label: 'Яндекс Пэй первым' },
      ],
    },
  },
  yandex_pay: {
    category: 'payments',
    icon: 'card',
    blurb: 'Ссылка на форму Яндекс Пэй',
    docs: [{ label: 'pay.yandex.ru', href: 'https://pay.yandex.ru' }],
    accessKeys: [
      'payment.yandexpay_api_key',
      'payment.yandexpay_merchant_id',
      'payment.yandexpay_test',
    ],
    booleanKeys: ['payment.yandexpay_test'],
  },
}

const GROUP_CHECK: Record<string, () => Promise<ConnectionStatus>> = {
  yandex_disk: checkYandexDisk,
  yandex_pay: checkYandexPay,
  yandex_delivery: checkYandexDelivery,
  cdek: checkCdek,
  ozon: checkOzon,
  payment: checkRobokassa,
}

function metaFor(id: string): ServiceMeta {
  return (
    META[id] ?? {
      category: 'files',
      icon: 'plug',
      blurb: '',
      accessKeys: [],
      booleanKeys: [],
    }
  )
}

function fieldLabel(field: IntegrationField): string {
  if (field.key === 'payment.provider') return 'Какой шлюз показывать первым'
  return field.label.replace(/\s*\(true\/false\)\s*/i, '')
}

function isConnected(group: IntegrationGroup): boolean {
  if (group.id === 'yandex_disk') {
    return group.fields.some((f) => f.key === 'yandex_disk.oauth_token' && f.is_set)
  }
  const secrets = group.fields.filter((f) => f.secret)
  return secrets.length > 0 ? secrets.some((f) => f.is_set) : group.fields.some((f) => f.is_set)
}

function rawValue(field: IntegrationField, edits: Record<string, string>): string {
  if (field.key in edits) return edits[field.key]
  if (field.secret) return ''
  return field.value ?? ''
}

function boolValue(field: IntegrationField, edits: Record<string, string>): boolean {
  const raw = field.key in edits ? edits[field.key] : (field.value ?? '')
  return raw.trim().toLowerCase() === 'true'
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function IntegrationsPanel({ onOpenProxy }: { onOpenProxy?: () => void }) {
  const [groups, setGroups] = useState<IntegrationGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [edits, setEdits] = useState<Record<string, string>>({})
  const [savingId, setSavingId] = useState<string | null>(null)
  const [savedId, setSavedId] = useState<string | null>(null)
  const [diskStatus, setDiskStatus] = useState<ConnectionStatus | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterId>('all')
  const [live, setLive] = useState<Record<string, ConnectionStatus>>({})

  useEffect(() => {
    let cancelled = false
    async function boot() {
      setLoading(true)
      setError(null)
      const pending = consumeYandexDiskOAuth()
      try {
        const next = await fetchIntegrations()
        if (cancelled) return
        setGroups(next)
        if (!pending.error && !pending.token && !pending.code) {
          const desktop = window.matchMedia('(min-width: 901px)').matches
          if (desktop) setSelectedId((cur) => cur ?? next[0]?.id ?? null)
        }
        if (pending.error) {
          setSelectedId('yandex_disk')
          setDiskStatus({ ok: false, detail: pending.error })
          return
        }
        if (!pending.token && !pending.code) return
        setSelectedId('yandex_disk')
        const status = await completeYandexDiskOAuth({
          access_token: pending.token ?? undefined,
          code: pending.code ?? undefined,
        })
        if (cancelled) return
        setDiskStatus(status)
        setLive((p) => ({ ...p, yandex_disk: status }))
        setGroups(await fetchIntegrations())
      } catch (e) {
        if (cancelled) return
        const message = e instanceof ApiError ? e.message : 'Не удалось загрузить настройки'
        if (pending.token || pending.code) {
          setSelectedId('yandex_disk')
          setDiskStatus({ ok: false, detail: message })
        } else {
          setError(message)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void boot()
    return () => {
      cancelled = true
    }
  }, [])

  async function saveGroup(g: IntegrationGroup): Promise<boolean> {
    const values: Record<string, string> = {}
    for (const f of g.fields) {
      if (f.key in edits) values[f.key] = edits[f.key]
    }
    if (Object.keys(values).length === 0) return true
    setSavingId(g.id)
    setSavedId(null)
    try {
      const next = await saveIntegrations(values)
      setGroups(next)
      setEdits((prev) => {
        const copy = { ...prev }
        for (const f of g.fields) delete copy[f.key]
        return copy
      })
      setSavedId(g.id)
      return true
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось сохранить')
      return false
    } finally {
      setSavingId(null)
    }
  }

  const connectedCount = groups.filter(isConnected).length
  const selected = groups.find((g) => g.id === selectedId) ?? null
  const visible = groups.filter((g) => filter === 'all' || metaFor(g.id).category === filter)

  if (loading) return <div className="empty">Загрузка…</div>
  if (error) return <div className="empty">{error}</div>

  return (
    <div>
      <p className="page__lead">
        Ключи и параметры внешних сервисов. Секреты не показываются — если задано, видно
        «задан». Чтобы сменить, введите новое.
      </p>
      <StatLine
        items={[
          { label: 'подключено', value: connectedCount },
          { label: 'без ключей', value: Math.max(0, groups.length - connectedCount) },
          { label: 'сервисов', value: groups.length },
        ]}
      />

      <div className={`int-hub${selected ? ' int-hub--open' : ''}`}>
        <aside className="int-side">
          <div className="int-filters" role="tablist" aria-label="Категории">
            {FILTERS.map((f) => (
              <button
                key={f.id}
                type="button"
                role="tab"
                aria-selected={filter === f.id}
                className={`int-chip${filter === f.id ? ' int-chip--on' : ''}`}
                onClick={() => setFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>

          {CATEGORIES.map((cat) => {
            const items = visible.filter((g) => metaFor(g.id).category === cat.id)
            if (items.length === 0) return null
            return (
              <div className="int-cat" key={cat.id}>
                <div className="int-cat__label">{cat.label}</div>
                <div className="int-cat__list">
                  {items.map((g) => {
                    const meta = metaFor(g.id)
                    const dirty = g.fields.some((f) => f.key in edits)
                    const liveStatus = live[g.id] ?? (g.id === 'yandex_disk' ? diskStatus : null)
                    return (
                      <button
                        key={g.id}
                        type="button"
                        className={`intile${selectedId === g.id ? ' intile--on' : ''}`}
                        onClick={() => setSelectedId(g.id)}
                      >
                        <span className="intile__icon">
                          <Icon name={meta.icon} size={18} />
                        </span>
                        <span className="intile__body">
                          <span className="intile__row">
                            <span className="intile__title">{g.title}</span>
                            {dirty && <span className="badge badge--warn">не сохранено</span>}
                            {!dirty && liveStatus && (
                              <span className={`badge${liveStatus.ok ? ' badge--green' : ' badge--red'}`}>
                                {liveStatus.ok ? 'связь есть' : 'нет связи'}
                              </span>
                            )}
                            {!dirty && !liveStatus && isConnected(g) && (
                              <span className="badge badge--green">подключено</span>
                            )}
                            {!dirty && !liveStatus && !isConnected(g) && (
                              <span className="badge">нет ключей</span>
                            )}
                          </span>
                          <span className="intile__blurb">{meta.blurb}</span>
                        </span>
                        <Icon name="chevron" size={14} />
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })}

          {onOpenProxy && filter === 'all' && (
            <div className="int-cat">
              <div className="int-cat__label">Инфраструктура</div>
              <button type="button" className="intile" onClick={onOpenProxy}>
                <span className="intile__icon">
                  <Icon name="proxy" size={18} />
                </span>
                <span className="intile__body">
                  <span className="intile__row">
                    <span className="intile__title">Прокси Telegram</span>
                    <span className="badge">настроить</span>
                  </span>
                  <span className="intile__blurb">Ключи VLESS / Hysteria2 / SOCKS для бота</span>
                </span>
                <Icon name="chevron" size={14} />
              </button>
            </div>
          )}
        </aside>

        <section className="int-detail" aria-live="polite">
          {selected ? (
            <ServiceEditor
              group={selected}
              edits={edits}
              onEdit={(k, v) => {
                setEdits((p) => ({ ...p, [k]: v }))
                setLive((p) => {
                  if (!selectedId || !(selectedId in p)) return p
                  const next = { ...p }
                  delete next[selectedId]
                  return next
                })
                if (selectedId === 'yandex_disk') setDiskStatus(null)
              }}
              onSave={() => saveGroup(selected)}
              onGroups={(next) => setGroups(next)}
              saving={savingId === selected.id}
              saved={savedId === selected.id}
              initialStatus={
                selected.id === 'yandex_disk' ? (live.yandex_disk ?? diskStatus) : (live[selected.id] ?? null)
              }
              onLive={(status) => setLive((p) => ({ ...p, [selected.id]: status }))}
              onBack={() => setSelectedId(null)}
            />
          ) : (
            <div className="int-empty">
              <div className="intile__icon">
                <Icon name="plug" size={22} />
              </div>
              <div className="int-empty__title">Выберите сервис</div>
              <p>Слева — список. Справа появятся ключи, параметры и проверка связи.</p>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}

function ServiceEditor({
  group,
  edits,
  onEdit,
  onSave,
  onGroups,
  saving,
  saved,
  initialStatus,
  onLive,
  onBack,
}: {
  group: IntegrationGroup
  edits: Record<string, string>
  onEdit: (key: string, value: string) => void
  onSave: () => Promise<boolean>
  onGroups: (next: IntegrationGroup[]) => void
  saving: boolean
  saved: boolean
  initialStatus?: ConnectionStatus | null
  onLive: (status: ConnectionStatus) => void
  onBack: () => void
}) {
  const meta = metaFor(group.id)
  const check = GROUP_CHECK[group.id]
  const [checking, setChecking] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [creatingWh, setCreatingWh] = useState(false)
  const [status, setStatus] = useState<ConnectionStatus | null>(initialStatus ?? null)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    setStatus(initialStatus ?? null)
  }, [initialStatus, group.id])

  const dirty = useMemo(
    () => group.fields.some((f) => f.key in edits),
    [group.fields, edits],
  )
  const connected = isConnected(group)
  const access = group.fields.filter((f) => meta.accessKeys.includes(f.key))
  const extra = group.fields.filter((f) => !meta.accessKeys.includes(f.key))
  const warehouseFieldKeys = [
    'yandex.platform_station_id',
    'yandex.sender_name',
    'yandex.sender_phone',
    'yandex.sender_email',
  ]
  const warehouseFields = extra.filter((f) => warehouseFieldKeys.includes(f.key))
  const accessFields = access.length > 0 ? access : group.fields
  const extraFields =
    access.length > 0
      ? extra.filter((f) => group.id !== 'yandex_delivery' || !warehouseFieldKeys.includes(f.key))
      : []

  async function runCheck() {
    if (!check) return
    setChecking(true)
    try {
      const next = await check()
      setStatus(next)
      onLive(next)
    } catch (e) {
      const next = { ok: false, detail: e instanceof ApiError ? e.message : 'Проверка не удалась' }
      setStatus(next)
      onLive(next)
    } finally {
      setChecking(false)
    }
  }

  async function createTomilinoWarehouse() {
    const phoneField = group.fields.find((f) => f.key === 'yandex.sender_phone')
    const nameField = group.fields.find((f) => f.key === 'yandex.sender_name')
    const emailField = group.fields.find((f) => f.key === 'yandex.sender_email')
    const phone = (phoneField ? rawValue(phoneField, edits) : '').trim()
    setCreatingWh(true)
    try {
      if (group.fields.some((f) => f.key in edits)) {
        const savedOk = await onSave()
        if (!savedOk) {
          setCreatingWh(false)
          return
        }
      }
      const created = await createYandexWarehouse({
        phone: phone || undefined,
        contact_name: nameField ? rawValue(nameField, edits).trim() || undefined : undefined,
        email: emailField ? rawValue(emailField, edits).trim() || undefined : undefined,
      })
      const nextGroups = await fetchIntegrations()
      onGroups(nextGroups)
      const next = { ok: true, detail: created.detail }
      setStatus(next)
      onLive(next)
    } catch (e) {
      const next = {
        ok: false,
        detail: e instanceof ApiError ? e.message : 'Не удалось создать склад',
      }
      setStatus(next)
      onLive(next)
    } finally {
      setCreatingWh(false)
    }
  }

  async function connectYandexDisk() {
    const typedId = edits['yandex_disk.client_id']
    const stored = group.fields.find((f) => f.key === 'yandex_disk.client_id')?.value
    const clientId = (typedId ?? stored ?? '').trim()
    if (!clientId) {
      const next = {
        ok: false,
        detail: 'Введите Client ID с oauth.yandex.ru — без него Яндекс не выдаст токен.',
      }
      setStatus(next)
      onLive(next)
      return
    }
    setConnecting(true)
    setStatus(null)
    try {
      if (group.fields.some((f) => f.key in edits)) {
        const savedOk = await onSave()
        if (!savedOk) {
          setConnecting(false)
          return
        }
      }
      window.location.assign(yandexDiskAuthorizeUrl(clientId))
    } catch (e) {
      const next = {
        ok: false,
        detail: e instanceof ApiError ? e.message : 'Не удалось открыть Яндекс OAuth',
      }
      setStatus(next)
      onLive(next)
      setConnecting(false)
    }
  }

  async function onCopy(label: string, text: string) {
    const ok = await copyText(text)
    if (ok) {
      setCopied(label)
      window.setTimeout(() => setCopied((cur) => (cur === label ? null : cur)), 1600)
    }
  }

  return (
    <div className="card int-editor">
      <div className="int-editor__head">
        <button type="button" className="int-back" onClick={onBack}>
          <Icon name="chevron" size={14} />
          К списку
        </button>
        <div className="intcard__head">
          <div className="intcard__icon">
            <Icon name={meta.icon} size={20} />
          </div>
          <div className="int-editor__titles">
            <div className="intcard__title">{group.title}</div>
            <div className="card__hint">{meta.blurb}</div>
          </div>
          {connected ? (
            <span className="badge badge--green">подключено</span>
          ) : (
            <span className="badge">нет ключей</span>
          )}
        </div>
      </div>

      <details className="int-help">
        <summary>Как подключить</summary>
        <p>{group.hint}</p>
        {group.id === 'yandex_disk' && (
          <div className="int-help__box">
            <CopyRow
              label="Redirect URI"
              value={YANDEX_DISK_REDIRECT_URI}
              copied={copied === 'uri'}
              onCopy={() => void onCopy('uri', YANDEX_DISK_REDIRECT_URI)}
            />
            <div className="int-help__scopes">
              <span className="field__label">Доступ к данным</span>
              <div className="int-help__chips">
                {YANDEX_DISK_SCOPES.map((scope) => (
                  <code className="chip chip--code" key={scope}>
                    {scope}
                  </code>
                ))}
              </div>
            </div>
          </div>
        )}
        {meta.docs && meta.docs.length > 0 && (
          <div className="int-help__links">
            {meta.docs.map((d) => (
              <a key={d.href} className="int-help__link" href={d.href} target="_blank" rel="noreferrer">
                {d.label}
                <Icon name="external" size={13} />
              </a>
            ))}
          </div>
        )}
      </details>

      <div className="int-sec">
        <div className="int-sec__title">Доступ</div>
        <div className="intcard__fields">
          {accessFields.map((f) => (
            <FieldControl
              key={f.key}
              field={f}
              edits={edits}
              onEdit={onEdit}
              booleanKeys={meta.booleanKeys}
              options={meta.options}
            />
          ))}
        </div>
        {group.id === 'yandex_disk' && (
          <button
            className="btn btn--ghost btn--sm int-oauth"
            onClick={() => void connectYandexDisk()}
            disabled={connecting || saving}
          >
            {connecting ? 'Открываем Яндекс…' : 'Получить токен у Яндекса'}
          </button>
        )}
      </div>

      {group.id === 'yandex_delivery' && (
        <div className="int-sec">
          <div className="int-sec__title">Склад отправителя</div>
          <p className="int-wh__lead">
            Гаршина 3, Томилино (БЦ «Звёздный»). Яндекс создаст точку отгрузки и запишет её ID
            в настройки — с неё будут забирать заказы.
          </p>
          <div className="intcard__fields">
            {warehouseFields.map((f) => (
              <FieldControl
                key={f.key}
                field={f}
                edits={edits}
                onEdit={onEdit}
                booleanKeys={meta.booleanKeys}
                options={meta.options}
              />
            ))}
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => void createTomilinoWarehouse()}
            disabled={creatingWh || saving}
          >
            {creatingWh ? 'Создаём склад…' : 'Создать склад в Яндекс Доставке'}
          </button>
        </div>
      )}

      {extraFields.length > 0 && (
        <details className="int-sec int-sec--fold">
          <summary>
            Параметры
            <span className="muted"> · {extraFields.length}</span>
          </summary>
          <div className="intcard__fields">
            {extraFields.map((f) => (
              <FieldControl
                key={f.key}
                field={f}
                edits={edits}
                onEdit={onEdit}
                booleanKeys={meta.booleanKeys}
                options={meta.options}
              />
            ))}
          </div>
        </details>
      )}

      {status && (
        <div className={`intcard__status${status.ok ? ' intcard__status--ok' : ' intcard__status--bad'}`}>
          <b>{status.ok ? 'Связь есть' : 'Нет связи'}</b> · {status.detail}
        </div>
      )}

      <div className="intcard__foot">
        {saved && !dirty && <span className="badge badge--green">Сохранено</span>}
        {dirty && <span className="badge badge--warn">есть изменения</span>}
        {check && (
          <button className="btn btn--sm" onClick={() => void runCheck()} disabled={checking}>
            {checking ? 'Проверяем…' : 'Проверить связь'}
          </button>
        )}
        <button
          className="btn btn--primary btn--sm"
          onClick={() => void onSave()}
          disabled={saving || !dirty}
        >
          {saving ? 'Сохраняем…' : 'Сохранить'}
        </button>
      </div>
    </div>
  )
}

function FieldControl({
  field,
  edits,
  onEdit,
  booleanKeys,
  options,
}: {
  field: IntegrationField
  edits: Record<string, string>
  onEdit: (key: string, value: string) => void
  booleanKeys: string[]
  options?: Record<string, { value: string; label: string }[]>
}) {
  const [reveal, setReveal] = useState(false)
  const selectOpts = options?.[field.key]

  if (booleanKeys.includes(field.key)) {
    const on = boolValue(field, edits)
    return (
      <button
        type="button"
        role="switch"
        aria-checked={on}
        className="int-toggle"
        onClick={() => onEdit(field.key, on ? 'false' : 'true')}
      >
        <span className={`toggle${on ? ' toggle--on' : ''}`} />
        <span>
          <span className="int-toggle__label">{fieldLabel(field)}</span>
          {field.placeholder && <span className="int-toggle__hint">{field.placeholder}</span>}
        </span>
      </button>
    )
  }

  if (selectOpts) {
    const current = rawValue(field, edits)
    const known = selectOpts.some((o) => o.value === current)
    return (
      <label className="field">
        <span className="field__label">{fieldLabel(field)}</span>
        <select
          className="input"
          value={current}
          onChange={(e) => onEdit(field.key, e.target.value)}
        >
          {!current && <option value="">Не задано</option>}
          {!known && current && <option value={current}>{current}</option>}
          {selectOpts.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    )
  }

  return (
    <label className="field">
      <span className="field__label">
        {fieldLabel(field)}
        {field.secret && field.is_set && <span className="muted"> · задан</span>}
      </span>
      <span className={field.secret ? 'int-secret' : undefined}>
        <input
          className="input"
          type={field.secret && !reveal ? 'password' : 'text'}
          placeholder={
            field.key === 'yandex_disk.oauth_token'
              ? 'y0_AgAA… или весь URL со страницы Яндекса'
              : field.secret && field.is_set
                ? '•••••• (оставьте пустым, чтобы не менять)'
                : field.placeholder || ''
          }
          value={rawValue(field, edits)}
          onChange={(e) => onEdit(field.key, e.target.value)}
          autoComplete="off"
          spellCheck={false}
        />
        {field.secret && (
          <button
            type="button"
            className="int-secret__eye"
            aria-label={reveal ? 'Скрыть' : 'Показать'}
            onClick={() => setReveal((v) => !v)}
          >
            <Icon name={reveal ? 'eyeOff' : 'eye'} size={16} />
          </button>
        )}
      </span>
    </label>
  )
}

function CopyRow({
  label,
  value,
  copied,
  onCopy,
}: {
  label: string
  value: string
  copied: boolean
  onCopy: () => void
}) {
  return (
    <div className="int-copyrow">
      <span className="field__label">{label}</span>
      <code>{value}</code>
      <button type="button" className="btn btn--ghost btn--sm" onClick={onCopy}>
        <Icon name="copy" size={14} />
        {copied ? 'Скопировано' : 'Копировать'}
      </button>
    </div>
  )
}
