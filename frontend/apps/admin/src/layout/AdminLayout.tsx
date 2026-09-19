import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import {
  type NotifyEvent,
  browserPermission,
  diffStats,
  ensureBrowserPermission,
  loadBaseline,
  permissionLabel,
  pushBrowser,
  saveBaseline,
  snapshotBaseline,
  syncTitle,
} from '../adminNotify'
import { useAuth } from '../auth'
import { Icon } from '../icons'
import { type Section, groupsFor, sectionByPath } from '../sections'
import { type Stats, fetchStats } from '../statsApi'
import { initials } from '../ui'

const ROLE_LABEL: Record<string, string> = { admin: 'Администратор', designer: 'Дизайнер' }
const TOAST_MS = 6000

function badgeValue(section: Section, stats: Stats | null): number | null {
  if (!section.badge || !stats) return null
  const v = stats[section.badge]
  return typeof v === 'number' && v > 0 ? v : null
}

export function AdminLayout() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [stats, setStats] = useState<Stats | null>(null)
  const [navOpen, setNavOpen] = useState(false)
  const [toasts, setToasts] = useState<NotifyEvent[]>([])
  const [notifPerm, setNotifPerm] = useState(() => browserPermission())
  const timers = useRef<Map<string, number>>(new Map())

  function dismissToast(id: string) {
    const t = timers.current.get(id)
    if (t) {
      window.clearTimeout(t)
      timers.current.delete(id)
    }
    setToasts((prev) => prev.filter((x) => x.id !== id))
  }

  function enqueueToasts(events: NotifyEvent[]) {
    if (events.length === 0) return
    setToasts((prev) => [...prev, ...events].slice(-5))
    for (const ev of events) {
      pushBrowser(ev)
      const tid = window.setTimeout(() => dismissToast(ev.id), TOAST_MS)
      timers.current.set(ev.id, tid)
    }
  }

  useEffect(() => {
    return () => {
      for (const t of timers.current.values()) window.clearTimeout(t)
      timers.current.clear()
    }
  }, [])

  // Метрики для бейджей и уведомлений (admin + designer).
  useEffect(() => {
    if (!user || (user.role !== 'admin' && user.role !== 'designer')) return
    let alive = true
    const includeConsult = user.role === 'admin'
    const load = () =>
      fetchStats()
        .then((s) => {
          if (!alive) return
          setStats(s)
          const prev = loadBaseline()
          const next = snapshotBaseline(s)
          if (prev) {
            enqueueToasts(diffStats(prev, s, { includeConsult }))
          }
          saveBaseline(next)
          syncTitle(s, includeConsult)
        })
        .catch(() => {})
    load()
    const t = window.setInterval(load, 15000)
    return () => {
      alive = false
      window.clearInterval(t)
    }
  }, [user?.role, location.pathname])

  useEffect(() => {
    setNavOpen(false)
  }, [location.pathname])

  useEffect(() => {
    return () => {
      syncTitle(null, false)
    }
  }, [])

  async function onEnableNotifications() {
    const p = await ensureBrowserPermission()
    setNotifPerm(p)
  }

  if (!user) return null
  const groups = groupsFor(user.role)
  const current = sectionByPath(location.pathname)
  const displayName = user.full_name || user.email
  const showNotifBtn = notifPerm !== 'unsupported'

  return (
    <div className={`layout${navOpen ? ' layout--nav-open' : ''}`}>
      <div className="scrim" onClick={() => setNavOpen(false)} aria-hidden="true" />
      <aside className="sidebar">
        <div className="sidebar__brand">
          casetop <span className="sidebar__badge">admin</span>
        </div>

        <nav className="nav">
          {groups.map((g, i) => (
            <div className="nav__group" key={g.label ?? `g${i}`}>
              {g.label && <div className="nav__group-label">{g.label}</div>}
              {g.items.map((s) => {
                const badge = badgeValue(s, stats)
                return (
                  <NavLink
                    key={s.path}
                    to={s.path}
                    end={s.path === '/'}
                    className={({ isActive }) => `nav__link${isActive ? ' nav__link--active' : ''}`}
                  >
                    <Icon name={s.icon} size={18} />
                    <span>{s.label}</span>
                    {badge !== null && <span className="nav__badge">{badge}</span>}
                  </NavLink>
                )
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar__foot">
          <div className="userchip">
            <div className="userchip__avatar">{initials(displayName)}</div>
            <div className="userchip__meta">
              <div className="userchip__name">{displayName}</div>
              <div className="userchip__role">{ROLE_LABEL[user.role] ?? user.role}</div>
            </div>
          </div>
          <button className="sidebar__logout" onClick={logout}>
            <Icon name="logout" size={18} />
            Выйти
          </button>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button
            className="hamburger"
            onClick={() => setNavOpen((v) => !v)}
            aria-label="Меню"
            aria-expanded={navOpen}
          >
            <Icon name="menu" size={20} />
          </button>
          <div className="crumbs">
            casetop <Icon name="chevron" size={14} /> <b>{current?.label ?? 'Панель'}</b>
          </div>
          <div className="topbar__right">
            {showNotifBtn && (
              <button
                type="button"
                className={`topbar__notif${notifPerm === 'granted' ? ' topbar__notif--on' : ''}`}
                onClick={onEnableNotifications}
                disabled={notifPerm === 'granted' || notifPerm === 'denied'}
                title={
                  notifPerm === 'granted'
                    ? 'Системные уведомления включены'
                    : notifPerm === 'denied'
                      ? 'Разрешите уведомления в настройках браузера'
                      : 'Включить системные уведомления (когда вкладка в фоне)'
                }
              >
                <Icon name="bell" size={16} />
                <span>{permissionLabel(notifPerm)}</span>
              </button>
            )}
            <span className="status-dot">все системы в норме</span>
          </div>
        </header>
        <main className={`content${current?.path === '/consult' ? ' content--fill' : ''}`}>
          <Outlet />
        </main>
      </div>

      {toasts.length > 0 && (
        <div className="toast-stack" aria-live="polite">
          {toasts.map((t) => (
            <div
              key={t.id}
              className={`toast toast--${t.kind}`}
              role="button"
              tabIndex={0}
              onClick={() => {
                dismissToast(t.id)
                navigate(t.href)
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  dismissToast(t.id)
                  navigate(t.href)
                }
              }}
            >
              <span className="toast__icon" aria-hidden>
                <Icon name={t.kind === 'consult' ? 'chat' : 'orders'} size={18} />
              </span>
              <span className="toast__body">
                <span className="toast__title">{t.title}</span>
                <span className="toast__text">{t.body}</span>
              </span>
              <button
                type="button"
                className="toast__close"
                aria-label="Закрыть"
                onClick={(e) => {
                  e.stopPropagation()
                  dismissToast(t.id)
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
