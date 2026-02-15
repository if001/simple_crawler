from __future__ import annotations
import json
import time
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class NegativeCacheEntry:
    url: str
    status_code: int
    reason: str
    created_at: float
    expires_at: float


@dataclass(frozen=True)
class NegativeCacheConfig:
    dir_path: str = ".scrape_negative_cache"
    ttl_seconds: int = 60 * 30  # 30分（必要なら設定可能）


class NegativeCacheStore:
    """
    URL -> JSONファイル
    - 200以外やbot判定などを「しばらく触らない」ための簡易キャッシュ。
    - “一時的に保持”が目的なので、TTLで自然消滅させる。
    """

    def __init__(self, cfg: NegativeCacheConfig = NegativeCacheConfig()) -> None:
        self._dir = Path(cfg.dir_path)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = cfg.ttl_seconds

    def _key_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self._dir / f"{h}.json"

    def get(self, url: str) -> Optional[NegativeCacheEntry]:
        p = self._key_path(url)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            entry = NegativeCacheEntry(
                url=data["url"],
                status_code=int(data["status_code"]),
                reason=str(data["reason"]),
                created_at=float(data["created_at"]),
                expires_at=float(data["expires_at"]),
            )
            if time.time() >= entry.expires_at:
                # 期限切れなら消して無効化
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
                return None
            return entry
        except Exception:
            # 壊れていたら消す
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
            return None

    def put(self, url: str, status_code: int, reason: str) -> None:
        now = time.time()
        entry = {
            "url": url,
            "status_code": status_code,
            "reason": reason,
            "created_at": now,
            "expires_at": now + self._ttl,
        }
        p = self._key_path(url)
        p.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
