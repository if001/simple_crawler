from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class TimeRange(str, Enum):
    ANY = "any"
    DAY = "d"
    WEEK = "w"
    MONTH = "m"
    YEAR = "y"


@dataclass(frozen=True)
class SearchOptions:
    # “検索品質”のためのフィルタ
    language: Optional[str] = None  # e.g. "ja", "en" (engineごとに解釈が異なる)
    region: Optional[str] = "jp-jp"  # DDGのkl相当
    time_range: TimeRange = TimeRange.ANY


@dataclass(frozen=True)
class SearchQuery:
    q: str
    k: int
    options: SearchOptions = SearchOptions()


@dataclass(frozen=True)
class SearchResult:
    rank: int
    title: str
    url: str
    snippet: Optional[str] = None


@dataclass(frozen=True)
class PageFetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: Optional[str]
    html: str


@dataclass(frozen=True)
class MarkdownDocument:
    url: str
    title: str
    markdown: str
