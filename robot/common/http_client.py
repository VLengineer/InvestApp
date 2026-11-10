"""Базовый HTTP клиент с retry логикой."""
import asyncio
import logging
from typing import Any, Dict, Optional

import httpx

from config import Config

logger = logging.getLogger(__name__)


class HTTPClient:
    """HTTP клиент с retry логикой и обработкой ошибок."""
    
    def __init__(
        self,
        base_url: str = Config.BASE_URL,
        token: str = Config.TINVEST_TOKEN,
        timeout: float = Config.HTTP_TIMEOUT,
        connect_timeout: float = Config.HTTP_CONNECT_TIMEOUT,
        max_retries: int = Config.MAX_RETRIES,
    ):
        self.base_url = base_url
        self.token = token
        self.timeout = httpx.Timeout(timeout, connect=connect_timeout)
        self.max_retries = max_retries
        self._headers = {"Authorization": f"Bearer {token}"}
    
    async def post(
        self,
        endpoint: str,
        payload: Dict[str, Any],
        skip_on_error_code: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Выполняет POST запрос с retry логикой.
        
        Args:
            endpoint: API endpoint (будет добавлен к base_url)
            payload: JSON payload
            skip_on_error_code: Код ошибки, при которой нужно пропустить (вернуть None)
        
        Returns:
            JSON response или None если skip_on_error_code совпал
        """
        url = f"{self.base_url}/{endpoint}"
        
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(verify=False, timeout=self.timeout) as client:
                    resp = await client.post(url, json=payload, headers=self._headers)
                    
                    if resp.status_code == 200:
                        return resp.json()
                    
                    # Проверяем, нужно ли пропустить эту ошибку
                    if skip_on_error_code is not None:
                        try:
                            err_data = resp.json()
                            err_code = err_data.get("code", 0)
                            err_desc = err_data.get("description", "")
                            
                            if err_code == skip_on_error_code:
                                logger.warning(
                                    f"API error {err_code}: {err_desc}. Skipping."
                                )
                                return None
                        except Exception:
                            pass
                    
                    logger.error(f"HTTP {resp.status_code}: {resp.text}")
                    
                    if attempt < self.max_retries - 1:
                        logger.warning(f"Retrying attempt {attempt + 1}...")
                        await asyncio.sleep(2 ** attempt)
                    else:
                        raise Exception(f"API error {resp.status_code}: {resp.text}")
                        
            except (httpx.ConnectTimeout, httpx.ReadTimeout) as e:
                if attempt < self.max_retries - 1:
                    logger.warning(f"Timeout on attempt {attempt + 1}, retrying...")
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        
        return None
