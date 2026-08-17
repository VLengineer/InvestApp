"""
Тесты для оркестраторов.
Запуск: pytest tests/test_orchestrators.py -v
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from src.domain.models import NewsItem, ImpactScores, NewsAnalysisResult


class TestNewsOrchestrator:
    """Тесты для NewsOrchestrator."""

    @pytest.fixture
    def mock_tinvest_provider(self):
        """Создание мок T-Invest провайдера."""
        from uuid import uuid4
        
        mock = AsyncMock()
        
        async def mock_get_news(limit=10):
            return [
                NewsItem(
                    id=uuid4(),
                    title=f"Новость {i}",
                    body=f"Текст новости {i}",
                    source="T-Invest",
                    published_at=datetime.now(),
                    url=f"https://example.com/news/{i}"
                )
                for i in range(limit)
            ]
        
        mock.get_news = mock_get_news
        return mock

    @pytest.fixture
    def mock_analysis_engine(self):
        """Создание мок движка анализа."""
        mock = AsyncMock()
        
        async def mock_analyze_news(news_item):
            return NewsAnalysisResult(
                news=news_item,
                scores=ImpactScores(market_sentiment=0.5),
                analysis_text="Аналитический отчёт",
                classification="positive"
            )
        
        mock.analyze_news = mock_analyze_news
        return mock

    @pytest.mark.asyncio
    async def test_fetch_and_analyze_news(self, mock_tinvest_provider, mock_analysis_engine):
        """Тест получения и анализа новостей."""
        from src.orchestration.news_orchestrator import NewsOrchestrator
        
        orchestrator = NewsOrchestrator(
            tinvest_provider=mock_tinvest_provider,
            news_analysis=mock_analysis_engine
        )
        
        results = await orchestrator.fetch_and_analyze_news(limit=5)
        
        assert len(results) == 5
        for result in results:
            assert isinstance(result, NewsAnalysisResult)
        
        # Проверка что методы были вызваны
        assert mock_tinvest_provider.get_news.called
        assert mock_analysis_engine.analyze_news.call_count == 5

    @pytest.mark.asyncio
    async def test_filter_news_by_score(self, mock_tinvest_provider):
        """Тест фильтрации новостей по порогу уверенности."""
        from src.orchestration.news_orchestrator import NewsOrchestrator
        
        # Мокируем анализ с разными confidence_score
        async def mock_analyze_with_confidence(news_item):
            confidence = 0.9 if "1" in news_item.title else 0.3
            return NewsAnalysisResult(
                news=news_item,
                scores=ImpactScores(confidence_score=confidence),
                analysis_text="Test",
                classification="neutral"
            )
        
        mock_analysis_engine = AsyncMock()
        mock_analysis_engine.analyze_news = mock_analyze_with_confidence
        
        orchestrator = NewsOrchestrator(
            tinvest_provider=mock_tinvest_provider,
            news_analysis=mock_analysis_engine
        )
        
        results = await orchestrator.fetch_and_analyze_news(
            limit=5,
            min_confidence=0.5
        )
        
        # Должны остаться только новости с confidence >= 0.5
        for result in results:
            assert result.scores.confidence_score >= 0.5

    @pytest.mark.asyncio
    async def test_error_handling_tinvest_failure(self):
        """Тест обработки ошибки при неудаче T-Invest API."""
        from src.orchestration.news_orchestrator import NewsOrchestrator
        
        mock_tinvest = AsyncMock()
        mock_tinvest.get_news = AsyncMock(side_effect=Exception("API Error"))
        
        mock_analysis = AsyncMock()
        
        orchestrator = NewsOrchestrator(
            tinvest_provider=mock_tinvest,
            news_analysis=mock_analysis
        )
        
        # Должен выбросить исключение или вернуть пустой список
        with pytest.raises(Exception):
            await orchestrator.fetch_and_analyze_news(limit=5)

    @pytest.mark.asyncio
    async def test_empty_news_list(self, mock_tinvest_provider):
        """Тест обработки пустого списка новостей."""
        from src.orchestration.news_orchestrator import NewsOrchestrator
        
        mock_analysis_engine = AsyncMock()
        mock_analysis_engine.analyze_news = AsyncMock(return_value=None)
        
        mock_tinvest_provider.get_news = AsyncMock(return_value=[])
        
        orchestrator = NewsOrchestrator(
            tinvest_provider=mock_tinvest_provider,
            news_analysis=mock_analysis_engine
        )
        
        results = await orchestrator.fetch_and_analyze_news(limit=5)
        
        assert len(results) == 0
        mock_analysis_engine.analyze_news.assert_not_called()


class TestNewsMarketOrchestrator:
    """Тесты для NewsMarketOrchestrator."""

    @pytest.fixture
    def mock_news_orchestrator(self):
        """Создание мок новостного оркестратора."""
        from uuid import uuid4
        
        mock = AsyncMock()
        
        async def mock_fetch_and_analyze(limit=10, **kwargs):
            return [
                NewsAnalysisResult(
                    news=NewsItem(
                        id=uuid4(),
                        title=f"Новость {i}",
                        body=f"Текст {i}",
                        source="T-Invest",
                        published_at=datetime.now(),
                        url=f"https://example.com/news/{i}"
                    ),
                    scores=ImpactScores(market_sentiment=0.3 * i),
                    analysis_text=f"Анализ {i}",
                    classification="neutral"
                )
                for i in range(limit)
            ]
        
        mock.fetch_and_analyze_news = mock_fetch_and_analyze
        return mock

    @pytest.fixture
    def mock_tinvest_provider(self):
        """Создание мок T-Invest провайдера для рыночных данных."""
        mock = AsyncMock()
        
        async def mock_get_timeframe(figi, timeframe, from_date, to_date):
            return [
                {
                    "time": datetime.now(),
                    "open": 100.0 + i,
                    "high": 105.0 + i,
                    "low": 95.0 + i,
                    "close": 102.0 + i,
                    "volume": 1000 * i
                }
                for i in range(10)
            ]
        
        mock.get_timeframe = mock_get_timeframe
        return mock

    @pytest.fixture
    def mock_db_provider(self):
        """Создание мок провайдера БД."""
        mock = AsyncMock()
        
        async def mock_save_result(result):
            return True
        
        mock.save_analysis_result = mock_save_result
        return mock

    @pytest.mark.asyncio
    async def test_analyze_latest_news(self, mock_news_orchestrator, mock_tinvest_provider, mock_db_provider):
        """Тест анализа последних новостей."""
        from src.orchestration.market_orchestrator import NewsMarketOrchestrator
        
        orchestrator = NewsMarketOrchestrator(
            news_orchestrator=mock_news_orchestrator,
            tinvest_provider=mock_tinvest_provider,
            db=mock_db_provider
        )
        
        results = await orchestrator.analyze_latest_news(limit=5)
        
        assert len(results) == 5
        for result in results:
            assert isinstance(result, NewsAnalysisResult)
        
        mock_news_orchestrator.fetch_and_analyze_news.assert_called_once_with(limit=5)

    @pytest.mark.asyncio
    async def test_save_results_to_db(self, mock_news_orchestrator, mock_tinvest_provider, mock_db_provider):
        """Тест сохранения результатов в БД."""
        from src.orchestration.market_orchestrator import NewsMarketOrchestrator
        
        orchestrator = NewsMarketOrchestrator(
            news_orchestrator=mock_news_orchestrator,
            tinvest_provider=mock_tinvest_provider,
            db=mock_db_provider
        )
        
        await orchestrator.analyze_latest_news(limit=3)
        
        # Проверка что save_analysis_result был вызван для каждого результата
        assert mock_db_provider.save_analysis_result.call_count == 3

    @pytest.mark.asyncio
    async def test_correlate_with_market_data(self, mock_news_orchestrator, mock_tinvest_provider, mock_db_provider):
        """Тест корреляции новостей с рыночными данными."""
        from src.orchestration.market_orchestrator import NewsMarketOrchestrator
        
        orchestrator = NewsMarketOrchestrator(
            news_orchestrator=mock_news_orchestrator,
            tinvest_provider=mock_tinvest_provider,
            db=mock_db_provider
        )
        
        # Получаем результаты
        results = await orchestrator.analyze_latest_news(limit=2)
        
        # Проверяем что get_timeframe был вызван для корреляции
        # (если эта логика реализована в market_orchestrator)
        # Это зависит от конкретной реализации

    @pytest.mark.asyncio
    async def test_aggregate_scores(self, mock_news_orchestrator, mock_tinvest_provider, mock_db_provider):
        """Тест агрегации оценок по нескольким новостям."""
        from src.orchestration.market_orchestrator import NewsMarketOrchestrator
        
        orchestrator = NewsMarketOrchestrator(
            news_orchestrator=mock_news_orchestrator,
            tinvest_provider=mock_tinvest_provider,
            db=mock_db_provider
        )
        
        results = await orchestrator.analyze_latest_news(limit=5)
        
        # Проверяем что оценки разные (как замокали)
        sentiments = [r.scores.market_sentiment for r in results]
        assert len(set(sentiments)) > 1  # Должны быть разные значения

    @pytest.mark.asyncio
    async def test_error_propagation(self):
        """Тест распространения ошибок."""
        from src.orchestration.market_orchestrator import NewsMarketOrchestrator
        
        mock_news = AsyncMock()
        mock_news.fetch_and_analyze_news = AsyncMock(side_effect=Exception("Analysis failed"))
        
        mock_tinvest = AsyncMock()
        mock_db = AsyncMock()
        
        orchestrator = NewsMarketOrchestrator(
            news_orchestrator=mock_news,
            tinvest_provider=mock_tinvest,
            db=mock_db
        )
        
        with pytest.raises(Exception):
            await orchestrator.analyze_latest_news(limit=5)


class TestIntegrationScenarios:
    """Интеграционные тесты сценариев использования."""

    @pytest.mark.asyncio
    async def test_full_pipeline_positive_news(self):
        """Тест полного пайплайна для позитивной новости."""
        from src.orchestration.market_orchestrator import NewsMarketOrchestrator
        from uuid import uuid4
        
        # Создаём полные моки
        mock_news_item = NewsItem(
            id=uuid4(),
            title="Компания показала рекордную прибыль",
            body="Квартальная прибыль превзошла ожидания аналитиков...",
            source="T-Invest",
            published_at=datetime.now(),
            url="https://example.com/news/positive"
        )
        
        mock_result = NewsAnalysisResult(
            news=mock_news_item,
            scores=ImpactScores(
                market_sentiment=0.8,
                volatility_impact=0.3,
                volume_impact=0.6,
                sector_impact=0.5,
                short_term_effect=0.7,
                medium_term_effect=0.6,
                confidence_score=0.9
            ),
            analysis_text="Позитивная новость о финансовых результатах...",
            classification="positive"
        )
        
        mock_news_orchestrator = AsyncMock()
        mock_news_orchestrator.fetch_and_analyze_news = AsyncMock(return_value=[mock_result])
        
        orchestrator = NewsMarketOrchestrator(
            news_orchestrator=mock_news_orchestrator,
            tinvest_provider=AsyncMock(),
            db=AsyncMock()
        )
        
        results = await orchestrator.analyze_latest_news(limit=1)
        
        assert len(results) == 1
        assert results[0].scores.market_sentiment > 0.5
        assert results[0].classification == "positive"

    @pytest.mark.asyncio
    async def test_full_pipeline_negative_news(self):
        """Тест полного пайплайна для негативной новости."""
        from src.orchestration.market_orchestrator import NewsMarketOrchestrator
        from uuid import uuid4
        
        mock_result = NewsAnalysisResult(
            news=NewsItem(
                id=uuid4(),
                title="Регулятор ввёл новые ограничения",
                body="Центральный банк объявил о новых ограничительных мерах...",
                source="T-Invest",
                published_at=datetime.now(),
                url="https://example.com/news/negative"
            ),
            scores=ImpactScores(
                market_sentiment=-0.7,
                volatility_impact=0.8,
                volume_impact=0.5,
                sector_impact=-0.6,
                short_term_effect=-0.7,
                medium_term_effect=-0.5,
                confidence_score=0.85
            ),
            analysis_text="Негативная новость о регуляторных изменениях...",
            classification="negative"
        )
        
        mock_news_orchestrator = AsyncMock()
        mock_news_orchestrator.fetch_and_analyze_news = AsyncMock(return_value=[mock_result])
        
        orchestrator = NewsMarketOrchestrator(
            news_orchestrator=mock_news_orchestrator,
            tinvest_provider=AsyncMock(),
            db=AsyncMock()
        )
        
        results = await orchestrator.analyze_latest_news(limit=1)
        
        assert len(results) == 1
        assert results[0].scores.market_sentiment < -0.5
        assert results[0].classification == "negative"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
