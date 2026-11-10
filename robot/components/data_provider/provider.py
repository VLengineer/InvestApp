"""Провайдер данных из TInvest API."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List

from components.base import BaseComponent
from common.http_client import HTTPClient
from schemas.market_data import (
    Candle,
    IndicatorType,
    MarketSnapshot,
    TechIndicator,
)
from components.data_provider.params import DataProviderParams

logger = logging.getLogger(__name__)


class DataProvider(BaseComponent[DataProviderParams]):
    """Компонент для загрузки данных из TInvest API."""
    
    # Максимальные периоды для разбиения
    CANDLE_MAX_PERIOD = timedelta(days=7)
    INDICATOR_MAX_PERIOD = timedelta(days=30)
    
    # API endpoints
    CANDLES_ENDPOINT = "tinkoff.public.invest.api.contract.v1.MarketDataService/GetCandles"
    INDICATORS_ENDPOINT = "tinkoff.public.invest.api.contract.v1.MarketDataService/GetTechAnalysis"
    
    def __init__(
        self,
        http_client: HTTPClient,
        max_concurrent_requests: int = 5,
    ):
        self.http_client = http_client
        self.semaphore = asyncio.Semaphore(max_concurrent_requests)
    
    async def execute(self, params: DataProviderParams) -> List[MarketSnapshot]:
        """Загружает и собирает данные для ML."""
        logger.info(
            f"Fetching data for {params.instrument_id} "
            f"from {params.from_ts} to {params.to_ts}"
        )
        
        # Формируем задачи
        tasks = [
            self._fetch_candles(
                params.instrument_id,
                params.from_ts,
                params.to_ts,
                params.candle_interval,
            )
        ]
        
        for price_type in params.price_types:
            for ind_type in params.indicator_types:
                tasks.append(
                    self._fetch_indicators(
                        params.instrument_id,
                        params.from_ts,
                        params.to_ts,
                        params.indicators_interval,
                        price_type,
                        params.indicator_length,
                        ind_type,
                    )
                )
        
        # Запускаем все запросы
        results = await asyncio.gather(*tasks)
        
        # Обрабатываем результаты
        candles = results[0]
        
        # Группируем индикаторы
        indicator_data: Dict[str, Dict[str, Dict[str, TechIndicator]]] = {}
        idx = 1
        for price_type in params.price_types:
            indicator_data[price_type] = {}
            for ind_type in params.indicator_types:
                indicator_data[price_type][ind_type.name.lower()] = results[idx]
                idx += 1
        
        # Собираем снимки
        return self._build_snapshots(candles, indicator_data, params)
    
    async def _fetch_candles(
        self,
        instrument_id: str,
        from_ts: str,
        to_ts: str,
        interval: str,
    ) -> Dict[str, Candle]:
        """Загружает свечи с разбиением на периоды."""
        start = self._parse_ts(from_ts)
        end = self._parse_ts(to_ts)
        
        all_candles = {}
        current_start = start
        
        while current_start < end:
            current_end = min(current_start + self.CANDLE_MAX_PERIOD, end)
            
            payload = {
                "instrumentId": instrument_id,
                "from": current_start.isoformat(),
                "to": current_end.isoformat(),
                "interval": interval,
            }
            
            async with self.semaphore:
                data = await self.http_client.post(self.CANDLES_ENDPOINT, payload)
            
            if data:
                for c in data.get("candles", []):
                    all_candles[c["time"]] = Candle(**c)
            
            current_start = current_end
        
        logger.info(f"Loaded {len(all_candles)} candles")
        return all_candles
    
    async def _fetch_indicators(
        self,
        instrument_id: str,
        from_ts: str,
        to_ts: str,
        interval: str,
        price_type: str,
        length: int,
        ind_type: IndicatorType,
    ) -> Dict[str, TechIndicator]:
        """Загружает индикаторы с разбиением на периоды."""
        start = self._parse_ts(from_ts)
        end = self._parse_ts(to_ts)
        
        all_indicators = {}
        current_start = start
        
        while current_start < end:
            current_end = min(current_start + self.INDICATOR_MAX_PERIOD, end)
            
            payload = {
                "indicatorType": ind_type.value,
                "instrumentId": instrument_id,
                "from": current_start.isoformat(),
                "to": current_end.isoformat(),
                "interval": interval,
                "typeOfPrice": price_type,
                "length": length,
            }
            
            # Дополнительные параметры для специфичных индикаторов
            if ind_type == IndicatorType.BB:
                payload["deviation"] = {
                    "deviationMultiplier": {"units": "2", "nano": 0}
                }
            elif ind_type == IndicatorType.MACD:
                payload["smoothing"] = {
                    "fastLength": 12,
                    "slowLength": 26,
                    "signalSmoothing": 9,
                }
            
            async with self.semaphore:
                data = await self.http_client.post(
                    self.INDICATORS_ENDPOINT,
                    payload,
                    skip_on_error_code=13,  # API не поддерживает комбинацию
                )
            
            if data:
                for item in data.get("technicalIndicators", []):
                    all_indicators[item["timestamp"]] = TechIndicator(**item)
            
            current_start = current_end
        
        logger.info(f"Loaded {len(all_indicators)} {ind_type.value} for {price_type}")
        return all_indicators
    
    def _build_snapshots(
        self,
        candles: Dict[str, Candle],
        indicator_data: Dict[str, Dict[str, Dict[str, TechIndicator]]],
        params: DataProviderParams,
    ) -> List[MarketSnapshot]:
        """Собирает MarketSnapshot из свечей и индикаторов."""
        # Все уникальные timestamp
        all_timestamps = set(candles.keys())
        for price_type in params.price_types:
            for ind_dict in indicator_data[price_type].values():
                all_timestamps |= set(ind_dict.keys())
        all_timestamps = sorted(all_timestamps)
        
        # Формируем снимки
        snapshots = []
        for ts in all_timestamps:
            indicators: Dict[str, Dict[str, TechIndicator]] = {}
            for price_type in params.price_types:
                indicators[price_type] = {}
                for ind_type in params.indicator_types:
                    ind_name = ind_type.name.lower()
                    indicators[price_type][ind_name] = indicator_data[price_type][ind_name].get(ts)
            
            snapshot = MarketSnapshot(
                timestamp=ts,
                candle=candles.get(ts),
                indicators=indicators,
            )
            snapshots.append(snapshot)
        
        logger.info(f"Built {len(snapshots)} snapshots")
        return snapshots
    
    @staticmethod
    def _parse_ts(ts_str: str) -> datetime:
        """Парсит ISO timestamp."""
        ts_str = ts_str.replace('Z', '+00:00')
        return datetime.fromisoformat(ts_str)
