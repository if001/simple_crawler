import asyncio
import pytest
from search_scrape.concurrency import DomainLimiter, ConcurrencyConfig


@pytest.mark.asyncio
async def test_per_domain_limit():
    limiter = DomainLimiter(
        ConcurrencyConfig(global_concurrency=10, per_domain_concurrency=1)
    )
    url = "https://example.com/a"

    await limiter.acquire(url)

    acquired = False

    async def try_acquire():
        nonlocal acquired
        await limiter.acquire(url)
        acquired = True
        await limiter.release(url)

    t = asyncio.create_task(try_acquire())
    await asyncio.sleep(0.05)
    assert acquired is False  # 2つ目はブロックされている

    await limiter.release(url)
    await asyncio.sleep(0.05)
    assert acquired is True
    await t
