import { useAuth } from '../auth'
import { sectionsFor } from '../sections'

export function Dashboard() {
  const { user } = useAuth()
  if (!user) return null
  const sections = sectionsFor(user.role)

  return (
    <div>
      <h1 className="page__title">Панель управления</h1>
      <p className="page__lead">
        {user.full_name || user.email}, вам доступно {sections.length}{' '}
        {plural(sections.length, ['раздел', 'раздела', 'разделов'])}.
      </p>
      <div className="cards">
        {sections.map((s) => (
          <a className="scard" href={`#${s.path}`} key={s.path}>
            <span className="scard__title">{s.label}</span>
          </a>
        ))}
      </div>
    </div>
  )
}

function plural(n: number, forms: [string, string, string]): string {
  const a = Math.abs(n) % 100
  const d = a % 10
  if (a > 10 && a < 20) return forms[2]
  if (d > 1 && d < 5) return forms[1]
  if (d === 1) return forms[0]
  return forms[2]
}
