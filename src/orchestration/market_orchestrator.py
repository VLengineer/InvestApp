"""Main Market Orchestrator."""

from typing import List, Optional

from src.orchestration.news_orchestrator import NewsOrchestrator
from src.providers.tinvest.base import TinvestProvider
from src.providers.db.base import DataBaseProvider
from src.domain.models import NewsAnalysisItem, Timeframe


class NewsMarketOrchestrator:
    """Main orchestrator for news market analysis pipeline."""

    def __init__(
        self,
        news_orchestrator: NewsOrchestrator,
        tinvest_provider: TinvestProvider,
        db: DataBaseProvider,
    ):
        """Initialize the market orchestrator.
        
        Args:
            news_orchestrator: News orchestrator instance.
            tinvest_provider: T-Invest provider for market data.
            db: Database provider for persistence.
        """
        self.news_orchestrator = news_orchestrator
        self.tinvest_provider = tinvest_provider
        self.db = db

    def execute(self, figi: Optional[str] = None) -> List[NewsAnalysisItem]:
        """Execute the main orchestration pipeline.
        
        Args:
            figi: Optional FIGI to filter news by instrument.
            
        Returns:
            List of analyzed news items.
        """
        # Step 1: Get and analyze news
        analyzed_items = self.news_orchestrator.get_news_and_analyze(figi=figi)
        
        if not analyzed_items:
            return []
        
        # Step 2: Collect market timeframe data (if figi provided)
        timeframe = None
        if figi:
            try:
                timeframe = self._collect_timeframe(figi)
            except NotImplementedError:
                # T-Invest provider not fully implemented yet
                pass
        
        # Step 3: Save results to database
        if timeframe:
            for item in analyzed_items:
                self._save_result(item, timeframe)
        
        return analyzed_items

    def _collect_timeframe(self, figi: str, days: int = 1) -> Timeframe:
        """Collect market timeframe data.
        
        Args:
            figi: FIGI identifier of the instrument.
            days: Number of days of historical data.
            
        Returns:
            Timeframe object with asset and candles.
        """
        return self.tinvest_provider.get_timeframe(figi=figi, days=days)

    def _save_result(self, item: NewsAnalysisItem, tf: Timeframe) -> bool:
        """Save analysis result to database.
        
        Args:
            item: The news analysis item to save.
            tf: Associated timeframe.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            return self.db.add_in_db(item, tf)
        except Exception:
            return False
