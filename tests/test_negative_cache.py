import time
from search_scrape.cache import NegativeCacheStore, NegativeCacheConfig


def test_negative_cache_ttl(tmp_path):
    store = NegativeCacheStore(
        NegativeCacheConfig(dir_path=str(tmp_path), ttl_seconds=1)
    )
    url = "https://example.com/x"
    assert store.get(url) is None
    store.put(url, 429, "non_200:429")
    assert store.get(url) is not None
    time.sleep(1.1)
    assert store.get(url) is None
