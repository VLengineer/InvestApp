"""Prompt Builder for News Analysis."""

from typing import List
from src.domain.models import NewsItem


class PromptBuilder:
    """Builder for LLM prompts used in news analysis."""

    def __init__(self):
        """Initialize prompt builder with default templates."""
        # Template for classifying news
        self.classification_template = (
            "Классифицируй следующую новость в одну из категорий:\n"
            "- 'positive': Хорошая новость для рынка\n"
            "- 'negative': Плохая новость для рынка\n"
            "- 'neutral': Без значительного влияния\n"
            "- 'macroeconomic': Относится к экономическим показателям\n"
            "- 'corporate': Новости компании\n"
            "- 'regulatory': Регуляторные или политические изменения\n\n"
            "Заголовок новости: {title}\n"
            "Текст новости: {body}\n\n"
            "Верни ТОЛЬКО название категории одним словом на русском языке."
        )

        # Template for generating RAG queries (methodological focus)
        self.rag_query_template = (
            "На основе следующей новости и её классификации сгенерируй 2-3 поисковых запроса "
            "для нахождения методологической информации о том, как анализировать такие новости.\n"
            "Сфокусируйся на аналитических фреймворках, методологиях и лучших практиках.\n\n"
            "Заголовок новости: {title}\n"
            "Текст новости: {body}\n"
            "Классификация: {classification}\n\n"
            "Верни JSON массив строк запросов. Пример: [\"запрос1\", \"запрос2\"]\n"
            "Верни ТОЛЬКО JSON массив, без дополнительного текста."
        )

        # Template for generating analytics text
        self.analytics_template = (
            "Проанализируй следующую новость используя предоставленную классификацию и методологический контекст.\n\n"
            "Заголовок новости: {title}\n"
            "Текст новости: {body}\n"
            "Классификация: {classification}\n\n"
            "Методологический контекст из исследования:\n"
            "{context_documents}\n\n"
            "Предоставь детальный анализ того, как эта новость может повлиять на рынок. "
            "Рассмотри потенциальное влияние на сентимент, волатильность, объём торгов и показатели сектора. "
            "Основывай свой анализ на методологических принципах из контекста. "
            "Отвечай на русском языке."
        )

        # Template for generating impact scores
        self.impact_scores_template = (
            "На основе новости, её классификации, анализа и методологического контекста "
            "сгенерируй числовые оценки влияния в виде JSON объекта.\n\n"
            "Заголовок новости: {title}\n"
            "Текст новости: {body}\n"
            "Классификация: {classification}\n"
            "Анализ: {analytics}\n\n"
            "Методологический контекст:\n"
            "{context_documents}\n\n"
            "Верни JSON объект со следующими полями:\n"
            "- market_sentiment: float между -1.0 (очень негативно) и 1.0 (очень позитивно)\n"
            "- volatility_impact: float между 0.0 (нет влияния) и 1.0 (высокое влияние)\n"
            "- volume_impact: float между 0.0 (нет влияния) и 1.0 (высокое влияние)\n"
            "- sector_impact: float между -1.0 (негативно для сектора) и 1.0 (позитивно для сектора)\n"
            "- short_term_effect: float между -1.0 (негативный) и 1.0 (позитивный)\n"
            "- medium_term_effect: float между -1.0 (негативный) и 1.0 (позитивный)\n"
            "- confidence_score: float между 0.0 (низкая уверенность) и 1.0 (высокая уверенность)\n\n"
            "Верни ТОЛЬКО JSON объект, без дополнительного текста."
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
