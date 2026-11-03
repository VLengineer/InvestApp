"""backend-frontend — BFF-микросервис (Backend For Frontend) для Vue-дашборда.

Единственная ответственность: отдавать данные таблицы ``market_news_ml_dataset``
фронтенду (REST + WebSocket real-time). Все остальные микросервисы проекта
(python_test, scheduler_service) остаются сервисными (для админа) и не затрагиваются.
"""
