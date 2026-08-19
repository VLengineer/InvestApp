#!/usr/bin/env python3
"""Flask API endpoint for news analysis."""

import os
from pathlib import Path
from uuid import uuid4
from datetime import datetime

from flask import Flask, request, jsonify, render_template_string

from src.config.settings import Config
from src.providers.llm.factory import LLMProviderFactory
from src.rag.embedding_gptunnel import GPTunnelEmbedding
from src.rag.vector_db_faiss import FAISSVectorDB
from src.rag.document_db_sqlite import SQLiteDocumentsDB
from src.rag.rag_provider import RAGProvider
from src.orchestration.analysis import NewsAnalysis
from src.domain.models import NewsItem


app = Flask(__name__)

# Initialize components at startup
config = Config.from_env()
llm_provider = None
rag_provider = None
news_analysis = None
initialization_error = None


def initialize_components():
    """Initialize all required components."""
    global llm_provider, rag_provider, news_analysis, initialization_error
    
    try:
        # Initialize LLM provider
        llm_provider = LLMProviderFactory.create(config)
        
        # Initialize RAG components
        db_path = Path(config.sqlite_db_path)
        embedding = GPTunnelEmbedding(
            api_key=config.llm_api_key,
            api_url=config.llm_api_url.replace("/chat/completions", ""),
        )
        vdb = FAISSVectorDB(embedding_provider=embedding)
        ddb = SQLiteDocumentsDB(db_path=str(db_path.with_suffix(".documents.db")))
        rag_provider = RAGProvider(embedding=embedding, vdb=vdb, ddb=ddb)
        
        # Initialize analysis engine
        news_analysis = NewsAnalysis(llm=llm_provider, rag=rag_provider)
        initialization_error = None
        return True
    except Exception as e:
        initialization_error = str(e)
        # Fallback without RAG
        try:
            llm_provider = LLMProviderFactory.create(config)
            from unittest.mock import Mock
            mock_rag = Mock()
            mock_rag.get_documents.return_value = []
            news_analysis = NewsAnalysis(llm=llm_provider, rag=mock_rag)
            initialization_error = f"RAG initialization failed: {e}. Running without RAG."
            return True
        except Exception as e2:
            initialization_error = f"Failed to initialize: {e2}"
            return False


# HTML template for the upload page
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Анализ новостей</title>
    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 900px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 2em;
            margin-bottom: 10px;
        }
        
        .header p {
            opacity: 0.9;
            font-size: 1.1em;
        }
        
        .form-section {
            padding: 40px;
        }
        
        .form-group {
            margin-bottom: 25px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 600;
            color: #333;
            font-size: 1.1em;
        }
        
        input[type="text"],
        textarea {
            width: 100%;
            padding: 15px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
            transition: border-color 0.3s;
        }
        
        input[type="text"]:focus,
        textarea:focus {
            outline: none;
            border-color: #667eea;
        }
        
        textarea {
            min-height: 200px;
            resize: vertical;
            font-family: inherit;
        }
        
        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 40px;
            border: none;
            border-radius: 8px;
            font-size: 1.1em;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            width: 100%;
            font-weight: 600;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 20px rgba(102, 126, 234, 0.4);
        }
        
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        
        .results-section {
            padding: 40px;
            border-top: 2px solid #f0f0f0;
            display: none;
        }
        
        .results-section.show {
            display: block;
        }
        
        .result-card {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 25px;
            margin-bottom: 20px;
        }
        
        .result-card h3 {
            color: #667eea;
            margin-bottom: 15px;
            font-size: 1.3em;
        }
        
        .score-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 15px;
        }
        
        .score-item {
            background: white;
            padding: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }
        
        .score-label {
            font-size: 0.9em;
            color: #666;
            margin-bottom: 5px;
        }
        
        .score-value {
            font-size: 1.5em;
            font-weight: bold;
            color: #333;
        }
        
        .score-value.positive {
            color: #28a745;
        }
        
        .score-value.negative {
            color: #dc3545;
        }
        
        .score-value.neutral {
            color: #6c757d;
        }
        
        .analysis-text {
            line-height: 1.8;
            color: #333;
            white-space: pre-wrap;
        }
        
        .loading {
            text-align: center;
            padding: 40px;
            display: none;
        }
        
        .loading.show {
            display: block;
        }
        
        .spinner {
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 50px;
            height: 50px;
            animation: spin 1s linear infinite;
            margin: 0 auto 20px;
        }
        
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        
        .error-message {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }
        
        .warning-message {
            background: #fff3cd;
            color: #856404;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            border: 1px solid #ffeeba;
        }
        
        .classification-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: 600;
            text-transform: capitalize;
        }
        
        .classification-positive { background: #d4edda; color: #155724; }
        .classification-negative { background: #f8d7da; color: #721c24; }
        .classification-neutral { background: #e2e3e5; color: #383d41; }
        .classification-macroeconomic { background: #d1ecf1; color: #0c5460; }
        .classification-corporate { background: #fff3cd; color: #856404; }
        .classification-regulatory { background: #d6d8db; color: #1b1e21; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Анализ новостей</h1>
            <p>Загрузите новость для получения аналитики и оценок влияния на рынок</p>
        </div>
        
        <div class="form-section">
            {% if error %}
            <div class="error-message">
                <strong>Ошибка:</strong> {{ error }}
            </div>
            {% endif %}
            
            {% if warning %}
            <div class="warning-message">
                <strong>Внимание:</strong> {{ warning }}
            </div>
            {% endif %}
            
            <form id="analysisForm">
                <div class="form-group">
                    <label for="title">Заголовок новости *</label>
                    <input type="text" id="title" name="title" required placeholder="Введите заголовок новости">
                </div>
                
                <div class="form-group">
                    <label for="body">Текст новости *</label>
                    <textarea id="body" name="body" required placeholder="Введите полный текст новости"></textarea>
                </div>
                
                <button type="submit" class="btn" id="submitBtn">
                    🚀 Запустить анализ
                </button>
            </form>
        </div>
        
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Выполняется анализ новости...</p>
            <p style="color: #666; font-size: 0.9em; margin-top: 10px;">Это может занять несколько секунд</p>
        </div>
        
        <div class="results-section" id="results">
            <div class="result-card">
                <h3>📋 Классификация</h3>
                <span class="classification-badge" id="classification"></span>
            </div>
            
            <div class="result-card">
                <h3>📈 Оценки влияния</h3>
                <div class="score-grid">
                    <div class="score-item">
                        <div class="score-label">Сентимент рынка</div>
                        <div class="score-value" id="market_sentiment"></div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Влияние на волатильность</div>
                        <div class="score-value" id="volatility_impact"></div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Влияние на объём</div>
                        <div class="score-value" id="volume_impact"></div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Влияние на сектор</div>
                        <div class="score-value" id="sector_impact"></div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Краткосрочный эффект</div>
                        <div class="score-value" id="short_term_effect"></div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Среднесрочный эффект</div>
                        <div class="score-value" id="medium_term_effect"></div>
                    </div>
                    <div class="score-item">
                        <div class="score-label">Уверенность анализа</div>
                        <div class="score-value" id="confidence_score"></div>
                    </div>
                </div>
            </div>
            
            <div class="result-card">
                <h3>📝 Аналитический отчёт</h3>
                <div class="analysis-text" id="analytics"></div>
            </div>
        </div>
    </div>
    
    <script>
        document.getElementById('analysisForm').addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const title = document.getElementById('title').value;
            const body = document.getElementById('body').value;
            
            // Show loading
            document.getElementById('loading').classList.add('show');
            document.getElementById('results').classList.remove('show');
            document.getElementById('submitBtn').disabled = true;
            
            try {
                const response = await fetch('/api/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ title, body })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    // Update results
                    document.getElementById('classification').textContent = translateClassification(data.classification);
                    document.getElementById('classification').className = 'classification-badge classification-' + data.classification;
                    
                    document.getElementById('market_sentiment').textContent = formatScore(data.impact_scores.market_sentiment);
                    document.getElementById('market_sentiment').className = 'score-value ' + getSentimentClass(data.impact_scores.market_sentiment);
                    
                    document.getElementById('volatility_impact').textContent = formatScore(data.impact_scores.volatility_impact);
                    document.getElementById('volume_impact').textContent = formatScore(data.impact_scores.volume_impact);
                    document.getElementById('sector_impact').textContent = formatScore(data.impact_scores.sector_impact);
                    document.getElementById('sector_impact').className = 'score-value ' + getSentimentClass(data.impact_scores.sector_impact);
                    
                    document.getElementById('short_term_effect').textContent = formatScore(data.impact_scores.short_term_effect);
                    document.getElementById('short_term_effect').className = 'score-value ' + getSentimentClass(data.impact_scores.short_term_effect);
                    
                    document.getElementById('medium_term_effect').textContent = formatScore(data.impact_scores.medium_term_effect);
                    document.getElementById('medium_term_effect').className = 'score-value ' + getSentimentClass(data.impact_scores.medium_term_effect);
                    
                    document.getElementById('confidence_score').textContent = formatScore(data.impact_scores.confidence_score);
                    
                    document.getElementById('analytics').textContent = data.analytics;
                    
                    document.getElementById('results').classList.add('show');
                } else {
                    alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
                }
            } catch (error) {
                alert('Ошибка подключения: ' + error.message);
            } finally {
                document.getElementById('loading').classList.remove('show');
                document.getElementById('submitBtn').disabled = false;
            }
        });
        
        function formatScore(value) {
            return value.toFixed(2);
        }
        
        function getSentimentClass(value) {
            if (value > 0.3) return 'positive';
            if (value < -0.3) return 'negative';
            return 'neutral';
        }
        
        function translateClassification(classification) {
            const translations = {
                'positive': 'позитивная',
                'negative': 'негативная',
                'neutral': 'нейтральная',
                'macroeconomic': 'макроэкономическая',
                'corporate': 'корпоративная',
                'regulatory': 'регуляторная'
            };
            return translations[classification] || classification;
        }
    </script>
</body>
</html>
"""


@app.route('/')
def index():
    """Render the main page."""
    return render_template_string(
        HTML_TEMPLATE, 
        error=initialization_error if initialization_error else None,
        warning=None
    )


@app.route('/api/analyze', methods=['POST'])
def analyze_news():
    """Analyze news endpoint."""
    if news_analysis is None:
        return jsonify({'error': 'Сервис не инициализирован'}), 500
    
    try:
        data = request.get_json()
        
        if not data or 'title' not in data or 'body' not in data:
            return jsonify({'error': 'Необходимо указать заголовок и текст новости'}), 400
        
        # Create NewsItem
        news_item = NewsItem(
            id=uuid4(),
            title=data['title'],
            body=data['body'],
            source="User Upload",
            published_at=datetime.now(),
            url=""
        )
        
        # Run analysis
        result = news_analysis.start_analysis(news_item)
        
        # Return results
        return jsonify({
            'classification': result.classification,
            'analytics': result.analytics,
            'impact_scores': result.impact_scores.to_dict()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    # Initialize components before starting
    initialize_components()
    
    # Run Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)
