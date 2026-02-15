from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Dict
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ConcurrencyConfig:
    global_concurrency: int = 6
    per_domain_concurrency: int = 2


class DomainLimiter:
    """
    URLからhostを取り、host単位でSemaphoreを割り当てる。
    ※ eTLD+1 まで正確にやるなら tldextract 等が必要だが、依存を増やさず host で管理。
    """

    def __init__(self, cfg: ConcurrencyConfig) -> None:
        self._cfg = cfg
        self._global = asyncio.Semaphore(cfg.global_concurrency)
        self._by_host: Dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    def _host_key(self, url: str) -> str:
        u = urlsplit(url)
        return (u.hostname or "").lower()

    async def acquire(self, url: str) -> None:
        await self._global.acquire()
        host = self._host_key(url)
        if not host:
            # hostが取れないURLは上位で弾く想定だが、ここではglobalだけ確保済み
            return

        async with self._lock:
            sem = self._by_host.get(host)
            if sem is None:
                sem = asyncio.Semaphore(self._cfg.per_domain_concurrency)
                self._by_host[host] = sem
        await sem.acquire()

    async def release(self, url: str) -> None:
        host = self._host_key(url)
        # hostのsemがないことは基本ないが防御的に
        if host:
            sem = self._by_host.get(host)
            if sem:
                sem.release()
        self._global.release()
