#!/usr/bin/env python3
"""Main entry point for News Market Analyzer.

This script demonstrates the usage of the News Market Analyzer system.
It initializes all required components and runs a sample analysis pipeline.
"""

import os
from pathlib import Path

from src.config.settings import Config
from src.providers.llm.factory import LLMProviderFactory
from src.providers.tinvest.base import TinvestProviderImpl
from src.providers.db.base import SQLiteDatabaseProvider
from src.rag.embedding_gptunnel import GPTunnelEmbedding
from src.rag.vector_db_faiss import FAISSVectorDB
from src.rag.document_db_sqlite import SQLiteDocumentsDB
from src.rag.rag_provider import RAGProvider
from src.orchestration.analysis import NewsAnalysis
from src.orchestration.news_orchestrator import NewsOrchestrator
from src.orchestration.market_orchestrator import NewsMarketOrchestrator


def main():
    """Run the News Market Analyzer pipeline."""
    # Load configuration
    config = Config.from_env()
    
    print(f"🚀 Starting {config.app_name}...")
    print(f"📊 LLM Provider: {config.llm_provider}")
    print(f"📝 Model: {config.llm_default_model}")
    print(f"💾 Database: {config.sqlite_db_path}")
    
    # Ensure data directory exists
    db_path = Path(config.sqlite_db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Initialize LLM provider
    try:
        llm_provider = LLMProviderFactory.create(config)
        print("✅ LLM provider initialized")
    except ValueError as e:
        print(f"❌ Failed to initialize LLM provider: {e}")
        return
    
    # Initialize RAG components
    try:
        embedding = GPTunnelEmbedding(
            api_key=config.llm_api_key,
            api_url=config.llm_api_url.replace("/chat/completions", ""),
        )
        vdb = FAISSVectorDB(embedding_provider=embedding)
        ddb = SQLiteDocumentsDB(db_path=str(db_path.with_suffix(".documents.db")))
        rag_provider = RAGProvider(embedding=embedding, vdb=vdb, ddb=ddb)
        print("✅ RAG provider initialized")
    except Exception as e:
        print(f"⚠️  RAG provider initialization failed (optional): {e}")
        rag_provider = None
    
    # Initialize T-Invest provider
    if config.tinvest_api_key:
        tinvest_provider = TinvestProviderImpl(
            api_key=config.tinvest_api_key,
            sandbox=config.tinvest_sandbox
        )
        print("✅ T-Invest provider initialized")
    else:
        print("⚠️  T-Invest API key not provided - using mock provider")
        # For demonstration, we'll create a minimal mock
        from unittest.mock import Mock
        tinvest_provider = Mock()
        tinvest_provider.get_news.return_value = []
        tinvest_provider.get_timeframe.side_effect = NotImplementedError()
    
    # Initialize database provider
    db_provider = SQLiteDatabaseProvider(db_path=str(db_path))
    print("✅ Database provider initialized")
    
    # Initialize analysis engine
    if rag_provider:
        news_analysis = NewsAnalysis(llm=llm_provider, rag=rag_provider)
    else:
        # Fallback without RAG
        from unittest.mock import Mock
        mock_rag = Mock()
        mock_rag.get_documents.return_value = []
        news_analysis = NewsAnalysis(llm=llm_provider, rag=mock_rag)
    print("✅ News analysis engine initialized")
    
    # Initialize orchestrators
    news_orchestrator = NewsOrchestrator(
        tinvest_provider=tinvest_provider,
        news_analysis=news_analysis
    )
    
    market_orchestrator = NewsMarketOrchestrator(
        news_orchestrator=news_orchestrator,
        tinvest_provider=tinvest_provider,
        db=db_provider
    )
    print("✅ Orchestrators initialized")
    
    print("\n✨ System ready!")
    print("\nTo analyze news:")
    print("  1. Set TINVEST_API_KEY in your .env file")
    print("  2. Call market_orchestrator.execute(figi='FIGI_CODE')")
    print("\nExample:")
    print("  results = market_orchestrator.execute(figi='BBG004730N88')")
    print("  for item in results:")
    print("      print(f'News: {item.news.title}')")
    print("      print(f'Sentiment: {item.impact_scores.market_sentiment}')")
    
    # Close connections
    db_provider.close()
    

if __name__ == "__main__":
    main()
