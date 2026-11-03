/**
 * useFullscreen — composable раскрытия DOM-элемента на весь экран
 * (стандартный Fullscreen API + fallback для Safari через webkit-префикс).
 *
 * Использование:
 *   const rootEl = ref<HTMLElement | null>(null)
 *   const { isFullscreen, toggle } = useFullscreen(rootEl)
 *
 * Состояние синхронизируется с документом (Exit по Esc тоже работает),
 * слушатель событий снимается при размонтировании компонента.
 */
import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

type FsElement = HTMLElement & {
  webkitRequestFullscreen?: () => Promise<void> | void
}
type FsDocument = Document & {
  webkitFullscreenElement?: Element | null
  webkitExitFullscreen?: () => Promise<void> | void
}

export function useFullscreen(target: Ref<HTMLElement | null>) {
  const isFullscreen = ref(false)

  function fsElement(): Element | null {
    const doc = document as FsDocument
    return doc.fullscreenElement ?? doc.webkitFullscreenElement ?? null
  }

  async function request(el: HTMLElement): Promise<void> {
    const node = el as FsElement
    if (node.requestFullscreen) {
      await node.requestFullscreen()
    } else if (node.webkitRequestFullscreen) {
      await node.webkitRequestFullscreen()
    }
  }

  async function exit(): Promise<void> {
    const doc = document as FsDocument
    if (doc.exitFullscreen) {
      await doc.exitFullscreen()
    } else if (doc.webkitExitFullscreen) {
      await doc.webkitExitFullscreen()
    }
  }

  async function toggle(): Promise<void> {
    const el = target.value
    if (!el) return
    if (fsElement() === el) {
      await exit()
    } else {
      await request(el)
    }
    // Фолбэк: если событие change не пришло (редкие браузеры) — обновим вручную
    isFullscreen.value = fsElement() === el
  }

  const onChange = () => {
    const el = target.value
    isFullscreen.value = !!el && fsElement() === el
  }

  onMounted(() => {
    document.addEventListener('fullscreenchange', onChange)
    document.addEventListener('webkitfullscreenchange', onChange)
  })

  onBeforeUnmount(() => {
    document.removeEventListener('fullscreenchange', onChange)
    document.removeEventListener('webkitfullscreenchange', onChange)
    // При уходе со страницы, пока открыт fullscreen, — корректно выходим
    if (isFullscreen.value) void exit()
  })

  return { isFullscreen, toggle, exit }
}
