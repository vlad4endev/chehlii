// Тонкая обёртка над MAX WebApp Bridge (window.WebApp, скрипт max-web-app.js).
// В MAX нет аналога Telegram.WebApp.sendData — выбор передаётся боту через backend
// (мини-приложение создаёт заказ) + deep-link в бот с payload order_<id>.

interface MaxUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
}
interface MaxBackButton {
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick?(cb: () => void): void
}
interface MaxWebApp {
  initData?: string
  initDataUnsafe?: { user?: MaxUser; start_param?: string }
  platform?: string
  ready?(): void
  expand?(): void
  openLink?(url: string): void
  openMaxLink?(url: string): void
  BackButton?: MaxBackButton
}

// Публичное имя MAX-бота (для deep-link в чат бота). Совпадает с MAX_BOT_USERNAME
// серверного compose. Переопределяется через VITE_MAX_BOT_USERNAME при сборке.
const MAX_BOT_USERNAME = import.meta.env.VITE_MAX_BOT_USERNAME ?? 'id682401246838_bot'

function maxApp(): MaxWebApp | undefined {
  return (window as unknown as { WebApp?: MaxWebApp }).WebApp
}

// «Настоящий» MAX определяем по наличию launch-данных пользователя: в обычном
// браузере скрипт может создать window.WebApp, но initDataUnsafe.user там нет.
function realMax(): MaxWebApp | undefined {
  const w = maxApp()
  return w && w.initDataUnsafe?.user?.id ? w : undefined
}

export const isMax = (): boolean => !!realMax()

export interface MaxClient {
  id: number
  firstName?: string
  username?: string
}

export function getMaxUser(): MaxClient | null {
  const u = realMax()?.initDataUnsafe?.user
  if (!u) return null
  return { id: u.id, firstName: u.first_name, username: u.username }
}

export function initMax(): void {
  const w = realMax()
  if (!w) return
  w.ready?.()
  w.expand?.()
}

// Открыть чат бота со стартовым payload order_<id> — бот подхватит заказ по id
// (GET /orders/{id}) и покажет подтверждение.
export function openBotWithOrder(orderId: number): void {
  const w = realMax()
  const url = `https://max.ru/${MAX_BOT_USERNAME}?start=order_${orderId}`
  if (w?.openMaxLink) w.openMaxLink(url)
  else if (w?.openLink) w.openLink(url)
  else window.open(url, '_blank')
}

export function maxBackButton(): MaxBackButton | undefined {
  return realMax()?.BackButton
}
