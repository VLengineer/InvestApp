/**
 * useChartSync — общий композабл синхронизации ECharts-графиков дашборда
 * с основным графиком свечей (PriceChart на Lightweight Charts).
 *
 * Задачи:
 *  1. Единый «барабан времени» (shared time window) — индексное окно [start, end]
 *     по отсортированному массиву времен свечей (unix-секунды).
 *  2. Зум колесом/пинчем и скролл перетаскиванием внутри окна; все графики
 *     (свечи + осцилляторы + объёмы) перерисовываются в одном окне —
 *     мультитаймфрейменная синхронизация без рассинхрона.
 *  3. Crosshair: при наведении на любой график линия перекрестия появляется
 *     на всех остальных (echarts.dispatchAction), значение показывается в
 *     tooltip'ах с точными данными.
 *  4. Fullscreen toggle — раскрытие группы графиков на весь экран
 *     (экранирование из Dashboard/OscillatorCharts).
 *
 * Индексное окно выбрано специально: времена свечей уникальны и отсортированы
 * (см. utils/chartData.toCandles), поэтому индекс === позиция на оси времени
 * и для category-axis ECharts, и для time-scale Lightweight Charts.
 */
import { computed, onBeforeUnmount, readonly, ref, shallowRef } from 'vue'

export interface ChartSyncState {
  /** Отсортированные уникальные времена свечей (unix-секунды) — «барабан». */
  times: number[]
}

const MIN_WINDOW = 10 // не зумим меньше 10 свечей в окне

export function useChartSync() {
  const drum = shallowRef<number[]>([])
  /** Окно видимости: индексы [startIdx, endIdx) в барабане. */
  const startIdx = ref(0)
  const endIdx = ref(0)

  /** Подписчики на изменение окна (каждый график перерисовывает dataZoom). */
  type WindowListener = (start: number, end: number) => void
  const listeners = new Set<WindowListener>()

  /** Полный перерасчёт окна при загрузке нового FIGI/истории. */
  function setDrum(times: number[]) {
    drum.value = times
    startIdx.value = 0
    endIdx.value = Math.max(MIN_WINDOW, times.length)
    emitWindow()
  }

  /** Расширение барабана real-time свечой без сброса текущего окна. */
  function appendTime(t: number) {
    const arr = drum.value
    if (arr.length > 0 && t <= arr[arr.length - 1]) return
    const wasAtEnd = endIdx.value >= arr.length
    arr.push(t)
    if (wasAtEnd) {
      endIdx.value = arr.length
      emitWindow()
    }
  }

  function emitWindow() {
    const s = startIdx.value
    const e = endIdx.value
    for (const fn of listeners) fn(s, e)
  }

  function onWindowChange(fn: WindowListener): () => void {
    listeners.add(fn)
    fn(startIdx.value, endIdx.value)
    return () => listeners.delete(fn)
  }

  /**
   * Применить окно к конкретному ECharts-графику.
   * Графики используют `dataZoom` c startValue/endValue — программный зум
   * без анимаций и с корректным crosshair.
   *
   * ВАЖНО: тип 'hidden' существует только в полной сборке echarts (плагин
   * installDataZoomHidden). В модульной сборке echarts/core (используется
   * в проекте) он не зарегистрирован и приводил к фатальной ошибке
   * "Component dataZoom.hidden is used but not imported". Используем
   * 'inside' — у него нет view-класса (панель не рисуется), но опции окна
   * работают так же.
   */
  function applyToInstance(inst: { setOption: (o: never, cfg?: object) => void }) {
    const s = startIdx.value
    const e = endIdx.value
    inst.setOption(
      {
        dataZoom: [
          {
            type: 'inside',
            xAxisIndex: 0,
            zoomOnMouseWheel: false,
            moveOnMouseMove: false,
            moveOnMouseWheel: false,
            preventDefaultMouseMove: false,
            startValue: s,
            endValue: Math.max(s + 1, e - 1),
          },
        ],
      } as never,
      { replaceMerge: [] },
    )
  }

  /* ------------------------- Управление окном ------------------------------ */

  function clampWindow(s: number, e: number): [number, number] {
    const n = drum.value.length
    let len = Math.min(Math.max(e - s, MIN_WINDOW), n)
    let start = Math.max(0, Math.min(s, n - len))
    let end = start + len
    if (end > n) {
      end = n
      start = Math.max(0, end - len)
    }
    return [start, end]
  }

  /** Зум вокруг якоря (доля позиции курсора в окне 0..1). factor < 1 — приближение. */
  function zoom(factor: number, anchorRatio = 0.5) {
    const s = startIdx.value
    const e = endIdx.value
    const len = e - s
    const anchor = s + len * anchorRatio
    const newLenRaw = len * factor
    const minLen = Math.min(MIN_WINDOW, drum.value.length || MIN_WINDOW)
    const newLen = Math.min(Math.max(newLenRaw, minLen), drum.value.length || minLen)
    const ns = anchor - newLen * anchorRatio
    const [cs, ce] = clampWindow(ns, ns + newLen)
    startIdx.value = cs
    endIdx.value = ce
    emitWindow()
  }

  /** Скролл на deltaCount свечей (панорамирование по оси времени). */
  function pan(deltaCount: number) {
    const len = endIdx.value - startIdx.value
    const [cs, ce] = clampWindow(startIdx.value + deltaCount, startIdx.value + deltaCount + len)
    startIdx.value = cs
    endIdx.value = ce
    emitWindow()
  }

  /** Показать всё (кнопка «сброс зума»). */
  function fitAll() {
    startIdx.value = 0
    endIdx.value = drum.value.length
    emitWindow()
  }

  /** Установить окно по абсолютным индексам (синхронизация со свечным графиком). */
  function setWindow(s: number, e: number) {
    const [cs, ce] = clampWindow(s, e)
    if (cs === startIdx.value && ce === endIdx.value) return
    startIdx.value = cs
    endIdx.value = ce
    emitWindow()
  }

  /** Индекс барабана по unix-времени (для сопоставления crosshair'ов). */
  function indexOfTime(t: number): number {
    return drum.value.indexOf(t)
  }

  /** Текущее окно как пара unix-времен (для timeScale Lightweight Charts). */
  const windowTimes = computed(() => {
    const arr = drum.value
    if (arr.length === 0) return null
    const s = Math.min(startIdx.value, arr.length - 1)
    const e = Math.max(Math.min(endIdx.value, arr.length) - 1, s)
    return { from: arr[s], to: arr[e] }
  })

  return {
    drum: readonly(drum),
    startIdx: readonly(startIdx),
    endIdx: readonly(endIdx),
    windowTimes,
    setDrum,
    appendTime,
    onWindowChange,
    applyToInstance,
    zoom,
    pan,
    fitAll,
    setWindow,
    indexOfTime,
  }
}

export type ChartSync = ReturnType<typeof useChartSync>

/* ------------------- DOM-обработчики зума/скролла -------------------------- */

/**
 * Навешивает на элемент wheel-зум (Ctrl/Cmd+колесо или просто колесо над
 * осцилляторами) и горизонтальный drag-скролл. Возвращает функцию-уничтожитель.
 *
 * Порог pan: ~8px на свечу — комфортная скорость панорамирования.
 */
export function attachWheelZoomScroll(
  el: HTMLElement,
  sync: Pick<ChartSync, 'zoom' | 'pan' | 'startIdx' | 'endIdx'>,
): () => void {
  const PX_PER_CANDLE = 8

  const onWheel = (ev: WheelEvent) => {
    ev.preventDefault()
    const rect = el.getBoundingClientRect()
    const anchorRatio = (ev.clientX - rect.left) / Math.max(1, rect.width)
    // deltaY > 0 — колесо «от себя» → отдалить (окно шире)
    const factor = ev.deltaY > 0 ? 1.25 : 0.8
    sync.zoom(factor, anchorRatio)
  }

  let dragging = false
  let lastX = 0
  let moved = 0

  const onPointerDown = (ev: PointerEvent) => {
    if (ev.button !== 0) return
    dragging = true
    lastX = ev.clientX
    moved = 0
    el.setPointerCapture?.(ev.pointerId)
    el.classList.add('is-dragging')
  }

  const onPointerMove = (ev: PointerEvent) => {
    if (!dragging) return
    const dx = ev.clientX - lastX
    lastX = ev.clientX
    moved += Math.abs(dx)
    const candles = dx / PX_PER_CANDLE
    // целочисленные шаги pan, остаток накапливаем
    const whole = Math.trunc(candles)
    if (whole !== 0) {
      ;(sync as ChartSync).pan(-whole)
    }
  }

  const onPointerUp = (ev: PointerEvent) => {
    if (!dragging) return
    dragging = false
    el.releasePointerCapture?.(ev.pointerId)
    el.classList.remove('is-dragging')
  }

  el.addEventListener('wheel', onWheel, { passive: false })
  el.addEventListener('pointerdown', onPointerDown)
  el.addEventListener('pointermove', onPointerMove)
  el.addEventListener('pointerup', onPointerUp)
  el.addEventListener('pointercancel', onPointerUp)

  return () => {
    el.removeEventListener('wheel', onWheel)
    el.removeEventListener('pointerdown', onPointerDown)
    el.removeEventListener('pointermove', onPointerMove)
    el.removeEventListener('pointerup', onPointerUp)
    el.removeEventListener('pointercancel', onPointerUp)
  }
}

/**
 * Кросс-хэйр синхронизация: при движении мыши по одному ECharts-графику
 * рассылаем showTip/moveCrosshair в остальные экземпляры той же группы.
 */
type EChartsLike = {
  dispatchAction: (payload: { type: string } & Record<string, unknown>) => void
  containPixel?: (finder: string, pos: [number, number]) => boolean
}

export function createCrosshairHub() {
  const members = new Set<EChartsLike>()

  function register(inst: EChartsLike): () => void {
    members.add(inst)
    return () => members.delete(inst)
  }

  /** Источник события: инстанс + координаты мыши относительно него. */
  function broadcastFrom(source: EChartsLike, x: number, y: number) {
    for (const inst of members) {
      if (inst === source) continue
      inst.dispatchAction({ type: 'showTip', x, y })
      inst.dispatchAction({
        type: 'updateAxisPointer',
        x,
        y,
        position: [x, y],
      })
    }
  }

  function hideEverywhere(except?: EChartsLike) {
    for (const inst of members) {
      if (inst === except) continue
      inst.dispatchAction({ type: 'hideTip' })
    }
  }

  return { register, broadcastFrom, hideEverywhere }
}

export type CrosshairHub = ReturnType<typeof createCrosshairHub>
