// Тонкая обёртка над Telegram WebApp SDK. В обычном браузере (лендинг/превью)
// window.Telegram отсутствует — методы деградируют мягко.

interface TgMainButton {
  setText(text: string): void
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick(cb: () => void): void
}
interface TgBackButton {
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick(cb: () => void): void
}
interface TgUser {
  id: number
  first_name?: string
  last_name?: string
  username?: string
}
interface TgWebApp {
  ready(): void
  expand(): void
  sendData(data: string): void
  openTelegramLink(url: string): void
  setHeaderColor(color: string): void
  setBackgroundColor(color: string): void
  MainButton: TgMainButton
  BackButton: TgBackButton
  colorScheme: 'light' | 'dark'
  platform: string
  initData: string
  initDataUnsafe: { user?: TgUser }
}

function tg(): TgWebApp | undefined {
  return (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp
}

// Скрипт telegram-web-app.js создаёт window.Telegram.WebApp и в обычном браузере —
// поэтому «настоящий» Telegram определяем по platform (вне Telegram она === 'unknown').
function realTelegram(): TgWebApp | undefined {
  const w = tg()
  return w && w.platform && w.platform !== 'unknown' ? w : undefined
}

export const isTelegram = (): boolean => !!realTelegram()

export interface Client {
  id: number
  firstName?: string
  username?: string
}

// Клиент из Telegram (tg_id и имя) — для привязки избранного/скидок к аккаунту.
export function getTelegramUser(): Client | null {
  const u = realTelegram()?.initDataUnsafe?.user
  if (!u) return null
  return { id: u.id, firstName: u.first_name, username: u.username }
}

export function initTelegram(): void {
  const w = realTelegram()
  if (!w) return
  w.ready()
  w.expand()
  // Цвет шапки/фона Telegram — под палитру приложения.
  const paper = w.colorScheme === 'dark' ? '#131211' : '#f2f1ed'
  try {
    w.setBackgroundColor(paper)
    w.setHeaderColor(paper)
  } catch {
    // старые версии клиента могут не поддерживать — не критично
  }
}

// Передать выбор типа и модели в бот. В Telegram — sendData (бот ловит web_app_data);
// вне Telegram (лендинг) — вернём false, вызывающий покажет экран-хэндофф в бот.
export function sendOrder(
  caseId: number,
  caseType: 'standard' | 'custom',
  model: string,
): boolean {
  const w = realTelegram()
  if (!w) return false
  w.sendData(JSON.stringify({ case_id: caseId, case_type: caseType, model }))
  return true
}

export function mainButton(): TgMainButton | undefined {
  return realTelegram()?.MainButton
}

export function backButton(): TgBackButton | undefined {
  return realTelegram()?.BackButton
}

// Deep link в бот со стартовым payload (для лендинга/браузера, где нет sendData).
// Модель кодируем индексом (start-param допускает только [A-Za-z0-9_-]).
// TODO: подставить реальный username бота из конфигурации.
const BOT_USERNAME = 'chehltest_bot'

export function botStartLink(
  caseId: number,
  caseType: 'standard' | 'custom',
  modelIndex: number,
): string {
  return `https://t.me/${BOT_USERNAME}?start=case_${caseId}_${caseType}_m${modelIndex}`
}
