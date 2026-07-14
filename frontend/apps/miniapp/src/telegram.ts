// Тонкая обёртка над Telegram WebApp SDK. В обычном браузере (лендинг/превью)
// window.Telegram отсутствует — методы деградируют мягко.

interface TgMainButton {
  setText(text: string): void
  show(): void
  hide(): void
  onClick(cb: () => void): void
  offClick(cb: () => void): void
}
interface TgWebApp {
  ready(): void
  expand(): void
  sendData(data: string): void
  openTelegramLink(url: string): void
  MainButton: TgMainButton
  colorScheme: 'light' | 'dark'
}

function tg(): TgWebApp | undefined {
  return (window as unknown as { Telegram?: { WebApp?: TgWebApp } }).Telegram?.WebApp
}

export const isTelegram = (): boolean => !!tg()

export function initTelegram(): void {
  const w = tg()
  if (!w) return
  w.ready()
  w.expand()
}

// Передать выбор типа чехла в бот. В Telegram — через sendData (бот ловит web_app_data);
// вне Telegram (лендинг) — вернём false, вызывающий откроет deep link в бот.
export function sendOrder(caseId: number, caseType: 'standard' | 'custom'): boolean {
  const w = tg()
  if (!w) return false
  w.sendData(JSON.stringify({ case_id: caseId, case_type: caseType }))
  return true
}

export function mainButton(): TgMainButton | undefined {
  return tg()?.MainButton
}
