"""News Orchestrator module."""

from typing import List, Optional
from uuid import uuid4
from datetime import datetime

from src.providers.tinvest.base import TinvestProvider
from src.orchestration.analysis import NewsAnalysis
from src.domain.models import NewsAnalysisItem, NewsItem, NewsAnalysisResult


class NewsOrchestrator:
    """Orchestrates news collection and analysis."""

    def __init__(self, tinvest_provider: TinvestProvider, news_analysis: NewsAnalysis):
        """Initialize news orchestrator.
        
        Args:
            tinvest_provider: T-Invest provider for news data.
            news_analysis: News analysis engine.
        """
        self.tinvest_provider = tinvest_provider
        self.news_analysis = news_analysis

    async def fetch_and_analyze_news(self, limit: int = 10, min_confidence: float = 0.0) -> List[NewsAnalysisResult]:
        """Get news from T-Invest and analyze them.
        
        Args:
            limit: Maximum number of news items to fetch.
            min_confidence: Minimum confidence score threshold for results.
            
        Returns:
            List of analyzed news results.
        """
        # Get raw news data from T-Invest
        raw_news = await self.tinvest_provider.get_news(limit=limit)
        
        if not raw_news:
            return []
        
        analyzed_items = []
        
        # Process each news item
        for news_item in raw_news:
            # Analyze the news
            analysis_result = await self.news_analysis.analyze_news(news_item)
            
            # Filter by confidence if threshold is set
            if analysis_result.scores.confidence_score >= min_confidence:
                analyzed_items.append(analysis_result)
        
        return analyzed_items

    def get_news_and_analyze(self, figi: Optional[str] = None) -> List[NewsAnalysisItem]:
        """Get news from T-Invest and analyze them.
        
        Args:
            figi: Optional FIGI to filter news by instrument.
            
        Returns:
            List of analyzed news items.
        """
        # Get raw news data from T-Invest
        raw_news = self.tinvest_provider.get_news(figi=figi)
        
        if not raw_news:
            return []
        
        analyzed_items = []
        
        # Process each news item
        for news_data in raw_news:
            # Convert raw data to NewsItem domain model
            news_item = self._convert_to_news_item(news_data)
            
            if news_item:
                # Analyze the news
                analysis_result = self.news_analysis.start_analysis(news_item)
                analyzed_items.append(analysis_result)
        
        return analyzed_items

    def _convert_to_news_item(self, news_data: dict) -> Optional[NewsItem]:
        """Convert raw news data to NewsItem domain model.
        
        Args:
            news_data: Raw news data from T-Invest API.
            
        Returns:
            NewsItem instance or None if conversion fails.
        """
        try:
            return NewsItem(
                id=uuid4(),  # Generate unique ID if not provided
                title=news_data.get("title", "No title"),
                body=news_data.get("body", ""),
                source=news_data.get("source", "unknown"),
                published_at=datetime.fromisoformat(news_data["publishedAt"]) if "publishedAt" in news_data else datetime.now(),
                url=news_data.get("url", "")
            )
        except (KeyError, ValueError, TypeError):
            return None
