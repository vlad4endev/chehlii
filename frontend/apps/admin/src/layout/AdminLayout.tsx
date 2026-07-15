import { NavLink, Outlet } from 'react-router-dom'

import { useAuth } from '../auth'
import { sectionsFor } from '../sections'

const ROLE_LABEL: Record<string, string> = { admin: 'Администратор', designer: 'Дизайнер' }

export function AdminLayout() {
  const { user, logout } = useAuth()
  if (!user) return null
  const sections = sectionsFor(user.role)

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar__brand">
          casetop
          <span className="sidebar__brand-sub">админка</span>
        </div>
        <nav className="nav">
          {sections.map((s) => (
            <NavLink
              key={s.path}
              to={s.path}
              className={({ isActive }) => `nav__link${isActive ? ' nav__link--active' : ''}`}
            >
              {s.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="topbar__user">
            <span className="topbar__name">{user.full_name || user.email}</span>
            <span className="topbar__role">{ROLE_LABEL[user.role] ?? user.role}</span>
          </div>
          <button className="btn btn--ghost" onClick={logout}>
            Выйти
          </button>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
