"""
Тесты для модуля анализа новостей.
Запуск: pytest tests/test_analysis.py -v
"""
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.domain.models import NewsItem, ImpactScores, NewsAnalysisResult


class TestNewsAnalysisEngine:
    """Тесты для движка анализа новостей."""

    @pytest.fixture
    def sample_news(self):
        """Создание тестовой новости."""
        from uuid import uuid4
        from datetime import datetime
        return NewsItem(
            id=uuid4(),
            title="ЦБ повысил ключевую ставку до 16%",
            body="Банк России принял решение повысить ключевую ставку на 2 процентных пункта...",
            source="T-Invest",
            published_at=datetime.now(),
            url="https://example.com/news/1"
        )

    @pytest.fixture
    def mock_llm_provider(self):
        """Создание мок LLM провайдера."""
        mock = AsyncMock()
        
        # Мокирование ответов для разных этапов
        async def mock_generate(prompt, **kwargs):
            if "классифицируй новость" in prompt.lower():
                return "macroeconomic, negative"
            elif "сгенерируй поисковые запросы" in prompt.lower():
                return "влияние повышения ставки на рынок\nметодика оценки макроэкономических новостей"
            elif "создай аналитический отчет" in prompt.lower():
                return "Повышение ключевой ставки является негативным фактором для рынка акций..."
            elif "оцени влияние" in prompt.lower() or "impact scores" in prompt.lower():
                return json.dumps({
                    "market_sentiment": -0.7,
                    "volatility_impact": 0.8,
                    "volume_impact": 0.5,
                    "sector_impact": -0.3,
                    "short_term_effect": -0.6,
                    "medium_term_effect": -0.4,
                    "confidence_score": 0.85
                })
            return "Default response"
        
        mock.generate = mock_generate
        return mock

    @pytest.fixture
    def mock_rag_provider(self):
        """Создание мок RAG провайдера."""
        mock = AsyncMock()
        
        async def mock_search(query, top_k=3):
            return [
                {
                    "content": "Методика оценки макроэкономических новостей...",
                    "metadata": {"type": "methodology"}
                }
            ]
        
        mock.search = mock_search
        return mock

    @pytest.mark.asyncio
    async def test_analyze_news_classification(self, sample_news, mock_llm_provider, mock_rag_provider):
        """Тест классификации новости."""
        from src.orchestration.analysis import NewsAnalysisEngine
        
        engine = NewsAnalysisEngine(mock_llm_provider, mock_rag_provider)
        result = await engine.analyze_news(sample_news)
        
        assert result is not None
        assert isinstance(result, NewsAnalysisResult)
        assert result.news == sample_news

    @pytest.mark.asyncio
    async def test_analyze_news_scores(self, sample_news, mock_llm_provider, mock_rag_provider):
        """Тест генерации оценок влияния."""
        from src.orchestration.analysis import NewsAnalysisEngine
        
        engine = NewsAnalysisEngine(mock_llm_provider, mock_rag_provider)
        result = await engine.analyze_news(sample_news)
        
        assert result.scores is not None
        assert isinstance(result.scores, ImpactScores)
        
        # Проверка диапазонов значений
        assert -1.0 <= result.scores.market_sentiment <= 1.0
        assert -1.0 <= result.scores.volatility_impact <= 1.0
        assert -1.0 <= result.scores.volume_impact <= 1.0
        assert -1.0 <= result.scores.sector_impact <= 1.0
        assert -1.0 <= result.scores.short_term_effect <= 1.0
        assert -1.0 <= result.scores.medium_term_effect <= 1.0
        assert 0.0 <= result.scores.confidence_score <= 1.0

    @pytest.mark.asyncio
    async def test_analyze_news_text(self, sample_news, mock_llm_provider, mock_rag_provider):
        """Тест генерации текстового анализа."""
        from src.orchestration.analysis import NewsAnalysisEngine
        
        engine = NewsAnalysisEngine(mock_llm_provider, mock_rag_provider)
        result = await engine.analyze_news(sample_news)
        
        assert result.analysis_text is not None
        assert len(result.analysis_text) > 0
        assert isinstance(result.analysis_text, str)

    @pytest.mark.asyncio
    async def test_rag_context_injection(self, sample_news, mock_llm_provider, mock_rag_provider):
        """Тест использования RAG контекста в анализе."""
        from src.orchestration.analysis import NewsAnalysisEngine
        
        engine = NewsAnalysisEngine(mock_llm_provider, mock_rag_provider)
        await engine.analyze_news(sample_news)
        
        # Проверка что RAG search был вызван
        mock_rag_provider.search.assert_called()

    @pytest.mark.asyncio
    async def test_error_handling_invalid_json(self, sample_news):
        """Тест обработки ошибки при невалидном JSON от LLM."""
        from src.orchestration.analysis import NewsAnalysisEngine
        
        mock_llm = AsyncMock()
        async def mock_generate(prompt, **kwargs):
            if "оцени влияние" in prompt.lower():
                return "invalid json {"  # Невалидный JSON
            return "test response"
        mock_llm.generate = mock_generate
        
        mock_rag = AsyncMock()
        mock_rag.search = AsyncMock(return_value=[])
        
        engine = NewsAnalysisEngine(mock_llm, mock_rag)
        result = await engine.analyze_news(sample_news)
        
        # Должен вернуть дефолтные значения при ошибке парсинга
        assert result.scores is not None
        assert isinstance(result.scores, ImpactScores)

    @pytest.mark.asyncio
    async def test_multiple_news_analysis(self, mock_llm_provider, mock_rag_provider):
        """Тест анализа нескольких новостей."""
        from src.orchestration.analysis import NewsAnalysisEngine
        from uuid import uuid4
        from datetime import datetime
        
        news_items = [
            NewsItem(
                id=uuid4(),
                title=f"Новость {i}",
                body=f"Текст новости {i}",
                source="Test",
                published_at=datetime.now(),
                url=f"https://example.com/news/{i}"
            )
            for i in range(3)
        ]
        
        engine = NewsAnalysisEngine(mock_llm_provider, mock_rag_provider)
        results = await engine.analyze_news_batch(news_items)
        
        assert len(results) == 3
        for result in results:
            assert isinstance(result, NewsAnalysisResult)


class TestImpactScores:
    """Тесты для модели ImpactScores."""

    def test_create_impact_scores(self):
        """Тест создания объекта оценок."""
        scores = ImpactScores(
            market_sentiment=0.5,
            volatility_impact=0.3,
            volume_impact=0.2,
            sector_impact=-0.1,
            short_term_effect=0.4,
            medium_term_effect=0.3,
            confidence_score=0.9
        )
        
        assert scores.market_sentiment == 0.5
        assert scores.volatility_impact == 0.3
        assert scores.confidence_score == 0.9

    def test_default_values(self):
        """Тест значений по умолчанию."""
        scores = ImpactScores()
        
        assert scores.market_sentiment == 0.0
        assert scores.volatility_impact == 0.0
        assert scores.confidence_score == 0.0

    def test_to_dict(self):
        """Тест конвертации в словарь."""
        scores = ImpactScores(market_sentiment=0.5, volatility_impact=0.3)
        scores_dict = scores.to_dict()
        
        assert isinstance(scores_dict, dict)
        assert "market_sentiment" in scores_dict
        assert "volatility_impact" in scores_dict

    def test_validation_ranges(self):
        """Тест проверки диапазонов значений."""
        # Допустимые значения
        scores = ImpactScores(market_sentiment=1.0, volatility_impact=0.5)
        assert scores.market_sentiment == 1.0
        assert scores.volatility_impact == 0.5
        
        # Отрицательные значения для market_sentiment
        scores = ImpactScores(market_sentiment=-1.0)
        assert scores.market_sentiment == -1.0
        
        # Значения за пределами диапазона должны вызвать ValidationError
        import pytest
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            ImpactScores(market_sentiment=1.5)
        
        with pytest.raises(ValidationError):
            ImpactScores(volatility_impact=-0.1)


class TestNewsAnalysisResult:
    """Тесты для результата анализа."""

    def test_create_result(self):
        """Тест создания результата анализа."""
        from uuid import uuid4
        from datetime import datetime
        
        news = NewsItem(
            id=uuid4(),
            title="Test",
            body="Content",
            source="Source",
            published_at=datetime.now(),
            url="https://example.com"
        )
        scores = ImpactScores()
        
        result = NewsAnalysisResult(
            news=news,
            scores=scores,
            analysis_text="Analysis text",
            classification="macroeconomic"
        )
        
        assert result.news == news
        assert result.scores == scores
        assert result.analysis_text == "Analysis text"
        assert result.classification == "macroeconomic"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
