from __future__ import annotations
from typing import Sequence
import httpx
from bs4 import BeautifulSoup

from .interfaces import SearchEngine
from .models import SearchQuery, SearchResult, TimeRange
from .url_utils import normalize_url, dedupe_urls


class DuckDuckGoHtmlSearchEngine(SearchEngine):
    """
    DDG HTMLページをスクレイピング。
    ※DDG側のHTML構造/パラメータは変わり得るので、ここだけ差し替えやすく分離。
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        params = {"q": query.q, "kl": query.options.region or "jp-jp"}
        # 期間フィルタ（DDG側がサポートしている場合に限り効く）
        if query.options.time_range != TimeRange.ANY:
            params["df"] = query.options.time_range.value
        # language は検索エンジン依存が強いので、ここでは“将来差し替え前提のオプション”として保持のみ。
        # DDGに確実に効かせる保証はしない（必要ならエンジン別に対応を拡張）。

        r = await self._client.get(
            "https://duckduckgo.com/html/",
            params=params,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15.0,
        )
        r.raise_for_status()

        soup = BeautifulSoup(r.text, "html.parser")
        raw: list[SearchResult] = []

        for i, a in enumerate(soup.select("a.result__a"), start=1):
            url = a.get("href") or ""
            title = a.get_text(strip=True) or ""
            snippet = None
            body = a.find_parent("div", class_="result__body")
            if body:
                sn = body.select_one(".result__snippet")
                if sn:
                    snippet = sn.get_text(" ", strip=True)

            if url and title:
                raw.append(SearchResult(rank=i, title=title, url=url, snippet=snippet))
            if len(raw) >= query.k * 3:
                # 後段で正規化/重複除去で減るので多めに取る
                break

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
