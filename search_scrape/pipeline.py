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
from .models import MarkdownDocument, SearchQuery, ErrorType
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

    async def _fetch_by_browser(self, url: str) -> MarkdownDocument | ErrorType:
        logger.info(f"browser fetch: {url}")
        page = await self._fetcher.fetch_browser(url)
        # browserでも200以外ならキャッシュ
        if page.status_code != 200:
            logger.warning("browser not 200: {page.status_code}")
            self._neg_cache.put(
                url,
                page.status_code,
                f"browser_non_200:{page.status_code}",
            )
            if 400 <= page.status_code < 500:
                return ErrorType(status=page.status_code, message="bad request")
            else:
                return ErrorType(status=500, message="server error")

        ct2 = (page.content_type or "").lower()
        if ct2 and "text/html" not in ct2:
            logger.warning("browser non html")
            self._neg_cache.put(url, page.status_code, f"browser_non_html:{ct2}")
            return ErrorType(status=500, message="negative cache")

        # browser結果もbot判定（HTTP段階ルールだがHTML本文は見れる）
        bot2 = self._bot.detect(page)
        if bot2 is not None:
            logger.warning("browser bot: {bot2}")
            self._neg_cache.put(
                url,
                403 if page.status_code == 200 else page.status_code,
                f"bot:{bot2}",
            )
            return ErrorType(
                status=500,
                message=f"negative cache. may be bot detect. reason: {bot_reason}",
            )
        return page

    async def fetch_one(self, url: str) -> MarkdownDocument | ErrorType:
        # 1) negative cache チェック（再アクセスしない）
        if self._neg_cache.get(url) is not None:
            logger.warning(f"negative cache: {url}")
            return ErrorType(status=500, message="negative cache")

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
                if 400 <= page.status_code < 500:
                    return ErrorType(status=page.status_code, message="bad request")
                else:
                    return ErrorType(status=500, message="server error")

            # 4) content-typeでHTML以外を除外（テキストのみ）
            ct = (page.content_type or "").lower()
            if "text/html" not in ct:
                logger.warning("content type not text/html")
                self._neg_cache.put(url, page.status_code, f"non_html:{ct}")
                return ErrorType(status=500, message="negative cache")

            # 5) bot/challenge判定（HTTP段階）
            bot_reason = self._bot.detect(page)
            if bot_reason is not None:
                logger.warning(f"bot detect: {url}")
                if bot_reason != "challenge_page_200":
                    # bot扱いで “しばらく触らない”
                    self._neg_cache.put(
                        url,
                        403 if page.status_code == 200 else page.status_code,
                        f"bot:{bot_reason}",
                    )
                    return ErrorType(
                        status=500,
                        message=f"negative cache. may be bot detect. reason: {bot_reason}",
                    )

            # 6) 本文抽出前の “薄いHTML” なら browser昇格（可能なら）
            if len(page.html or "") < self._cfg.min_html_chars_for_browser_escalation:
                try:
                    page = await self._fetch_by_browser(url)
                    if isinstance(page, ErrorType):
                        return page
                except Exception as e:
                    logger.error("browser error: {e}")
                    pass

            # 7) 抽出 → markdown
            title, cleaned_html = self._cleaner.clean(page.html)
            if not cleaned_html:
                logger.warning("not cleaned html")
                return ErrorType(status=500, message="extract markdown error")

            logger.info(f"fetch {url}")
            ## browser fetch
            md_text = (self._converter.convert(cleaned_html) or "").strip()
            if len(md_text) < self._cfg.min_markdown_chars:
                logger.warning(
                    f"md min chars {len(md_text)} < {self._cfg.min_markdown_chars}"
                )
                page = await self._fetch_by_browser(url)
                if isinstance(page, ErrorType):
                    return page

                title, cleaned_html = self._cleaner.clean(page.html)
                if not cleaned_html:
                    logger.warning("not cleaned html")
                    return ErrorType(status=500, message="extract markdown error")
                md_text = (self._converter.convert(cleaned_html) or "").strip()

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
            return ErrorType(status=500, message="internal server error")
        finally:
            await self._limiter.release(url)

    async def run(
        self, query: SearchQuery
    ) -> tuple[list[MarkdownDocument], list[ErrorType]]:
        results = await self._engine.search(query)

        urls = [normalize_url(r.url) for r in results]
        urls = [u for u in urls if u.startswith("http")]
        urls = dedupe_urls(urls)

        docs = await asyncio.gather(*[self.fetch_one(u) for u in urls])

        ok_list = []
        error_list = []
        for d in docs:
            if isinstance(d, ErrorType):
                error_list.append(d)
            else:
                if self._post:
                    out = await self._post.process(out)
                else:
                    out = d
                ok_list.append(out)
        return ok_list, error_list
