"""News Analysis module."""

import json
import re
from typing import List, Optional

from src.providers.llm.base import LLMProvider
from src.providers.rag.base import RAGProvider
from src.domain.models import NewsItem, NewsAnalysisItem, ImpactScores
from src.orchestration.prompt_builder import PromptBuilder


class NewsAnalysis:
    """News analysis engine using LLM and RAG."""

    def __init__(
        self, 
        llm: LLMProvider, 
        rag: RAGProvider,
        prompt_builder: Optional[PromptBuilder] = None
    ):
        """Initialize news analyzer.
        
        Args:
            llm: LLM provider for text generation.
            rag: RAG provider for context retrieval.
            prompt_builder: Optional custom prompt builder.
        """
        self.llm = llm
        self.rag = rag
        self.prompt_builder = prompt_builder or PromptBuilder()

    async def start_analysis(self, news: NewsItem) -> NewsAnalysisItem:
        """Start analysis of a news item.
        
        Args:
            news: The news item to analyze.
            
        Returns:
            NewsAnalysisItem with classification, analytics, and impact scores.
        """
        # Step 1: Classify the news
        classification = await self._classify(news)
        
        # Step 2: Build RAG queries and get context documents
        rag_queries = await self._build_rag_queries(news, classification)
        context_documents = self.rag.get_documents(rag_queries)
        
        # Step 3: Generate analytics text
        analytics = await self._analyze(news, classification, context_documents)
        
        # Step 4: Generate impact scores
        impact_scores = await self._generate_impact_scores(
            news, classification, analytics, context_documents
        )
        
        return NewsAnalysisItem(
            news=news,
            classification=classification,
            analytics=analytics,
            impact_scores=impact_scores,
            timeframe=None
        )

    async def _classify(self, news: NewsItem) -> str:
        """Classify the news item.
        
        Args:
            news: The news item to classify.
            
        Returns:
            Classification label.
        """
        prompt = self.prompt_builder.build_classification_prompt(news)
        response = self.llm.generate(prompt, model="qwen3.8")
        return response.strip().lower()

    async def _build_rag_queries(
        self, 
        news: NewsItem, 
        classification: str
    ) -> List[str]:
        """Build RAG queries based on news and classification.
        
        Args:
            news: The news item.
            classification: Classification label.
            
        Returns:
            List of query strings for RAG.
        """
        prompt = self.prompt_builder.build_rag_query_prompt(news, classification)
        response = self.llm.generate(prompt, model="qwen3.8")
        
        # Parse JSON array from response
        queries = self._parse_json_array(response)
        return queries if queries else ["market analysis methodology"]

    async def _analyze(
        self, 
        news: NewsItem, 
        classification: str, 
        context_documents: List[str]
    ) -> str:
        """Analyze news with context from RAG documents.
        
        Args:
            news: The news item.
            classification: Classification label.
            context_documents: Context documents from RAG.
            
        Returns:
            Analytics text.
        """
        prompt = self.prompt_builder.build_analytics_prompt(
            news, classification, context_documents
        )
        response = self.llm.generate(prompt, model="qwen3.8")
        return response.strip()

    async def _generate_impact_scores(
        self,
        news: NewsItem,
        classification: str,
        analytics: str,
        context_documents: List[str]
    ) -> ImpactScores:
        """Generate impact scores from news analysis.
        
        Args:
            news: The news item.
            classification: Classification label.
            analytics: Analytics text.
            context_documents: Context documents from RAG.
            
        Returns:
            ImpactScores object with numerical metrics.
        """
        prompt = self.prompt_builder.build_impact_scores_prompt(
            news, classification, analytics, context_documents
        )
        response = self.llm.generate(prompt, model="qwen3.8")
        
        # Parse JSON object from response
        scores_data = self._parse_json_object(response)
        
        if scores_data:
            try:
                return ImpactScores.from_dict(scores_data)
            except (ValueError, TypeError):
                pass
        
        # Return default scores if parsing fails
        return ImpactScores()

    def _parse_json_array(self, text: str) -> List[str]:
        """Parse JSON array from LLM response.
        
        Args:
            text: Raw text response from LLM.
            
        Returns:
            Parsed list of strings, or empty list if parsing fails.
        """
        try:
            # Try to find JSON array in the response
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                json_str = match.group(0)
                return json.loads(json_str)
        except (json.JSONDecodeError, AttributeError):
            pass
        return []

    def _parse_json_object(self, text: str) -> dict:
        """Parse JSON object from LLM response.
        
        Args:
            text: Raw text response from LLM.
            
        Returns:
            Parsed dictionary, or empty dict if parsing fails.
        """
        try:
            # Try to find JSON object in the response
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                json_str = match.group(0)
                return json.loads(json_str)
        except (json.JSONDecodeError, AttributeError):
            pass
        return {}
