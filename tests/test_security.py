import pytest
from search_scrape.fetchers import validate_url_safe, UrlSafetyError
from search_scrape.url_utils import UrlSafetyPolicy


@pytest.mark.asyncio
async def test_block_localhost():
    with pytest.raises(UrlSafetyError):
        await validate_url_safe("http://localhost:8000/x", UrlSafetyPolicy())


@pytest.mark.asyncio
async def test_block_ip_literal():
    with pytest.raises(UrlSafetyError):
        await validate_url_safe("http://127.0.0.1/x", UrlSafetyPolicy())
