from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

from .models import PageFetchResult


@dataclass(frozen=True)
class BotDetectionConfig:
    # 403を全部bot扱いにすると誤判定もあるので、本文シグネチャも見る
    treat_403_as_suspect: bool = True


class HttpBotDetector:
    """
    HTTP段階で判定できる範囲だけ（ルールベース）。
    - 429はレート制限でbotとは限らないが、いずれにせよ “触らない” 対象
    - 403は本文シグネチャと組み合わせてbot/ブロック判定
    """

    _PATTERNS = [
        r"checking your browser",
        r"just a moment",
        r"attention required",
        r"cloudflare",
        r"cdn-cgi/challenge",
        r"enable javascript and cookies",
        r"verify you are human",
        r"captcha",
        r"unusual traffic",
        r"access denied",
        r"bot detection",
        r"request blocked",
    ]

    def __init__(self, cfg: BotDetectionConfig = BotDetectionConfig()) -> None:
        self._cfg = cfg
        self._rx = re.compile("|".join(self._PATTERNS), re.IGNORECASE)

    def detect(self, page: PageFetchResult) -> Optional[str]:
        """
        bot/ブロックっぽい場合、理由文字列を返す。問題なければ None。
        """
        sc = page.status_code
        body = page.html or ""
        # 429は“アクセス制限”なので一律で触らない（bot判定というより制限判定）
        if sc == 429:
            return "rate_limited_429"

        if sc in (401, 407):
            return "auth_required"

        if sc == 403 and self._cfg.treat_403_as_suspect:
            if self._rx.search(body):
                return "blocked_or_bot_403_signature"
            # シグネチャがなくても403はかなり怪しいので弱く扱う（運用次第）
            return "blocked_403"

        # 200でも中間ページ（“enable js”など）を返すサイトがある
        if sc == 200 and self._rx.search(body):
            return "challenge_page_200"

        return None
