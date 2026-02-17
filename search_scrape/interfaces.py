from __future__ import annotations
from typing import Protocol, Sequence
from .models import SearchQuery, SearchResult, PageFetchResult


class SearchEngine(Protocol):
    async def search(self, query: SearchQuery) -> Sequence[SearchResult]: ...


class PageFetcher(Protocol):
    async def fetch(self, url: str) -> PageFetchResult: ...


class HybridPageFetcher(Protocol):
    async def fetch_http(self, url: str) -> PageFetchResult: ...
    async def fetch_browser(self, url: str) -> PageFetchResult: ...


class HtmlCleaner(Protocol):
    def clean(self, html: str) -> tuple[str, str]:
        """return (title, cleaned_html_fragment)"""
        ...


class HtmlToMarkdownConverter(Protocol):
    def convert(self, html: str) -> str: ...


# 将来拡張の差し込み口（embedding重複判定、LLM要約など）
class DocumentPostProcessor(Protocol):
    async def process(
        self, docs: list["MarkdownDocument"]
    ) -> list["MarkdownDocument"]: ...
