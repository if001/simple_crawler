import pytest
from search_scrape.pipeline import SearchScrapePipeline
from search_scrape.models import (
    SearchQuery,
    SearchResult,
    SearchOptions,
    MarkdownDocument,
)
from search_scrape.interfaces import (
    SearchEngine,
    PageFetcher,
    HtmlCleaner,
    HtmlToMarkdownConverter,
)


class FakeEngine(SearchEngine):
    async def search(self, query: SearchQuery):
        return [
            SearchResult(1, "a", "https://example.com/x?utm_source=1"),
            SearchResult(2, "b", "https://example.com/x"),
        ]


class FakeFetcher(PageFetcher):
    async def fetch(self, url: str):
        from search_scrape.models import PageFetchResult

        return PageFetchResult(
            url,
            url,
            200,
            "text/html; charset=utf-8",
            "<html><body><main><p>Hello</p></main></body></html>",
        )


class FakeCleaner(HtmlCleaner):
    def clean(self, html: str):
        return ("t", "<main><p>Hello</p></main>")


class FakeConv(HtmlToMarkdownConverter):
    def convert(self, html: str):
        return "Hello"


@pytest.mark.asyncio
async def test_dedupe_urls():
    p = SearchScrapePipeline(
        engine=FakeEngine(),
        fetcher=FakeFetcher(),
        cleaner=FakeCleaner(),
        converter=FakeConv(),
    )
    docs = await p.run(SearchQuery("q", 10, SearchOptions()))
    assert len(docs) == 1
