from search_scrape.url_utils import normalize_url


def test_normalize_drops_tracking():
    u = "https://Example.com/path?a=1&utm_source=x&b=2#frag"
    n = normalize_url(u)
    assert n == "https://example.com/path?a=1&b=2"
