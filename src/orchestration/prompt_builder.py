"""Prompt Builder for News Analysis."""

from typing import List
from src.domain.models import NewsItem


class PromptBuilder:
    """Builder for LLM prompts used in news analysis."""

    def __init__(self):
        """Initialize prompt builder with default templates."""
        # Template for classifying news
        self.classification_template = (
            "Classify the following news into one of these categories:\n"
            "- 'positive': Good news for the market\n"
            "- 'negative': Bad news for the market\n"
            "- 'neutral': No significant impact\n"
            "- 'macroeconomic': Related to economic indicators\n"
            "- 'corporate': Company-specific news\n"
            "- 'regulatory': Regulatory or policy changes\n\n"
            "News title: {title}\n"
            "News body: {body}\n\n"
            "Return ONLY the category name as a single word."
        )

        # Template for generating RAG queries (methodological focus)
        self.rag_query_template = (
            "Based on the following news and its classification, generate 2-3 search queries "
            "to find methodological information about how to analyze such news.\n"
            "Focus on analytical frameworks, methodologies, and best practices.\n\n"
            "News title: {title}\n"
            "News body: {body}\n"
            "Classification: {classification}\n\n"
            "Return a JSON array of query strings. Example: [\"query1\", \"query2\"]\n"
            "Return ONLY the JSON array, no other text."
        )

        # Template for generating analytics text
        self.analytics_template = (
            "Analyze the following news using the provided classification and methodological context.\n\n"
            "News title: {title}\n"
            "News body: {body}\n"
            "Classification: {classification}\n\n"
            "Methodological context from research:\n"
            "{context_documents}\n\n"
            "Provide a detailed analysis of how this news might affect the market. "
            "Consider potential impacts on sentiment, volatility, trading volume, and sector performance. "
            "Base your analysis on the methodological principles from the context."
        )

        # Template for generating impact scores
        self.impact_scores_template = (
            "Based on the news, its classification, analysis, and methodological context, "
            "generate numerical impact scores as a JSON object.\n\n"
            "News title: {title}\n"
            "News body: {body}\n"
            "Classification: {classification}\n"
            "Analysis: {analytics}\n\n"
            "Methodological context:\n"
            "{context_documents}\n\n"
            "Return a JSON object with these fields:\n"
            "- market_sentiment: float between -1.0 (very negative) and 1.0 (very positive)\n"
            "- volatility_impact: float between 0.0 (no impact) and 1.0 (high impact)\n"
            "- volume_impact: float between 0.0 (no impact) and 1.0 (high impact)\n"
            "- sector_impact: float between -1.0 (negative for sector) and 1.0 (positive for sector)\n"
            "- short_term_effect: float between -1.0 (negative) and 1.0 (positive)\n"
            "- medium_term_effect: float between -1.0 (negative) and 1.0 (positive)\n"
            "- confidence_score: float between 0.0 (low confidence) and 1.0 (high confidence)\n\n"
            "Return ONLY the JSON object, no other text."
        )

    def build_classification_prompt(self, news: NewsItem) -> str:
        """Build prompt for news classification.
        
        Args:
            news: The news item to classify.
            
        Returns:
            Formatted classification prompt.
        """
        return self.classification_template.format(
            title=news.title,
            body=news.body
        )

    def build_rag_query_prompt(
        self, 
        news: NewsItem, 
        classification: str
    ) -> str:
        """Build prompt for generating RAG queries.
        
        Args:
            news: The news item.
            classification: The classification label.
            
        Returns:
            Formatted RAG query generation prompt.
        """
        return self.rag_query_template.format(
            title=news.title,
            body=news.body,
            classification=classification
        )

    def build_analytics_prompt(
        self,
        news: NewsItem,
        classification: str,
        context_documents: List[str]
    ) -> str:
        """Build prompt for generating analytics text.
        
        Args:
            news: The news item.
            classification: The classification label.
            context_documents: List of context documents from RAG.
            
        Returns:
            Formatted analytics generation prompt.
        """
        context_str = "\n\n".join(context_documents) if context_documents else "No additional context available."
        
        return self.analytics_template.format(
            title=news.title,
            body=news.body,
            classification=classification,
            context_documents=context_str
        )

    def build_impact_scores_prompt(
        self,
        news: NewsItem,
        classification: str,
        analytics: str,
        context_documents: List[str]
    ) -> str:
        """Build prompt for generating impact scores.
        
        Args:
            news: The news item.
            classification: The classification label.
            analytics: The analytics text.
            context_documents: List of context documents from RAG.
            
        Returns:
            Formatted impact scores generation prompt.
        """
        context_str = "\n\n".join(context_documents) if context_documents else "No additional context available."
        
        return self.impact_scores_template.format(
            title=news.title,
            body=news.body,
            classification=classification,
            analytics=analytics,
            context_documents=context_str
        )

    def update_classification_template(self, template: str):
        """Update the classification template.
        
        Args:
            template: New template string with {title} and {body} placeholders.
        """
        self.classification_template = template

    def update_rag_query_template(self, template: str):
        """Update the RAG query generation template.
        
        Args:
            template: New template string with {title}, {body}, and {classification} placeholders.
        """
        self.rag_query_template = template

    def update_analytics_template(self, template: str):
        """Update the analytics generation template.
        
        Args:
            template: New template string with {title}, {body}, {classification}, and {context_documents} placeholders.
        """
        self.analytics_template = template

    def update_impact_scores_template(self, template: str):
        """Update the impact scores generation template.
        
        Args:
            template: New template string with {title}, {body}, {classification}, {analytics}, and {context_documents} placeholders.
        """
        self.impact_scores_template = template
