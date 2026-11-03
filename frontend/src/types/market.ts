/**
 * Типы данных рынка — зеркало Pydantic-схем backend-frontend
 * (app/schemas/market_data.py). Даты приходят в ISO-8601 (UTC).
 */

/** Одна заявка стакана. */
export interface OrderBookLevel {
  position: number
  price: number
  quantity: number
}

/** Строка market_news_ml_dataset — базовая единица данных дашборда. */
export interface MarketDataItem {
  id: string
  figi: string | null
  source: string | null
  title: string | null
  content: string | null
  ts: string | null
  candle_time: string | null

  // OHLCV
  open_price: number
  high_price: number
  low_price: number
  close_price: number
  volume: number
  volume_buy: number
  volume_sell: number
  is_complete: boolean | null

  // Осцилляторы / индикаторы
  rsi_14: number
  stoch_k: number
  stoch_d: number
  cci_20: number
  williams_r: number
  roc_12: number
  mfi_14: number
  macd: number
  macd_signal: number
  adx_14: number
  atr_14: number

  // Рыночные данные T-Invest
  limit_up_units: number
  limit_down_units: number
  close_price_units: number
  last_price_units: number
  price_currency: string
  last_price_ts: string | null
  orderbook_ts: string | null
  close_price_ts: string | null
  depth: number | null

  // Аналитика ИИ
  ai_sentiment_score: number | null
  ai_relevance_score: number | null
  ai_expected_impact: number | null
  ai_confidence: number | null
  ai_text_summary: string | null
  /**
   * Сырой JSON-ответ ИИ (колонка JSONB `ai_raw_response`; в части выгрузок
   * встречается написание `ai_raw_responce` — оба варианта принимаем на фронте,
   * см. utils pickAiRaw). Структура — см. types/aiAnalysis.ts (зеркало temp.json).
   */
  ai_raw_response: Record<string, unknown> | null
  /** Альтернативное (историческое) написание колонки — опционально. */
  ai_raw_responce?: Record<string, unknown> | string | null

  // Целевые переменные ML
  target_horizon_minutes: number
  target_future_return_pct: number | null
  target_direction: number | null
  target_volatility_threshold_pct: number | null

  // Стакан (заполняется бэкендом)
  orderbook_asks: OrderBookLevel[]
  orderbook_bids: OrderBookLevel[]
}

/** GET /api/market/figis */
export interface FigiListResponse {
  figis: string[]
}

/** GET /api/market/initial-data?figi=... */
export interface InitialDataResponse {
  data: MarketDataItem[]
  figi: string
}

/** GET /api/market/news/{id} */
export interface NewsResponse {
  news: MarketDataItem
}

/** Сообщения WebSocket /ws/market-updates. */
export type WsServerMessage =
  | { type: 'new_data'; data: MarketDataItem; figi: string }
  | { type: 'subscribe_ack'; figi: string }
  | { type: 'unsubscribe_ack' }
  | { type: 'error'; message?: string; figi?: string }
  | { type: 'pong'; [k: string]: unknown }

export type WsClientMessage =
  | { type: 'subscribe'; figi: string }
  | { type: 'unsubscribe' }
