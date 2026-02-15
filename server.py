from __future__ import annotations

import os
from typing import Optional, List

import httpx
from fastapi import FastAPI
from pydantic import BaseModel, Field

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
from search_scrape.models import SearchQuery, SearchOptions, TimeRange, MarkdownDocument


# -----------------------
# Request / Response
# -----------------------


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=1)
    k: int = Field(5, ge=1, le=50)

    # optional filters
    region: Optional[str] = Field(default="jp-jp", description="DuckDuckGo region (kl)")
    language: Optional[str] = Field(
        default=None, description="Language hint (engine-dependent)"
    )
    time_range: TimeRange = Field(default=TimeRange.ANY, description="any/d/w/m/y")

    # behavior flags
    enable_browser: bool = Field(
        default=True, description="Allow Playwright escalation for JS-required pages"
    )


class DocOut(BaseModel):
    url: str
    title: str
    markdown: str


class SearchResponse(BaseModel):
    query: str
    k: int
    docs: List[DocOut]


# -----------------------
# App + Lifespan
# -----------------------

app = FastAPI(title="search-scrape-server")

# shared singletons
_http_client: httpx.AsyncClient | None = None
_pipeline: SearchScrapePipeline | None = None


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except ValueError:
        return default


@app.on_event("startup")
async def startup() -> None:
    global _http_client, _pipeline

    _http_client = httpx.AsyncClient()

    engine = DuckDuckGoHtmlSearchEngine(_http_client)

    # Fetch policy (safety checks are inside fetchers.py)
    fetch_policy = FetchPolicy(
        timeout_s=float(os.getenv("FETCH_TIMEOUT_S", "20.0")),
        require_html=True,
        min_html_chars=_env_int("MIN_HTML_CHARS", 2000),
    )
    http_fetcher = HttpxPageFetcher(_http_client, policy=fetch_policy)

    # browser fetcher will be selected per-request (enable_browser)
    # pipeline needs HybridFetcher, so we create it with browser fetcher by default;
    # if request disables browser, we will recreate a "no browser" HybridFetcher per request (cheap).
    browser_fetcher = BrowserPageFetcher(policy=fetch_policy)
    hybrid_fetcher = HybridFetcher(http_fetcher, browser_fetcher)

    cfg = PipelineConfig(
        concurrency=ConcurrencyConfig(
            global_concurrency=_env_int("GLOBAL_CONCURRENCY", 8),
            per_domain_concurrency=_env_int("PER_DOMAIN_CONCURRENCY", 2),
        ),
        min_html_chars_for_browser_escalation=_env_int(
            "MIN_HTML_CHARS_FOR_ESCALATION", 2000
        ),
        min_markdown_chars=_env_int("MIN_MARKDOWN_CHARS", 400),
        negative_cache=NegativeCacheConfig(
            dir_path=os.getenv("NEG_CACHE_DIR", ".negcache"),
            ttl_seconds=_env_int("NEG_CACHE_TTL_S", 1800),
        ),
    )

    _pipeline = SearchScrapePipeline(
        engine=engine,
        fetcher=hybrid_fetcher,
        cleaner=SimpleHtmlCleaner(),
        converter=MarkdownifyConverter(),
        config=cfg,
        post_processor=None,  # 将来拡張
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest) -> SearchResponse:
    """
    POST /search
    body: { "q": "...", "k": 5, ... }
    response: docs[].markdown
    """
    assert _pipeline is not None
    assert _http_client is not None

    # リクエストごとに Playwright 昇格をON/OFFできるようにする
    if req.enable_browser:
        pipeline = _pipeline
    else:
        # browserなしの HybridFetcher を作る（http clientは使い回し）
        # ※ pipeline内のnegative cache等は pipelineのインスタンスに紐づくので、
        # ここでは “browserを使わないfetcherだけ差し替え” を簡潔に行うため、
        # 既存pipelineの fetcher を直接差し替えず、別pipelineを都度作る（小規模なら十分）。
        engine = DuckDuckGoHtmlSearchEngine(_http_client)
        fetch_policy = FetchPolicy(
            timeout_s=float(os.getenv("FETCH_TIMEOUT_S", "20.0")),
            require_html=True,
            min_html_chars=_env_int("MIN_HTML_CHARS", 2000),
        )
        http_fetcher = HttpxPageFetcher(_http_client, policy=fetch_policy)
        hybrid_fetcher = HybridFetcher(http_fetcher, browser_fetcher=None)

        pipeline = SearchScrapePipeline(
            engine=engine,
            fetcher=hybrid_fetcher,
            cleaner=SimpleHtmlCleaner(),
            converter=MarkdownifyConverter(),
            config=_pipeline._cfg,  # 既存設定を流用（軽量）
            post_processor=None,
        )

    query = SearchQuery(
        q=req.q,
        k=req.k,
        options=SearchOptions(
            region=req.region,
            language=req.language,
            time_range=req.time_range,
        ),
    )

    docs: list[MarkdownDocument] = await pipeline.run(query)

    return SearchResponse(
        query=req.q,
        k=req.k,
        docs=[DocOut(url=d.url, title=d.title, markdown=d.markdown) for d in docs],
    )
