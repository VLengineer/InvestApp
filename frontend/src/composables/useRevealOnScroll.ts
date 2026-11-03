/**
 * useRevealOnScroll — composable появления секций при скролле
 * на чистом IntersectionObserver (без сторонних библиотек).
 *
 * Использование:
 *   <section ref="revealRef" class="reveal">…</section>
 *   const { revealRef } = useRevealOnScroll()
 *
 * При пересечении области видимости элементу добавляется класс
 * `.is-visible` (стили перехода — в animations.css). После показа
 * наблюдатель отключается — анимация проигрывается один раз.
 */
import { nextTick, onBeforeUnmount, onMounted, shallowRef } from 'vue'

export interface RevealOptions {
  /** Доля видимости элемента для срабатывания (по умолчанию 0.15). */
  threshold?: number
  /** Отступ «зоны обнаружения» (по умолчанию 0px 0px -40px 0px). */
  rootMargin?: string
}

export function useRevealOnScroll(options: RevealOptions = {}) {
  const { threshold = 0.15, rootMargin = '0px 0px -40px 0px' } = options

  /** Ref на корневой элемент; внутри ищутся все .reveal-секции. */
  const revealRef = shallowRef<HTMLElement | null>(null)

  let observer: IntersectionObserver | null = null
  let mutationObserver: MutationObserver | null = null

  function markVisible(el: Element) {
    el.classList.add('is-visible')
  }

  function observeNewTargets(root: HTMLElement) {
    if (!observer) return
    const targets = root.matches('.reveal')
      ? [root]
      : Array.from(root.querySelectorAll('.reveal:not(.is-visible)'))
    targets.forEach((el) => observer!.observe(el))
  }

  onMounted(async () => {
    await nextTick()
    const root = revealRef.value
    if (!root) return

    // Браузеры без IntersectionObserver — показываем контент сразу
    if (typeof IntersectionObserver === 'undefined') {
      root.querySelectorAll('.reveal').forEach(markVisible)
      return
    }

    observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.classList.add('is-visible')
          observer?.unobserve(entry.target) // один раз — без повторных дёрганий
        }
      },
      { threshold, rootMargin },
    )

    observeNewTargets(root)

    // Динамические секции (графики появляются после выбора FIGI):
    // следим за DOM-деревом и навешиваем наблюдатель на новые .reveal-узлы.
    if (typeof MutationObserver !== 'undefined') {
      mutationObserver = new MutationObserver((mutations) => {
        for (const m of mutations) {
          m.addedNodes.forEach((node) => {
            if (!(node instanceof HTMLElement)) return
            if (node.matches('.reveal:not(.is-visible)')) observer?.observe(node)
            node.querySelectorAll('.reveal:not(.is-visible)').forEach((el) => observer?.observe(el))
          })
        }
      })
      mutationObserver.observe(root, { childList: true, subtree: true })
    }
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
    mutationObserver?.disconnect()
    mutationObserver = null
  })

  return { revealRef }
}
