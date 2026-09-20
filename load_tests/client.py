import asyncio
import time
import uuid
from typing import Any, Callable, Coroutine, Optional

import httpx

from load_tests.config import settings


class RequestResult:
    def __init__(
        self,
        status_code: Optional[int],
        latency: float,
        error: Optional[str] = None,
        is_success: bool = False,
    ):
        self.status_code = status_code
        self.latency = latency
        self.error = error
        self.is_success = is_success


class BoundedHttpClient:
    """An HTTP client wrapper that limits concurrency."""

    def __init__(self, concurrency_limit: int):
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.client = httpx.AsyncClient(
            base_url=settings.BASE_URL,
            timeout=httpx.Timeout(settings.DEFAULT_TIMEOUT),
            limits=httpx.Limits(max_connections=concurrency_limit, max_keepalive_connections=concurrency_limit)
        )

    async def close(self):
        await self.client.aclose()

    async def _execute_with_timing(
        self,
        method: str,
        url: str,
        **kwargs
    ) -> RequestResult:
        start_time = time.perf_counter()
        async with self.semaphore:
            try:
                response = await self.client.request(method, url, **kwargs)
                latency = time.perf_counter() - start_time
                is_success = 200 <= response.status_code < 300
                return RequestResult(
                    status_code=response.status_code,
                    latency=latency,
                    is_success=is_success,
                )
            except httpx.TimeoutException:
                latency = time.perf_counter() - start_time
                return RequestResult(status_code=None, latency=latency, error="Timeout")
            except Exception as e:
                latency = time.perf_counter() - start_time
                return RequestResult(status_code=None, latency=latency, error=str(e))

    async def post(
        self,
        url: str,
        token: str,
        json_data: dict[str, Any],
        use_idempotency: bool = False,
    ) -> RequestResult:
        headers = {"Authorization": f"Bearer {token}"}
        if use_idempotency:
            headers["Idempotency-Key"] = str(uuid.uuid4())
            
        return await self._execute_with_timing(
            "POST", url, headers=headers, json=json_data
        )

    async def patch(
        self,
        url: str,
        token: str,
        json_data: dict[str, Any],
    ) -> RequestResult:
        headers = {"Authorization": f"Bearer {token}"}
        return await self._execute_with_timing(
            "PATCH", url, headers=headers, json=json_data
        )

    async def get(
        self,
        url: str,
        token: str,
    ) -> RequestResult:
        headers = {"Authorization": f"Bearer {token}"}
        return await self._execute_with_timing(
            "GET", url, headers=headers
        )
