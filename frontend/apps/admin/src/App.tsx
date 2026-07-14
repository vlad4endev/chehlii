import { Navigate, Outlet, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth'
import { AdminLayout } from './layout/AdminLayout'
import { Dashboard } from './pages/Dashboard'
import { Login } from './pages/Login'
import { Placeholder } from './pages/Placeholder'
import { SECTIONS } from './sections'

function Protected() {
  const { user, loading } = useAuth()
  if (loading) return <div className="boot">Загрузка…</div>
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}

// Роль ограничивает доступ и на сервере, и здесь — редирект, если раздел не для этой роли.
function RoleGuard({ roles, children }: { roles: string[]; children: React.ReactNode }) {
  const { user } = useAuth()
  if (user && !roles.includes(user.role)) return <Navigate to="/" replace />
  return <>{children}</>
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Protected />}>
        <Route element={<AdminLayout />}>
          <Route index element={<Dashboard />} />
          {SECTIONS.map((s) => (
            <Route
              key={s.path}
              path={s.path.slice(1)}
              element={
                <RoleGuard roles={s.roles}>
                  <Placeholder title={s.label} />
                </RoleGuard>
              }
            />
          ))}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>
    </Routes>
  )
}
