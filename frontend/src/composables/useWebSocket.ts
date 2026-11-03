/**
 * useWebSocket — composable для real-time подписки на новые данные рынка.
 *
 * Протокол (ТЗ): клиент шлёт { "type": "subscribe", "figi": "..." },
 * сервер фильтрует по FIGI на своей стороне и присылает
 * { "type": "new_data", "data": MarketDataItem, "figi": "..." }.
 *
 * Особенности реализации:
 *  - относительный URL ws(s)://<текущий хост>/ws/market-updates — работает
 *    через прокси Vite (ws:true), браузеру не нужно знать docker-имена;
 *  - автопереподключение с экспоненциальным backoff (max 15 c);
 *  - при реконнекте текущая подписка восстанавливается автоматически;
 *  - дедупликация сообщений по id записи (защита от повторов после reconnect).
 */

import { onBeforeUnmount, ref, shallowRef } from 'vue'
import type { MarketDataItem, WsServerMessage } from '../types/market'

export type MarketUpdateHandler = (item: MarketDataItem) => void

/** WS-эндпоинт BFF относительно текущего origin страницы. */
function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}/ws/market-updates`
}

export function useWebSocket(onNewData: MarketUpdateHandler) {
  const connected = ref(false)
  const subscribedFigi = ref<string | null>(null)

  const socket = shallowRef<WebSocket | null>(null)
  let reconnectTimer: number | undefined
  let reconnectDelay = 1000
  let manualClose = false
  // id уже обработанных записей — защита от дублей после переподключения
  const seenIds = new Set<string>()

  function sendSubscribe(figi: string) {
    const ws = socket.value
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'subscribe', figi }))
    }
  }

  function handleMessage(raw: string) {
    let msg: WsServerMessage
    try {
      msg = JSON.parse(raw) as WsServerMessage
    } catch {
      return
    }
    if (msg.type === 'new_data') {
      const item = msg.data
      if (!item || seenIds.has(item.id)) return // дедупликация
      seenIds.add(item.id)
      // Ограничиваем размер множества, чтобы не раздувать память на долгих сессиях
      if (seenIds.size > 5000) {
        const first = seenIds.values().next().value
        if (first) seenIds.delete(first)
      }
      onNewData(item)
    }
  }

  function connect() {
    if (socket.value && (socket.value.readyState === WebSocket.OPEN || socket.value.readyState === WebSocket.CONNECTING)) {
      return
    }
    manualClose = false
    const ws = new WebSocket(wsUrl())
    socket.value = ws

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000 // сброс backoff при успешном коннекте
      // Восстанавливаем подписку (первый коннект или после reconnect)
      if (subscribedFigi.value) sendSubscribe(subscribedFigi.value)
    }
    ws.onmessage = (ev) => handleMessage(typeof ev.data === 'string' ? ev.data : '')
    ws.onclose = () => {
      connected.value = false
      socket.value = null
      if (!manualClose) scheduleReconnect()
    }
    ws.onerror = () => {
      // onclose всё равно вызовется после onerror — просто закрываем сокет
      ws.close()
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer !== undefined) return
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = undefined
      connect()
    }, reconnectDelay)
    reconnectDelay = Math.min(reconnectDelay * 2, 15000)
  }

  /** Подписаться на FIGI (при смене — сервер сам отпишет от предыдущего). */
  function subscribe(figi: string) {
    subscribedFigi.value = figi
    seenIds.clear() // новая история — старые id больше не актуальны
    connect()
    sendSubscribe(figi)
  }

  function disconnect() {
    manualClose = true
    if (reconnectTimer !== undefined) {
      clearTimeout(reconnectTimer)
      reconnectTimer = undefined
    }
    socket.value?.close()
    socket.value = null
    connected.value = false
  }

  onBeforeUnmount(disconnect)

  return { connected, subscribedFigi, subscribe, disconnect }
}
