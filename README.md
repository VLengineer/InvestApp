# News Market Analyzer

News market analysis system using T-Invest API, LLM (GPTunnel), and RAG.

## Setup

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

2. Fill in your credentials in `.env`:
   - `TINVEST_API_KEY` - Your T-Invest API key
   - `LLM_API_KEY` - Your GPTunnel API key
   - Other settings as needed

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Project Structure

```
src/
├── __init__.py
├── config/          # Configuration management
│   ├── __init__.py
│   └── settings.py
├── domain/          # Domain models
│   ├── __init__.py
│   └── models.py
├── orchestration/   # Orchestration layer
│   ├── __init__.py
│   ├── analysis.py
│   ├── news_orchestrator.py
│   └── market_orchestrator.py
└── providers/       # External service providers
    ├── __init__.py
    ├── db/          # Database providers (SQLite)
    │   ├── __init__.py
    │   └── base.py
    ├── llm/         # LLM providers
    │   ├── __init__.py
    │   ├── base.py        # Abstract LLMProvider interface
    │   ├── gptunnel.py    # GPTunnel implementation
    │   └── factory.py     # LLM provider factory
    ├── rag/         # RAG provider
    │   ├── __init__.py
    │   └── base.py
    └── tinvest/     # T-Invest provider
        ├── __init__.py
        └── base.py
```

## Usage

### Option 1: Manual initialization

```python
from src.config import config
from src.providers.llm import GPTunnelProvider
from src.providers.db import (
    SQLiteEmbeddingProvider,
    SQLiteVectorDBProvider,
    SQLiteDocumentsDBProvider,
    SQLiteDatabaseProvider,
)
from src.providers.rag import RAGProvider
from src.providers.tinvest import TinvestProviderImpl
from src.orchestration import NewsAnalysis, NewsOrchestrator, NewsMarketOrchestrator

# Initialize providers
llm = GPTunnelProvider(
    api_url=config.llm_api_url,
    api_key=config.llm_api_key,
    default_model=config.llm_default_model,
)

embedding = SQLiteEmbeddingProvider(model_name=config.rag_embedding_model)
vdb = SQLiteVectorDBProvider(db_path=config.sqlite_db_path)
ddb = SQLiteDocumentsDBProvider(db_path=config.sqlite_db_path)
rag = RAGProvider(embedding=embedding, vdb=vdb, ddb=ddb)

tinvest = TinvestProviderImpl(
    api_key=config.tinvest_api_key,
    sandbox=config.tinvest_sandbox,
)

db = SQLiteDatabaseProvider(db_path=config.sqlite_db_path)

# Initialize orchestration
analysis = NewsAnalysis(llm=llm, rag=rag)
news_orchestrator = NewsOrchestrator(tinvest_provider=tinvest, news_analysis=analysis)
market_orchestrator = NewsMarketOrchestrator(
    news_orchestrator=news_orchestrator,
    tinvest_provider=tinvest,
    db=db,
)

# Execute
market_orchestrator.execute()
```

### Option 2: Using LLM Provider Factory (recommended)

```python
from src.config import config
from src.providers.llm import LLMProviderFactory
from src.providers.db import (
    SQLiteEmbeddingProvider,
    SQLiteVectorDBProvider,
    SQLiteDocumentsDBProvider,
    SQLiteDatabaseProvider,
)
from src.providers.rag import RAGProvider
from src.providers.tinvest import TinvestProviderImpl
from src.orchestration import NewsAnalysis, NewsOrchestrator, NewsMarketOrchestrator

# Initialize LLM provider via factory (reads from .env)
llm = LLMProviderFactory.create_provider()

# Initialize other providers
embedding = SQLiteEmbeddingProvider(model_name=config.rag_embedding_model)
vdb = SQLiteVectorDBProvider(db_path=config.sqlite_db_path)
ddb = SQLiteDocumentsDBProvider(db_path=config.sqlite_db_path)
rag = RAGProvider(embedding=embedding, vdb=vdb, ddb=ddb)

tinvest = TinvestProviderImpl(
    api_key=config.tinvest_api_key,
    sandbox=config.tinvest_sandbox,
)

db = SQLiteDatabaseProvider(db_path=config.sqlite_db_path)

# Initialize orchestration
analysis = NewsAnalysis(llm=llm, rag=rag)
news_orchestrator = NewsOrchestrator(tinvest_provider=tinvest, news_analysis=analysis)
market_orchestrator = NewsMarketOrchestrator(
    news_orchestrator=news_orchestrator,
    tinvest_provider=tinvest,
    db=db,
)

# Execute
market_orchestrator.execute()
```

## Configuration

Edit `.env` file to configure the system:

- `LLM_PROVIDER_TYPE` - LLM provider type (`gptunnel`, `ollama`, etc.)
- `LLM_API_KEY` - API key for the selected LLM provider
- `LLM_API_URL` - API endpoint URL (for GPTunnel: `https://gptunnel.ru/v1/chat/completions`)
- `LLM_DEFAULT_MODEL` - Default model name (e.g., `qwen3.8`, `gpt-4o`)
- `TINVEST_API_KEY` - T-Invest API key
- `SQLITE_DB_PATH` - Path to SQLite database
- Other settings as needed
