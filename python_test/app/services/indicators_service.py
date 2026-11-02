"""Сервис расчёта технических индикаторов и аналитики по свечным данным.

Индикаторы считаются библиотекой ``pandas-ta`` (RSI, Stochastic, MACD, CCI,
Williams %R, MFI, ADX, ROC, ATR). Исключение — CCI: в pandas-ta 0.3.x/0.4.x
известный баг (отсутствуют скобки в формуле ``(tp - sma) / (c * mad)``,
см. https://github.com/twopirllc/pandas-ta/issues/ — значения завышены на
порядки), поэтому CCI считается эталонной формулой напрямую.

Аналитика (ТЗ п.2.3): гэпы, аномалии объёма, тренды, свечные паттерны,
режим волатильности, моментум.

Правила (ТЗ):
  * первые ``WARMUP_PERIOD = 40`` свечей — ``is_valid: false``;
  * менее 40 свечей — ошибка 400 "Минимум 40 свечей для расчета индикаторов";
  * несоответствие порядка свечей по времени — авто-сортировка;
  * пропуски во времени — warning в лог, расчёт продолжается;
  * незавершённые свечи (``isComplete: false``) — warning (могут искажать
    индикаторы), но расчёт продолжается (рекомендация ТЗ п.5).
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

import numpy as np
import pandas as pd
import pandas_ta as ta

from app.core.exceptions import AppError
from app.schemas.indicators import (
    AnalyticsResponse,
    CandlePattern,
    GapInfo,
    IndicatorsMetadata,
    IndicatorsRequest,
    IndicatorsResponse,
    IndicatorRow,
    MomentumInfo,
    TrendInfo,
    VolatilityRegime,
    VolumeAnomaly,
)
from app.utils.candle_parser import (
    candles_to_dataframe,
    find_time_gaps,
    infer_timeframe_minutes,
)

logger = logging.getLogger(__name__)

# --------------------------- константы ТЗ -----------------------------------
WARMUP_PERIOD = 40          # первые N свечей — невалидные (прогрев индикаторов)
MAX_CANDLES = 10_000        # защитный лимит входных данных (рекомендация ТЗ п.5)

GAP_THRESHOLD_PCT = 0.05    # порог обнаружения гэпа, %
VOLUME_ANOMALY_MULT = 3.0   # объём > 3 * SMA20(volume)
VOLUME_LOOKBACK = 20
TREND_MIN_CANDLES = 5       # серия из 5+ свечей в одну сторону
ATR_AVG_LOOKBACK = 20       # среднее ATR за 20 свечей

ROC_EPS = 1e-9              # «нулевой» ROC для классификации моментума


class TooFewCandlesError(AppError):
    """Ошибка ТЗ п.3.4: недостаточно свечей для расчёта (HTTP 400)."""

    status_code = 400
    code = "not_enough_candles"


class TooManyCandlesError(AppError):
    """Защитный лимит входных данных (рекомендация ТЗ п.5)."""

    status_code = 400
    code = "too_many_candles"


def _round(value: Any, ndigits: int) -> float | None:
    """float c округлением; NaN/None → None (поле ответа тогда null)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, ndigits)


class IndicatorsService:
    """Бизнес-логика POST /indicators/calculate (без состояния — чистые функции)."""

    # ============================ публичный API ==============================
    def calculate(self, request: IndicatorsRequest) -> IndicatorsResponse:
        started = time.perf_counter()

        raw = [c.model_dump() for c in request.candles]
        if len(raw) < WARMUP_PERIOD:
            raise TooFewCandlesError("Минимум 40 свечей для расчета индикаторов")
        if len(raw) > MAX_CANDLES:
            raise TooManyCandlesError(
                f"Слишком много свечей ({len(raw)}). Максимум {MAX_CANDLES} за один запрос."
            )

        df = candles_to_dataframe(raw)  # авто-сортировка по времени внутри
        if len(df) < WARMUP_PERIOD:
            raise TooFewCandlesError("Минимум 40 свечей для расчета индикаторов")

        dropped = len(raw) - len(df)
        if dropped:
            logger.warning("Отброшено %d некорректных свечей (битое время/цены)", dropped)
        if not df["is_complete"].all():
            incomplete = int((~df["is_complete"]).sum())
            logger.warning(
                "В наборе %d незавершённых свечей (isComplete=false) — "
                "они могут искажать значения индикаторов", incomplete
            )

        timeframe = infer_timeframe_minutes(df)
        gap_indices = find_time_gaps(df, timeframe)
        if gap_indices:
            logger.warning(
                "Обнаружены пропуски во времени между свечами (%d шт., таймфрейм %d мин) — "
                "расчёт продолжается", len(gap_indices), timeframe,
            )

        indicators_df = self._calculate_indicators(df)
        rows = self._build_indicator_rows(df, indicators_df)

        analytics = AnalyticsResponse(
            gaps=self._detect_gaps(df),
            volume_anomalies=self._detect_volume_anomalies(df),
            trends=self._detect_trends(df),
            candle_patterns=self._detect_patterns(df),
            volatility_regime=self._volatility_regime(indicators_df),
            momentum=self._momentum(indicators_df),
        )

        elapsed_ms = int((time.perf_counter() - started) * 1000)
        valid_candles = sum(1 for r in rows if r.is_valid)
        logger.info(
            "Расчёт индикаторов завершён: свечей=%d, валидных=%d, таймфрейм=%d мин, %d мс",
            len(rows), valid_candles, timeframe, elapsed_ms,
        )

        return IndicatorsResponse(
            indicators=rows,
            analytics=analytics,
            metadata=IndicatorsMetadata(
                total_candles=len(rows),
                valid_candles=valid_candles,
                warmup_period=WARMUP_PERIOD,
                timeframe_minutes=timeframe,
                calculation_time_ms=elapsed_ms,
            ),
        )

    # ======================== технические индикаторы =========================
    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Считает все 9 индикаторов ТЗ (pandas-ta + эталонный CCI)."""
        high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]

        rsi = ta.rsi(close, length=14)
        stoch = ta.stoch(high, low, close, k=14, d=3, smooth_k=3)
        macd = ta.macd(close, fast=12, slow=26, signal=9)
        willr = ta.willr(high, low, close, length=14)
        mfi = ta.mfi(high, low, close, volume, length=14)
        adx = ta.adx(high, low, close, length=14)
        roc = ta.roc(close, length=12, percentage=True)
        atr = ta.atr(high, low, close, length=14)

        out = pd.DataFrame(index=df.index)
        out["rsi_14"] = rsi
        out["stoch_k"] = self._column(stoch, ("STOCHk",))
        out["stoch_d"] = self._column(stoch, ("STOCHd",))
        out["macd"] = self._column(macd, ("MACD_",))
        out["macd_signal"] = self._column(macd, ("MACDs",))
        out["cci_20"] = self._cci(high, low, close, length=20)
        out["williams_r"] = willr
        out["mfi_14"] = mfi
        out["adx_14"] = self._column(adx, ("ADX",))
        out["roc_12"] = roc
        out["atr_14"] = atr
        return out

    @staticmethod
    def _column(frame: Any, prefixes: tuple[str, ...]) -> pd.Series:
        """Достаёт нужную колонку из DataFrame'а pandas-ta (имена содержат периоды)."""
        if frame is None:
            return pd.Series(dtype="float64")
        if isinstance(frame, pd.Series):
            return frame
        for prefix in prefixes:
            for col in frame.columns:
                if col.startswith(prefix) and not col.startswith(prefix + "h"):
                    return frame[col]
        return pd.Series(index=frame.index, dtype="float64")

    @staticmethod
    def _cci(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
        """CCI эталонной формулы: (TP − SMA(TP)) / (0.015 · MAD(TP)).

        Собственная реализация вместо ``ta.cci`` — из-за бага операторов
        приоритета в pandas-ta (деление применяется только к ``sma``).
        """
        tp = (high + low + close) / 3.0
        sma = tp.rolling(length, min_periods=length).mean()
        mad = tp.rolling(length, min_periods=length).apply(
            lambda x: float(np.mean(np.abs(x - x.mean()))), raw=True
        )
        return (tp - sma) / (0.015 * mad)

    def _build_indicator_rows(self, df: pd.DataFrame, ind: pd.DataFrame) -> list[IndicatorRow]:
        """Формирует пострядовый ответ; первые WARMUP_PERIOD свечей — is_valid=false."""
        rows: list[IndicatorRow] = []
        precision = {
            "rsi_14": 2, "stoch_k": 2, "stoch_d": 2, "macd": 4, "macd_signal": 4,
            "cci_20": 2, "williams_r": 2, "mfi_14": 2, "adx_14": 2,
            "roc_12": 4, "atr_14": 4,
        }
        for i in range(len(df)):
            is_valid = i >= WARMUP_PERIOD
            values: dict[str, Any] = {"timestamp": df["timestamp"].iloc[i], "is_valid": is_valid}
            for name, digits in precision.items():
                value = ind[name].iloc[i] if name in ind.columns else None
                # ТЗ п.2.2: для warmup-свечей значения могут быть null — отдаём то,
                # что уже догрето на этой позиции (недосчитанное → None/null)
                values[name] = _round(value, digits)
            rows.append(IndicatorRow(**values))
        return rows

    # ================================ аналитика ==============================
    # 2.3.1 гэпы ----------------------------------------------------------------
    def _detect_gaps(self, df: pd.DataFrame) -> list[GapInfo]:
        """Разрыв м/у close предыдущей и open текущей свечи; порог |gap| > 0.05%."""
        gaps: list[GapInfo] = []
        prev_close = df["close"].shift(1)
        for i in range(1, len(df)):
            pc = prev_close.iloc[i - 1]
            o = df["open"].iloc[i]
            if pc == 0 or pd.isna(pc):
                continue
            gap_pct = (o - pc) / pc * 100.0
            if abs(gap_pct) > GAP_THRESHOLD_PCT:
                severity = "high" if abs(gap_pct) > 0.3 else "medium" if abs(gap_pct) >= 0.1 else "low"
                gaps.append(
                    GapInfo(
                        timestamp=df["timestamp"].iloc[i],
                        gap_percent=_round(gap_pct, 4) or 0.0,
                        direction="up" if gap_pct > 0 else "down",
                        severity=severity,
                    )
                )
        return gaps

    # 2.3.2 аномалии объёма ------------------------------------------------------
    def _detect_volume_anomalies(self, df: pd.DataFrame) -> list[VolumeAnomaly]:
        """volume > 3 × средний объём за последние 20 свечей (окно без текущей)."""
        anomalies: list[VolumeAnomaly] = []
        avg_volume = df["volume"].rolling(VOLUME_LOOKBACK, min_periods=VOLUME_LOOKBACK).mean().shift(1)
        for i in range(len(df)):
            avg = avg_volume.iloc[i]
            vol = df["volume"].iloc[i]
            if pd.isna(avg) or avg <= 0:
                continue
            if vol > VOLUME_ANOMALY_MULT * avg:
                direction = "buy" if df["volume_buy"].iloc[i] > df["volume_sell"].iloc[i] else "sell"
                anomalies.append(
                    VolumeAnomaly(
                        timestamp=df["timestamp"].iloc[i],
                        volume=_round(vol, 2),
                        avg_volume_20=_round(avg, 2),
                        anomaly_ratio=_round(vol / avg, 2),
                        direction=direction,
                    )
                )
        return anomalies

    # 2.3.3 тренды ---------------------------------------------------------------
    def _detect_trends(self, df: pd.DataFrame) -> list[TrendInfo]:
        """Серии из 5+ свечей подряд в одну сторону по close (close > prev close — up)."""
        closes = df["close"].to_numpy(dtype=float)
        n = len(closes)
        if n < 2:
            return []
        directions = np.sign(np.diff(closes))  # +1 up, -1 down, 0 flat

        trends: list[TrendInfo] = []
        i = 0
        while i < len(directions):
            d = directions[i]
            if d == 0:
                i += 1
                continue
            j = i
            while j < len(directions) and directions[j] == d:
                j += 1
            duration = j - i + 1  # количество свечей в серии
            if duration >= TREND_MIN_CANDLES:
                start_idx, end_idx = i, j  # свечи [start .. end] включительно
                start_price = closes[start_idx]
                end_price = closes[end_idx]
                change_pct = (end_price - start_price) / start_price * 100.0 if start_price else 0.0
                strength = (
                    "strong" if abs(change_pct) > 0.5
                    else "medium" if abs(change_pct) >= 0.2
                    else "weak"
                )
                trends.append(
                    TrendInfo(
                        start_timestamp=df["timestamp"].iloc[start_idx],
                        end_timestamp=df["timestamp"].iloc[end_idx],
                        duration_candles=duration,
                        price_change_percent=_round(change_pct, 4) or 0.0,
                        direction="up" if d > 0 else "down",
                        strength=strength,
                    )
                )
            i = j
        return trends

    # 2.3.4 свечные паттерны -----------------------------------------------------
    def _detect_patterns(self, df: pd.DataFrame) -> list[CandlePattern]:
        """Engulfing (бычий/медвежий), hammer / inverted hammer, doji."""
        patterns: list[CandlePattern] = []
        for i in range(len(df)):
            o = df["open"].iloc[i]
            h = df["high"].iloc[i]
            l = df["low"].iloc[i]
            c = df["close"].iloc[i]
            rng = h - l
            body = abs(c - o)
            ts = df["timestamp"].iloc[i]

            # --- Doji: тело пренебрежимо мало относительно диапазона (ТЗ: <0.1) ---
            if rng > 0 and body / rng < 0.1:
                confidence = min(1.0, (1.0 - body / rng) * 0.9 + 0.1)
                patterns.append(
                    CandlePattern(
                        timestamp=ts, pattern="doji",
                        confidence=_round(confidence, 2) or 0.0,
                    )
                )
                continue  # doji не совмещаем с прочными паттернами той же свечи

            upper_wick = h - max(o, c)
            lower_wick = min(o, c) - l

            # --- Hammer / Inverted hammer: длинная тень при малом теле ---
            if rng > 0 and body / rng <= 0.35:
                if lower_wick >= 2.0 * body and upper_wick <= body:
                    ratio = lower_wick / rng
                    confidence = min(1.0, 0.5 + ratio)
                    patterns.append(
                        CandlePattern(
                            timestamp=ts, pattern="hammer",
                            confidence=_round(confidence, 2) or 0.0,
                        )
                    )
                    continue
                if upper_wick >= 2.0 * body and lower_wick <= body:
                    ratio = upper_wick / rng
                    confidence = min(1.0, 0.5 + ratio)
                    patterns.append(
                        CandlePattern(
                            timestamp=ts, pattern="inverted_hammer",
                            confidence=_round(confidence, 2) or 0.0,
                        )
                    )
                    continue

            # --- Engulfing: тело текущей свечи полностью перекрывает тело previous ---
            if i > 0:
                prev_o = df["open"].iloc[i - 1]
                prev_c = df["close"].iloc[i - 1]
                prev_body = abs(prev_c - prev_o)
                if body > prev_body and prev_body > 0:
                    if c > o and o <= prev_c and c >= prev_o and prev_c < prev_o:
                        # бычье поглощение: предыдущая медвежья, текущая бычья «съедает»
                        confidence = min(1.0, 0.5 + 0.5 * (body / prev_body - 1.0))
                        patterns.append(
                            CandlePattern(
                                timestamp=ts, pattern="bullish_engulfing",
                                confidence=_round(max(confidence, 0.5), 2) or 0.0,
                            )
                        )
                    elif c < o and o >= prev_c and c <= prev_o and prev_c > prev_o:
                        confidence = min(1.0, 0.5 + 0.5 * (body / prev_body - 1.0))
                        patterns.append(
                            CandlePattern(
                                timestamp=ts, pattern="bearish_engulfing",
                                confidence=_round(max(confidence, 0.5), 2) or 0.0,
                            )
                        )
        return patterns

    # 2.3.5 режим волатильности --------------------------------------------------
    def _volatility_regime(self, ind: pd.DataFrame) -> VolatilityRegime:
        """Текущий ATR против среднего ATR за последние 20 свечей."""
        atr = ind["atr_14"].dropna()
        if atr.empty:
            return VolatilityRegime(regime="normal", ratio=None)
        current_atr = float(atr.iloc[-1])
        window = atr.iloc[-ATR_AVG_LOOKBACK:]
        avg_atr = float(window.mean())
        if avg_atr <= 0:
            return VolatilityRegime(
                current_atr=_round(current_atr, 4), avg_atr_20=_round(avg_atr, 4),
                regime="normal", ratio=None,
            )
        ratio = current_atr / avg_atr
        regime = (
            "high_volatility" if ratio > 1.2
            else "low_volatility" if ratio < 0.8
            else "normal"
        )
        return VolatilityRegime(
            current_atr=_round(current_atr, 4),
            avg_atr_20=_round(avg_atr, 4),
            regime=regime,
            ratio=_round(ratio, 2),
        )

    # 2.3.6 моментум -------------------------------------------------------------
    def _momentum(self, ind: pd.DataFrame) -> MomentumInfo:
        """ROC(12) последней свечи + ускорение (ΔROC м/у последней и предыдущей)."""
        roc = ind["roc_12"]
        valid = roc.dropna()
        if valid.empty:
            return MomentumInfo(current=None, acceleration=None, regime="neutral")
        current = float(roc.iloc[-1]) if not pd.isna(roc.iloc[-1]) else float(valid.iloc[-1])
        prev_value = roc.iloc[-2] if len(roc) >= 2 else float("nan")
        if pd.isna(prev_value):
            return MomentumInfo(current=_round(current, 4), acceleration=None, regime="neutral")
        acceleration = current - float(prev_value)

        if abs(current) < ROC_EPS and abs(acceleration) < ROC_EPS:
            regime = "neutral"
        elif current > 0:
            regime = "bullish_acceleration" if acceleration >= 0 else "bullish_deceleration"
        else:
            regime = "bearish_deceleration" if acceleration >= 0 else "bearish_acceleration"
        return MomentumInfo(
            current=_round(current, 4),
            acceleration=_round(acceleration, 4),
            regime=regime,
        )
