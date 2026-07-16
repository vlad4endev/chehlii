import { useEffect, useState } from 'react'

import { ApiError } from '../api'
import type { Role } from '../api'
import { useAuth } from '../auth'
import {
  type AdminUserRow,
  ROLE_LABEL,
  createUser,
  deleteUser,
  fetchUsers,
  updateUser,
} from '../usersApi'
import { StatLine, UserCell } from '../ui'

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', { dateStyle: 'medium' })
}

export function Users() {
  const { user: me } = useAuth()
  const [items, setItems] = useState<AdminUserRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState<AdminUserRow | null>(null)
  const [creating, setCreating] = useState(false)

  async function reload() {
    setLoading(true)
    setError(null)
    try {
      setItems(await fetchUsers())
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось загрузить пользователей')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    reload()
  }, [])

  async function onDelete(u: AdminUserRow) {
    if (!confirm(`Удалить пользователя ${u.email}?`)) return
    try {
      await deleteUser(u.id)
      reload()
    } catch (e) {
      alert(e instanceof ApiError ? e.message : 'Не удалось удалить')
    }
  }

  return (
    <div>
      <div className="page__head">
        <h1 className="page__title">Пользователи</h1>
        <button className="btn btn--primary" onClick={() => setCreating(true)}>
          Добавить пользователя
        </button>
      </div>
      <p className="page__lead">
        Управление доступом к админке. У Дизайнера — только раздел «Заказы» с ограниченными полями.
      </p>

      {loading && <div className="empty">Загрузка…</div>}
      {error && <div className="empty">{error}</div>}

      {!loading && !error && items.length > 0 && (
        <StatLine
          items={[
            { label: 'Всего', value: items.length },
            { label: 'Администраторов', value: items.filter((u) => u.role === 'admin').length },
            { label: 'Дизайнеров', value: items.filter((u) => u.role === 'designer').length },
            { label: 'Активных', value: items.filter((u) => u.is_active).length },
          ]}
        />
      )}

      {!loading && !error && (
        <div className="tablewrap"><table className="table">
          <thead>
            <tr>
              <th>Пользователь</th>
              <th>Роль</th>
              <th>Статус</th>
              <th>Создан</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.id}>
                <td>
                  <UserCell
                    name={u.full_name || u.email}
                    sub={u.full_name ? u.email : me?.id === u.id ? 'это вы' : undefined}
                  />
                </td>
                <td>
                  <span className="chip">{ROLE_LABEL[u.role]}</span>
                </td>
                <td>
                  {u.is_active ? (
                    <span className="badge badge--green">Активен</span>
                  ) : (
                    <span className="badge badge--red">Отключён</span>
                  )}
                </td>
                <td className="muted">{fmtDate(u.created_at)}</td>
                <td className="row-actions">
                  <button className="linkbtn" onClick={() => setEditing(u)}>
                    Изменить
                  </button>
                  {me?.id !== u.id && (
                    <button className="linkbtn linkbtn--danger" onClick={() => onDelete(u)}>
                      Удалить
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}

      {creating && (
        <CreateUser
          onClose={() => setCreating(false)}
          onSaved={() => {
            setCreating(false)
            reload()
          }}
        />
      )}
      {editing && (
        <EditUser
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            reload()
          }}
        />
      )}
    </div>
  )
}

function RoleSelect({ value, onChange }: { value: Role; onChange: (r: Role) => void }) {
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value as Role)}>
      <option value="designer">Дизайнер</option>
      <option value="admin">Администратор</option>
    </select>
  )
}

function CreateUser({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<Role>('designer')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    if (!email.trim() || password.length < 6) {
      setError('Укажите почту и пароль не короче 6 символов')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await createUser({ email: email.trim(), full_name: fullName.trim() || null, role, password })
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось создать')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title">Новый пользователь</h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal__body">
          <label className="field">
            <span className="field__label">Почта</span>
            <input className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="field">
            <span className="field__label">Имя</span>
            <input
              className="input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field__label">Роль</span>
            <RoleSelect value={role} onChange={setRole} />
          </label>
          <label className="field">
            <span className="field__label">Пароль</span>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="минимум 6 символов"
            />
          </label>
          {error && <div className="login__error">{error}</div>}
        </div>
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={save} disabled={busy}>
            {busy ? 'Создаём…' : 'Создать'}
          </button>
        </div>
      </div>
    </div>
  )
}

function EditUser({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUserRow
  onClose: () => void
  onSaved: () => void
}) {
  const { user: me } = useAuth()
  const isSelf = me?.id === user.id
  const [fullName, setFullName] = useState(user.full_name ?? '')
  const [role, setRole] = useState<Role>(user.role)
  const [active, setActive] = useState(user.is_active)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    if (password && password.length < 6) {
      setError('Пароль не короче 6 символов')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await updateUser(user.id, {
        full_name: fullName.trim() || null,
        role,
        is_active: active,
        password: password || undefined,
      })
      onSaved()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Не удалось сохранить')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal" onClick={onClose}>
      <div className="modal__card" onClick={(e) => e.stopPropagation()}>
        <div className="modal__head">
          <h2 className="modal__title">{user.email}</h2>
          <button className="modal__close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal__body">
          <label className="field">
            <span className="field__label">Имя</span>
            <input
              className="input"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="field__label">Роль</span>
            <RoleSelect value={role} onChange={setRole} />
          </label>
          <label className="field field--check">
            <input
              type="checkbox"
              checked={active}
              onChange={(e) => setActive(e.target.checked)}
              disabled={isSelf}
            />
            <span>Активен{isSelf && ' (нельзя отключить себя)'}</span>
          </label>
          <label className="field">
            <span className="field__label">Новый пароль</span>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="оставьте пустым, чтобы не менять"
            />
          </label>
          {error && <div className="login__error">{error}</div>}
        </div>
        <div className="modal__actions">
          <button className="btn btn--ghost" onClick={onClose}>
            Отмена
          </button>
          <button className="btn btn--primary" onClick={save} disabled={busy}>
            {busy ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </div>
      </div>
    </div>
  )
}
