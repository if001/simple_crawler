from __future__ import annotations
import re
from bs4 import BeautifulSoup
from markdownify import markdownify as md

from .interfaces import HtmlCleaner, HtmlToMarkdownConverter


_NOISE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "header",
    "aside",
    # コメント欄っぽいもの
    "[id*='comment']",
    "[class*='comment']",
    # 広告っぽいもの
    "[id*='ad']",
    "[class*='-ad']",
    "[class*='ad-']",
    "[class*='-ad-']",
    "[class*='ads']",
    "[id*='ads']",
    "[class*='banner']",
    "[id*='banner']",
    # cookieバナーっぽいもの
    "[id*='cookie']",
    "[class*='cookie']",
    "[id*='consent']",
    "[class*='consent']",
    "[aria-label*='cookie']",
    "[aria-label*='consent']",
    # UIテキスト/モーダルっぽいもの（過剰に消すと本文も消えるので控えめ）
    "[role='dialog']",
]


def _strip_noise(soup: BeautifulSoup) -> None:
    for sel in _NOISE_SELECTORS:
        for tag in soup.select(sel):
            tag.decompose()


def _remove_images_and_links(soup: BeautifulSoup) -> None:
    # 画像は無視
    for img in soup.select("img, picture, svg, figure"):
        img.decompose()

    # リンクは辿らない → aタグを unwrap してテキストだけ残す
    for a in soup.select("a"):
        a.unwrap()


class SimpleHtmlCleaner(HtmlCleaner):
    """
    “本文抽出”はReadability等に差し替えやすいように、ここに閉じ込める。
    """

    def clean(self, html: str) -> tuple[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""

        _strip_noise(soup)
        _remove_images_and_links(soup)

        main = soup.select_one("article") or soup.select_one("main") or soup.body
        if not main:
            return title, ""

        return title, str(main)


class MarkdownifyConverter(HtmlToMarkdownConverter):
    def convert(self, html: str) -> str:
        # 画像/リンクは前段で除去済み前提
        return md(html, heading_style="ATX")


def normalize_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
