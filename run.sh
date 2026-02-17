docker run -d --rm -p 8000:8000 \
  -e GLOBAL_CONCURRENCY=8 \
  -e PER_DOMAIN_CONCURRENCY=2 \
  -e NEG_CACHE_DIR=/app/.negcache \
  -e NEG_CACHE_TTL_S=1800 \
  search-scrape-server
