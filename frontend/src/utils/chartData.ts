/**
 * Вспомогательные функции преобразования данных market_news_ml_dataset
 * в форматы TradingView Lightweight Charts и ECharts.
 */

import type { MarketDataItem } from '../types/market'

/** Время свечи для графиков: candle_time (первично) или ts (fallback). */
export function candleTime(item: MarketDataItem): number | null {
  const raw = item.candle_time ?? item.ts
  if (!raw) return null
  const ms = new Date(raw).getTime()
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null
}

/** Есть ли у записи непустая ИИ-аналитика → нужен маркер на графике. */
export function hasAiSummary(item: MarketDataItem): boolean {
  return !!item.ai_text_summary && item.ai_text_summary.trim() !== ''
}

export interface CandlePoint {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export interface VolumePoint {
  time: number
  value: number
  /** true — растущая свеча (buy), false — падающая (sell). Цвет на фронте. */
  up: boolean
}

/** Свечи из записей, отсортированные по времени, без дублей времени. */
export function toCandles(data: MarketDataItem[]): CandlePoint[] {
  const map = new Map<number, CandlePoint>()
  for (const item of data) {
    const time = candleTime(item)
    if (time === null) continue
    map.set(time, {
      time,
      open: item.open_price,
      high: item.high_price,
      low: item.low_price,
      close: item.close_price,
    })
  }
  return [...map.values()].sort((a, b) => a.time - b.time)
}

/** Объемы: суммарный volume с направлением по close vs open. */
export function toVolumes(data: MarketDataItem[]): VolumePoint[] {
  const out: VolumePoint[] = []
  for (const item of data) {
    const time = candleTime(item)
    if (time === null) continue
    out.push({ time, value: item.volume, up: item.close_price >= item.open_price })
  }
  return dedupeByTime(out)
}

/** При real-time обновлении свеча с тем же временем перезаписывается последней. */
export function upsertByTime<T extends { time: number }>(arr: T[], point: T): T[] {
  const idx = arr.findIndex((p) => p.time === point.time)
  if (idx >= 0) {
    const copy = arr.slice()
    copy[idx] = point
    return copy
  }
  // данные приходят хронологически — просто дописываем в конец
  return [...arr, point]
}

function dedupeByTime<T extends { time: number }>(arr: T[]): T[] {
  const map = new Map<number, T>()
  for (const p of arr) map.set(p.time, p)
  return [...map.values()].sort((a, b) => a.time - b.time)
}

/** Метки оси X для ECharts (HH:MM внутри суток, иначе DD.MM). */
export function timeLabels(times: number[]): string[] {
  const daySec = 86400
  const spanSec = times.length > 1 ? times[times.length - 1] - times[0] : 0
  const withinOneDay = spanSec <= daySec * 0.95
  return times.map((t) => {
    const d = new Date(t * 1000)
    return withinOneDay
      ? d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
  })
}
