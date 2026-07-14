// Заглушка для разделов, которые ещё разрабатываются (Фазы B–H).
export function Placeholder({ title }: { title: string }) {
  return (
    <div>
      <h1 className="page__title">{title}</h1>
      <div className="empty">Раздел в разработке.</div>
    </div>
  )
}
