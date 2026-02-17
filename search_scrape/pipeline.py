from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Optional

from .interfaces import (
    SearchEngine,
    HtmlCleaner,
    HtmlToMarkdownConverter,
    DocumentPostProcessor,
)
from .models import MarkdownDocument, SearchQuery
from .url_utils import normalize_url, dedupe_urls

from .concurrency import ConcurrencyConfig, DomainLimiter
from .cache import NegativeCacheStore, NegativeCacheConfig
from .bot_detector import HttpBotDetector, BotDetectionConfig
from .fetchers import HybridFetcher

from logging import getLogger, basicConfig, INFO

basicConfig(format="%(name)s [%(levelname)s]: %(message)s")
logger = getLogger(__name__)


@dataclass(frozen=True)
class PipelineConfig:
    concurrency: ConcurrencyConfig = ConcurrencyConfig(
        global_concurrency=6, per_domain_concurrency=2
    )

    # 200でも “中身が薄い” なら browser 昇格の候補
    min_html_chars_for_browser_escalation: int = 2_000

    # 変換後が短すぎるものは捨てる
    min_markdown_chars: int = 400

    negative_cache: NegativeCacheConfig = NegativeCacheConfig(ttl_seconds=60 * 30)

    bot_detection: BotDetectionConfig = BotDetectionConfig()


class SearchScrapePipeline:
    def __init__(
        self,
        *,
        engine: SearchEngine,
        fetcher: HybridFetcher,  # ← HybridFetcherを前提に（HTTP/Browserを明示的に使う）
        cleaner: HtmlCleaner,
        converter: HtmlToMarkdownConverter,
        config: PipelineConfig = PipelineConfig(),
        post_processor: Optional[DocumentPostProcessor] = None,
    ) -> None:
        self._engine = engine
        self._fetcher = fetcher
        self._cleaner = cleaner
        self._converter = converter
        self._cfg = config
        self._post = post_processor

        self._limiter = DomainLimiter(config.concurrency)
        self._neg_cache = NegativeCacheStore(config.negative_cache)
        self._bot = HttpBotDetector(config.bot_detection)

    async def fetch_one(self, url: str) -> Optional[MarkdownDocument]:
        # 1) negative cache チェック（再アクセスしない）
        if self._neg_cache.get(url) is not None:
            logger.warning(f"negative cache: {url}")
            return None

        await self._limiter.acquire(url)
        try:
            # 2) まずHTTPで取得
            page = await self._fetcher.fetch_http(url)

            # 3) 200以外は negative cache に入れて終了
            if page.status_code != 200:
                logger.warning(f"not200, {page.status_code}: {url}")
                self._neg_cache.put(
                    url, page.status_code, f"non_200:{page.status_code}"
                )
                return None

            # 4) content-typeでHTML以外を除外（テキストのみ）
            ct = (page.content_type or "").lower()
            if "text/html" not in ct:
                logger.warning("content type not text/html")
                self._neg_cache.put(url, page.status_code, f"non_html:{ct}")
                return None

            # 5) bot/challenge判定（HTTP段階）
            bot_reason = self._bot.detect(page)
            if bot_reason is not None:
                logger.warning(f"bot detect: {url}")
                # bot扱いで “しばらく触らない”
                self._neg_cache.put(
                    url,
                    403 if page.status_code == 200 else page.status_code,
                    f"bot:{bot_reason}",
                )
                return None

            # 6) 本文抽出前の “薄いHTML” なら browser昇格（可能なら）
            if len(page.html or "") < self._cfg.min_html_chars_for_browser_escalation:
                try:
                    logger.info(f"run browser: {url}")
                    page2 = await self._fetcher.fetch_browser(url)
                    # browserでも200以外ならキャッシュ
                    if page2.status_code != 200:
                        self._neg_cache.put(
                            url,
                            page2.status_code,
                            f"browser_non_200:{page2.status_code}",
                        )
                        return None
                    ct2 = (page2.content_type or "").lower()
                    if ct2 and "text/html" not in ct2:
                        self._neg_cache.put(
                            url, page2.status_code, f"browser_non_html:{ct2}"
                        )
                        return None
                    # browser結果もbot判定（HTTP段階ルールだがHTML本文は見れる）
                    bot2 = self._bot.detect(page2)
                    if bot2 is not None:
                        self._neg_cache.put(
                            url,
                            403 if page2.status_code == 200 else page2.status_code,
                            f"bot:{bot2}",
                        )
                        return None
                    page = page2
                except Exception as e:
                    logger.error("browser error: {e}")
                    pass

            # 7) 抽出 → markdown
            title, cleaned_html = self._cleaner.clean(page.html)
            if not cleaned_html:
                logger.warning("not cleaned html")
                return None

            md_text = (self._converter.convert(cleaned_html) or "").strip()
            if len(md_text) < self._cfg.min_markdown_chars:
                logger.warning(
                    f"md min chars {len(md_text)} < {self._cfg.min_markdown_chars}"
                )
                return None

            return MarkdownDocument(
                url=page.final_url,
                title=title or page.final_url,
                markdown=md_text,
            )

        except Exception as e:
            # ネットワーク例外なども “しばらく触らない” に入れる運用が多い（要件の意図に沿う）
            # status_codeは擬似的に 0 とする
            logger.error(e)
            self._neg_cache.put(url, 0, f"exception:{type(e).__name__}")
            return None
        finally:
            await self._limiter.release(url)

    async def run(self, query: SearchQuery) -> list[MarkdownDocument]:
        results = await self._engine.search(query)

        urls = [normalize_url(r.url) for r in results]
        urls = [u for u in urls if u.startswith("http")]
        urls = dedupe_urls(urls)

        docs = await asyncio.gather(*[self.fetch_one(u) for u in urls])
        out = [d for d in docs if d is not None]

        if self._post:
            out = await self._post.process(out)

        return out
