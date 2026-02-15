from __future__ import annotations
import ipaddress
import re
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Set, Tuple

DEFAULT_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "spm",
    "yclid",
}

_IP_LITERAL_RE = re.compile(r"^\[?[0-9a-fA-F:.]+\]?$")  # IPv4/IPv6っぽいもの


def is_ip_literal(host: str) -> bool:
    h = host.strip("[]")
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def normalize_url(
    url: str,
    *,
    drop_fragment: bool = True,
    drop_tracking_params: bool = True,
    tracking_params: Set[str] = DEFAULT_TRACKING_PARAMS,
) -> str:
    """
    - スキーム/ホストを小文字化
    - default port除去
    - フラグメント除去
    - tracking params除去
    - クエリのキー順ソート
    """
    u = urllib.parse.urlsplit(url.strip())
    scheme = (u.scheme or "").lower()
    netloc = u.netloc

    # netlocが空で pathに入っているケースへの軽い防御（相対URLを弾く用途）
    if not scheme or not netloc:
        return url.strip()

    host = u.hostname.lower() if u.hostname else ""
    port = u.port
    default_port = (scheme == "http" and port == 80) or (
        scheme == "https" and port == 443
    )
    if port and not default_port:
        netloc = f"{host}:{port}"
    else:
        netloc = host

    path = u.path or "/"
    query = u.query or ""

    if drop_tracking_params and query:
        qsl = urllib.parse.parse_qsl(query, keep_blank_values=True)
        qsl2 = [(k, v) for (k, v) in qsl if k.lower() not in tracking_params]
        qsl2.sort(key=lambda kv: (kv[0], kv[1]))
        query = urllib.parse.urlencode(qsl2, doseq=True)

    fragment = "" if drop_fragment else (u.fragment or "")

    return urllib.parse.urlunsplit((scheme, netloc, path, query, fragment))


def dedupe_urls(urls: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def is_localhost(host: str) -> bool:
    h = host.lower().strip("[]")
    return h in {"localhost", "localhost.localdomain"} or h.endswith(".localhost")


@dataclass(frozen=True)
class UrlSafetyPolicy:
    allowed_schemes: Tuple[str, ...] = ("http", "https")
    max_redirects: int = 5
    block_private_ips: bool = True
    block_link_local: bool = True
    block_loopback: bool = True
    block_multicast: bool = True
    block_reserved: bool = True


def ip_is_blocked(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address, policy: UrlSafetyPolicy
) -> bool:
    if policy.block_loopback and ip.is_loopback:
        return True
    if policy.block_private_ips and ip.is_private:
        return True
    if policy.block_link_local and ip.is_link_local:
        return True
    if policy.block_multicast and ip.is_multicast:
        return True
    if policy.block_reserved and ip.is_reserved:
        return True
    # “unspecified” も実質危険
    if ip.is_unspecified:
        return True
    return False
