from __future__ import annotations
from typing import Sequence
import httpx
from bs4 import BeautifulSoup

from .interfaces import SearchEngine
from .models import SearchQuery, SearchResult, TimeRange
from .url_utils import normalize_url, dedupe_urls

from logging import getLogger, basicConfig, INFO, WARNING, DEBUG

logger = getLogger(__name__)


class DuckDuckGoHtmlSearchEngine(SearchEngine):
    """
    DDG HTMLページをスクレイピング。
    ※DDG側のHTML構造/パラメータは変わり得るので、ここだけ差し替えやすく分離。
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        logger.info("info!")

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        params = {"q": query.q, "kl": query.options.region or "jp-jp"}
        # 期間フィルタ（DDG側がサポートしている場合に限り効く）
        if query.options.time_range != TimeRange.ANY:
            params["df"] = query.options.time_range.value
        # language は検索エンジン依存が強いので、ここでは“将来差し替え前提のオプション”として保持のみ。
        # DDGに確実に効かせる保証はしない（必要ならエンジン別に対応を拡張）。

        r = await self._client.get(
            "https://html.duckduckgo.com/html/",
            params=params,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            },
            timeout=15.0,
        )
        # r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        raw: list[SearchResult] = []
        if not soup:
            logger.warning("soup not found")
            return []

        for i, result in enumerate(soup.select(".result"), start=1):
            title_elem = result.select_one(".result__title")
            if not title_elem:
                continue

            link_elem = title_elem.find("a")
            if not link_elem:
                continue

            title = link_elem.get_text(strip=True)
            url = link_elem.get("href", "")

            # Skip ad results
            if "y.js" in url:
                continue

            # Clean up DuckDuckGo redirect URLs
            if url.startswith("//duckduckgo.com/l/?uddg="):
                url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])

            snippet_elem = result.select_one(".result__snippet")
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""

            published_date = None
            extras_url_div = soup.find("div", class_="result__extras__url")
            if extras_url_div:
                spans = extras_url_div.find_all("span")
                for span in spans:
                    text = span.get_text(strip=True)
                    if "20" in text and "-" in text:
                        published_date = text

            if url and title:
                raw.append(
                    SearchResult(
                        rank=i,
                        title=title,
                        url=url,
                        snippet=snippet,
                        published_date=published_date,
                    )
                )
            if len(raw) >= query.k * 3:
                # 後段で正規化/重複除去で減るので多めに取る
                break

        logger.info(f"Successfully found {len(raw)} raws")
        # 正規化 + 重複除去（検索品質）
        normalized_urls = [normalize_url(x.url) for x in raw if x.url]
        normalized_urls = [u for u in normalized_urls if u.startswith("http")]
        unique_urls = dedupe_urls(normalized_urls)

        # rankを詰め直し（安定）
        url_to_best = {}
        for item in raw:
            nu = normalize_url(item.url)
            if nu in unique_urls and nu not in url_to_best:
                url_to_best[nu] = item

        out: list[SearchResult] = []
        for rank, u in enumerate(unique_urls[: query.k], start=1):
            base = url_to_best.get(u)
            if base:
                out.append(
                    SearchResult(
                        rank=rank, title=base.title, url=u, snippet=base.snippet
                    )
                )
            else:
                out.append(SearchResult(rank=rank, title=u, url=u))

        return out
