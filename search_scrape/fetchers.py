from __future__ import annotations
import asyncio
import socket
import urllib.parse
import ipaddress
from dataclasses import dataclass
from typing import Optional

import httpx

from .interfaces import HybridPageFetcher, PageFetcher
from .models import PageFetchResult
from .url_utils import (
    UrlSafetyPolicy,
    is_ip_literal,
    is_localhost,
    ip_is_blocked,
    normalize_url,
)
# from .fetchers import validate_url_safe


class UrlSafetyError(RuntimeError):
    pass


async def _resolve_host_ips(
    host: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    # asyncio.getaddrinfo でDNS解決（テストでモックしやすい）
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, None, type=socket.SOCK_STREAM
    )
    ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for fam, _, _, _, sockaddr in infos:
        if fam == socket.AF_INET:
            ips.append(ipaddress.ip_address(sockaddr[0]))
        elif fam == socket.AF_INET6:
            ips.append(ipaddress.ip_address(sockaddr[0]))
    return ips


async def validate_url_safe(url: str, policy: UrlSafetyPolicy) -> None:
    u = urllib.parse.urlsplit(url)
    scheme = (u.scheme or "").lower()
    if scheme not in policy.allowed_schemes:
        raise UrlSafetyError(f"scheme not allowed: {scheme}")

    host = u.hostname or ""
    if not host:
        raise UrlSafetyError("missing host")

    # localhost / IP直打ち拒否
    if is_localhost(host):
        raise UrlSafetyError("localhost is blocked")

    if is_ip_literal(host):
        raise UrlSafetyError("IP literal is blocked")

    # DNS解決後のIPレンジ拒否
    ips = await _resolve_host_ips(host)
    if not ips:
        raise UrlSafetyError("DNS resolution failed")

    for ip in ips:
        if ip_is_blocked(ip, policy):
            raise UrlSafetyError(f"resolved IP is blocked: {ip}")


@dataclass(frozen=True)
class FetchPolicy:
    safety: UrlSafetyPolicy = UrlSafetyPolicy()
    timeout_s: float = 20.0
    # HTML以外は落とす（PDF等を弾く）
    require_html: bool = True
    # “昇格判定”で使う最低文字数（本文抽出前の粗い指標）
    min_html_chars: int = 2_000


class HttpxPageFetcher(PageFetcher):
    def __init__(
        self, client: httpx.AsyncClient, policy: FetchPolicy = FetchPolicy()
    ) -> None:
        self._client = client
        self._policy = policy

    async def fetch(self, url: str) -> PageFetchResult:
        url = normalize_url(url)
        await validate_url_safe(url, self._policy.safety)

        r = await self._client.get(
            url,
            follow_redirects=True,
            timeout=self._policy.timeout_s,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            },
            # max_redirects=self._policy.safety.max_redirects,
        )

        content_type = r.headers.get("content-type")
        html = r.text if isinstance(r.text, str) else ""

        # HTML以外は扱わない（PDF等）→ status_codeはそのまま返し、content-typeで判断できるように
        # ここで例外にせず返して、pipelineで「非HTMLならネガティブキャッシュしてskip」できるようにする
        return PageFetchResult(
            requested_url=url,
            final_url=str(r.url),
            status_code=r.status_code,
            content_type=content_type,
            html=html,
        )


class BrowserPageFetcher(PageFetcher):
    """
    Playwrightでレンダリング後HTMLを取得。
    依存が重いので必要時だけ使う（HybridFetcherから呼ばれる想定）。
    """

    def __init__(self, policy: FetchPolicy = FetchPolicy()) -> None:
        self._policy = policy

    async def fetch(self, url: str) -> PageFetchResult:
        url = normalize_url(url)
        await validate_url_safe(url, self._policy.safety)

        try:
            from playwright.async_api import async_playwright
        except Exception as e:
            raise RuntimeError("playwright is not installed or import failed") from e

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            # 余計なリソースを落とさない（画像/フォント/メディアをブロック）
            await page.route(
                "**/*",
                lambda route, request: asyncio.create_task(
                    route.abort()
                    if request.resource_type in {"image", "media", "font"}
                    else route.continue_()
                ),
            )

            resp = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=int(self._policy.timeout_s * 1000),
            )
            # “本文が出るまで”の待ち（サイトにより要調整）
            try:
                await page.wait_for_selector("main, article, body", timeout=5_000)
            except Exception:
                pass

            html = await page.content()
            final_url = page.url
            status = resp.status if resp else 0
            content_type = None
            if resp:
                try:
                    headers = await resp.all_headers()
                    content_type = headers.get("content-type")
                except Exception:
                    pass

            await context.close()
            await browser.close()

        if (
            self._policy.require_html
            and content_type
            and "text/html" not in content_type
        ):
            raise httpx.HTTPError(f"non-html content-type: {content_type}")

        return PageFetchResult(
            requested_url=url,
            final_url=final_url,
            status_code=status,
            content_type=content_type,
            html=html,
        )


class HybridFetcher(HybridPageFetcher):
    def __init__(
        self,
        http_fetcher: HttpxPageFetcher,
        browser_fetcher: Optional[BrowserPageFetcher] = None,
    ) -> None:
        self._http = http_fetcher
        self._browser = browser_fetcher

    async def fetch_http(self, url: str) -> PageFetchResult:
        return await self._http.fetch(url)

    async def fetch_browser(self, url: str) -> PageFetchResult:
        if not self._browser:
            raise RuntimeError("browser fetcher is not configured")
        return await self._browser.fetch(url)
