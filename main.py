import asyncio
import httpx

from search_scrape.ddg_engine import DuckDuckGoHtmlSearchEngine
from search_scrape.fetchers import (
    FetchPolicy,
    HttpxPageFetcher,
    BrowserPageFetcher,
    HybridFetcher,
)
from search_scrape.extractor import SimpleHtmlCleaner, MarkdownifyConverter
from search_scrape.pipeline import SearchScrapePipeline, PipelineConfig
from search_scrape.concurrency import ConcurrencyConfig
from search_scrape.cache import NegativeCacheConfig
from search_scrape.models import SearchQuery, SearchOptions, TimeRange

from logging import getLogger, basicConfig, INFO, WARNING

basicConfig(level=WARNING, format="[%(levelname)s](%(name)s): %(message)s", force=True)
logger = getLogger("search_scrape.main")
getLogger("search_scrape").setLevel(INFO)


async def main():
    async with httpx.AsyncClient() as client:
        engine = DuckDuckGoHtmlSearchEngine(client)

        policy = FetchPolicy()
        http_fetcher = HttpxPageFetcher(client, policy=policy)
        browser_fetcher = BrowserPageFetcher(policy=policy)  # playwright不要なら None
        fetcher = HybridFetcher(http_fetcher, browser_fetcher)

        cfg = PipelineConfig(
            concurrency=ConcurrencyConfig(
                global_concurrency=8, per_domain_concurrency=2
            ),
            negative_cache=NegativeCacheConfig(dir_path=".negcache", ttl_seconds=1800),
        )

        pipeline = SearchScrapePipeline(
            engine=engine,
            fetcher=fetcher,
            cleaner=SimpleHtmlCleaner(),
            converter=MarkdownifyConverter(),
            config=cfg,
        )

        docs = await pipeline.run(
            SearchQuery(
                q="python httpx async tutorial",
                k=10,
                options=SearchOptions(
                    region="jp-jp", language="ja", time_range=TimeRange.MONTH
                ),
            )
        )

    for d in docs:
        print(d.url, d.title, len(d.markdown))


if __name__ == "__main__":
    asyncio.run(main())
