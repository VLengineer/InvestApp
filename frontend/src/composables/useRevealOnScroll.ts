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
import { onBeforeUnmount, onMounted, shallowRef } from 'vue'

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

  onMounted(() => {
    const root = revealRef.value
    if (!root) return

    // Браузеры без IntersectionObserver — показываем контент сразу
    if (typeof IntersectionObserver === 'undefined') {
      root.querySelectorAll('.reveal').forEach((el) => el.classList.add('is-visible'))
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

    const targets = root.matches('.reveal') ? [root] : Array.from(root.querySelectorAll('.reveal'))
    targets.forEach((el) => observer!.observe(el))
  })

  onBeforeUnmount(() => {
    observer?.disconnect()
    observer = null
  })

  return { revealRef }
}
