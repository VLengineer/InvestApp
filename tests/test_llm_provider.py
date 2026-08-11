"""
Тесты для проверки LLM провайдеров.
Запуск: pytest tests/test_llm_provider.py -v
Или для быстрого теста без pytest: python tests/test_llm_provider.py
"""
import os
import sys
from pathlib import Path

# Добавляем корень проекта в path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.llm.factory import create_llm_provider
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()


def test_gptunnel_provider_creation():
    """Тест создания провайдера через фабрику"""
    os.environ["LLM_PROVIDER"] = "gptunnel"
    provider = create_llm_provider()
    
    assert provider is not None
    assert provider.__class__.__name__ == "GPTunnelProvider"
    print("✅ Фабрика успешно создала GPTunnelProvider")


def test_gptunnel_provider_generate():
    """Тест реального запроса к GPTunnel"""
    os.environ["LLM_PROVIDER"] = "gptunnel"
    os.environ["LLM_MODEL"] = "qwen3.8"  # Модель из ТЗ
    
    provider = create_llm_provider()
    
    prompt = "Привет! Как тебя зовут? Ответь кратко."
    
    try:
        response = provider.generate(prompt=prompt, model=os.getenv("LLM_MODEL", "qwen3.8"))
        
        assert response is not None
        assert isinstance(response, str)
        assert len(response) > 0
        
        print(f"✅ Успешный ответ от LLM:\n{response}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при вызове LLM: {e}")
        return False


def test_system_prompt():
    """Тест с системным промптом"""
    os.environ["LLM_PROVIDER"] = "gptunnel"
    
    provider = create_llm_provider()
    
    system_prompt = "Ты полезный ассистент по финансовым новостям."
    user_prompt = "Что такое волатильность?"
    
    try:
        response = provider.generate(
            prompt=user_prompt,
            model=os.getenv("LLM_MODEL", "qwen3.8"),
            system_prompt=system_prompt
        )
        
        print(f"✅ Ответ с системным промптом:\n{response}")
        return True
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


if __name__ == "__main__":
    print("=" * 50)
    print("Тестирование LLM Provider (GPTunnel)")
    print("=" * 50)
    
    # Проверка наличия токена
    if not os.getenv("GPTUNNEL_API_KEY"):
        print("⚠️  Предупреждение: GPTUNNEL_API_KEY не найден в .env")
        print("   Добавьте ключ в файл .env для полноценного тестирования")
    else:
        print("✅ API ключ найден")
    
    print("\n1. Тест создания провайдера...")
    test_gptunnel_provider_creation()
    
    print("\n2. Тест генерации ответа...")
    test_gptunnel_provider_generate()
    
    print("\n3. Тест с системным промптом...")
    test_system_prompt()
    
    print("\n" + "=" * 50)
    print("Тестирование завершено")
    print("=" * 50)
