import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '../auth'
import { Icon } from '../icons'
import { type Section, groupsFor, sectionByPath } from '../sections'
import { type Stats, fetchStats } from '../statsApi'
import { initials } from '../ui'

const ROLE_LABEL: Record<string, string> = { admin: 'Администратор', designer: 'Дизайнер' }

function badgeValue(section: Section, stats: Stats | null): number | null {
  if (!section.badge || !stats) return null
  const v = stats[section.badge]
  return typeof v === 'number' && v > 0 ? v : null
}

export function AdminLayout() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const [stats, setStats] = useState<Stats | null>(null)

  // Метрики для бейджей в меню (только у Админа — эндпоинт admin-only).
  useEffect(() => {
    if (user?.role !== 'admin') return
    let alive = true
    fetchStats()
      .then((s) => alive && setStats(s))
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [user?.role, location.pathname])

  if (!user) return null
  const groups = groupsFor(user.role)
  const current = sectionByPath(location.pathname)
  const displayName = user.full_name || user.email

  return (
    <div className="layout">
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
          <div className="crumbs">
            casetop <Icon name="chevron" size={14} /> <b>{current?.label ?? 'Панель'}</b>
          </div>
          <div className="topbar__right">
            <span className="status-dot">все системы в норме</span>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
