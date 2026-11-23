import { type RefObject, useEffect, useRef } from 'react'

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/**
 * Клавиатура и фокус для модального окна:
 * - Escape закрывает (если onClose решает, что можно);
 * - Tab и Shift+Tab ходят по кругу внутри окна, а не уходят на страницу под ним;
 * - при открытии фокус внутри окна, при закрытии возвращается туда, откуда открыли.
 */
export function useModalA11y(ref: RefObject<HTMLElement | null>, onClose: () => void): void {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  // Кто открыл окно — запоминаем при первом рендере, до монтирования: автофокус поля внутри
  // окна сработает раньше эффекта, и «активным элементом» к тому моменту было бы само поле.
  const openerRef = useRef<HTMLElement | null | undefined>(undefined)
  if (openerRef.current === undefined) openerRef.current = document.activeElement as HTMLElement | null

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const opener = openerRef.current

    if (!el.contains(document.activeElement)) {
      ;(el.querySelector<HTMLElement>(FOCUSABLE) ?? el).focus()
    }

    function onKeyDown(e: KeyboardEvent) {
      if (!el) return
      if (e.key === 'Escape') {
        e.stopPropagation()
        closeRef.current()
        return
      }
      if (e.key !== 'Tab') return
      const items = [...el.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
        (item) => item.offsetParent !== null,
      )
      if (items.length === 0) {
        e.preventDefault()
        el.focus()
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || active === el)) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && active === last) {
        e.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (opener?.isConnected) opener.focus()
    }
  }, [ref])
}
