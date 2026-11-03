# Сервис 5. Технический анализ свечей (индикаторы + аналитика, формат T-Invest API)

**Реализация:** микросервис `python_test` (FastAPI, порт 8100), префикс `/indicators`
**Ключевые модули:**
- `python_test/app/api/routes/indicators.py` — эндпоинт (stateless-сервис инстанцируется на уровне модуля)
- `python_test/app/services/indicators_service.py` — вся бизнес-логика расчёта
- `python_test/app/schemas/indicators.py` — контракты запроса/ответа
- `python_test/app/utils/candle_parser.py` — конвертация `units/nano`, DataFrame, таймфрейм
- тесты: `python_test/app/tests/test_indicators.py`, `test_candle_parser.py`, `test_last_candle_rsi.py`

## Назначение

Синхронный CPU-сервис: по массиву свеч Tinkoff Invest API (`GetCandles`) возвращает 9 технических индикаторов для каждой свечи + агрегированную аналитику (гэпы, аномалии объёма, тренды, свечные паттерны, режим волатильности, моментум) и метаданные расчёта. БД/Ollama не используются.

## API контракт

### POST `/indicators/calculate` (scope `rag:read`)
Вход `IndicatorsRequest`: `{candles: list[CandleIn]}` (min_length=1; `extra="ignore"`).
`CandleIn`: `open/high/low/close: Money{units: str|int|float, nano: int|float=0}`, `volume: str|int|float=0`, `time: str` (ISO 8601, напр. `2026-11-01T18:25:00Z`), `isComplete: bool=true`, `candleSource: str|null`, `volumeBuy/volumeSell: str|int|float|null`.

Выход `IndicatorsResponse`:
- `indicators: list[IndicatorRow]` — `timestamp, rsi_14, stoch_k, stoch_d, macd, macd_signal, cci_20, williams_r, mfi_14, adx_14, roc_12, atr_14, is_valid` (null где не рассчитано);
- `analytics` — см. правила 6–11;
- `metadata` — `total_candles, valid_candles, warmup_period=40, timeframe_minutes, calculation_time_ms`;
- `last_candle_rsi` — `{timestamp, rsi_14}` последней свечи **после авто-сортировки**.

Ошибка `400` документирована в OpenAPI: `{"code": "not_enough_candles", "message": "Минимум 40 свечей для расчета индикаторов", "details": {}}`.

## Модель данных

Отсутствует (in-memory pandas/numpy). Формула конверсии ТЗ: `value = units + nano / 1e9` (`money_to_float` принимает строки и числа; битое значение → None → свеча отбрасывается). Время парсится `fromisoformat` с заменой `Z→+00:00`, приводится к UTC.

## Бизнес-правила

1. **Минимум 40 свечей** (`WARMUP_PERIOD`) — иначе `TooFewCandlesError` (400). Счёт после отбраковки битых свечей.
2. **Максимум 10 000 свечей** — `TooManyCandlesError` (400, защитный лимит).
3. **Авто-сортировка по времени**; несоответствие порядка не ошибка. Отброшенные свечи → WARNING «Отброшено N некорректных свечей».
4. **Первые 40 свечей:** `is_valid=false`, но значения индикаторов отдаются как есть (не обнуляются принудительно).
5. **Индикаторы (pandas-ta):** RSI(14), Stochastic(14,3,3), MACD(12,26,9), Williams %R(14), MFI(14), ADX(14), ROC(12,%), ATR(14). **CCI(20) считается собственной эталонной формулой** `(TP − SMA(TP)) / (0.015·MAD(TP))` из-за известного бага приоритета операторов в pandas-ta. Округления: осцилляторы/CCI/ADX/MFI — 2 знака; MACD/ROC/ATR — 4. NaN/Inf → null.
6. **Гэпы:** `gap% = (open_i − close_{i−1})/close_{i−1}·100`, порог |gap| > 0.05%; severity: high >0.3%, medium ≥0.1%, иначе low; direction up/down.
7. **Аномалии объёма:** `volume > 3 × SMA20(volume)` (окно за **предыдущие** 20 свечей, со сдвигом — текущая не входит); direction buy/sell по `volumeBuy > volumeSell`; поля `volume, avg_volume_20, anomaly_ratio`.
8. **Тренды:** серии ≥5 свечей одного знака Δclose (0 разрывает серию); `price_change_percent` от первой до последней свечи серии; strength: strong >0.5%, medium ≥0.2%, иначе weak.
9. **Паттерны** (приоритет проверки сверху вниз, один паттерн на свечу): bullish/bearish engulfing (тело перекрывает тело предыдущей противоположной свечи; confidence = min(1, 0.5+0.5·(body/prev_body−1)), минимум 0.5) → doji (body/range < 0.1; confidence = min(1,(1−ratio)·0.9+0.1)) → hammer (нижняя тень ≥2×тела, верхняя ≤тела, тело ≤35% диапазона) → inverted_hammer (зеркально); симметричные длинные тени при теле <10% диапазона доклассифицируются как doji.
10. **Режим волатильности:** `ratio = ATR14_тек / mean(ATR14 за последние 20 непустых)`; high_volatility >1.2, low_volatility <0.8, иначе normal (при отсутствии ATR — normal, ratio null).
11. **Моментум:** current=ROC12 последней свечи, acceleration=ΔROC; regime: neutral (оба ≈0), bullish_acceleration/deceleration (ROC>0 по знаку Δ), bearish_deceleration/acceleration (ROC<0).
12. **Незавершённые свечи** (`isComplete=false`) — WARNING, расчёт продолжается; **пропуски во времени** (шаг > 1.5×таймфрейма) — WARNING, расчёт продолжается. Таймфрейм определяется медианой шага (в минутах, дефолт 5).

## Обработка ошибок

| Ситуация | Реакция |
|---|---|
| <40 валидных свечей | AppError → JSON `{code:"not_enough_candles"}` HTTP 400 |
| >10 000 свечей | HTTP 400 `too_many_candles` |
| Битая свеча (время/цены) | молча отбрасывается в парсере, суммарный WARNING |
| Недостаточно данных для индикатора | null в поле (NaN→None) |
| Неверная схема тела | FastAPI 422 |

## Безопасность

JWT scope `rag:read`; вычислительный лимит 10k свечей как защита от DoS; внешних вызовов нет.

## Паттерны

Stateless service (один экземпляр на модуль роутера), Strategy разбора колонок pandas-ta (`_column` по префиксам), чистые функции анализа, DTO-слой Pydantic, единый обработчик доменных ошибок.

## Тесты

`test_indicators.py` (warmup, формулы, аномалии/тренды/паттерны), `test_candle_parser.py` (units+nano, время, таймфрейм), `test_last_candle_rsi.py`.
