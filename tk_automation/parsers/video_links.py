from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse


TIKTOK_VIDEO_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[^/\"'\s]+/video/\d+[^\s\"'<)]*",
    flags=re.I,
)
TIKTOK_SHORT_RE = re.compile(
    r"https?://(?:(?:vt|vm)\.tiktok\.com|(?:www\.)?tiktok\.com/t)/[^\s\"'<)]+",
    flags=re.I,
)
DIRECT_VIDEO_EXTENSIONS = (".mp4", ".mov", ".webm", ".m4v")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
TRAILING_URL_PUNCTUATION = ".,;:!?，。；：！？"


def normalize_video_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if _is_tiktok_host(host):
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    return url.strip()


def extract_video_urls_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for pattern in (TIKTOK_VIDEO_RE, TIKTOK_SHORT_RE):
        for match in pattern.finditer(text or ""):
            url = normalize_video_url(match.group(0).rstrip(TRAILING_URL_PUNCTUATION))
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def looks_like_video_url(url: str) -> bool:
    parsed = urlparse(str(url).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if path.endswith(IMAGE_EXTENSIONS):
        return False
    if _is_tiktok_host(host) and ("/video/" in path or path.startswith("/t/")):
        return True
    if host in {"vt.tiktok.com", "vm.tiktok.com"}:
        return True
    return path.endswith(DIRECT_VIDEO_EXTENSIONS) or "/video/" in path


def _is_tiktok_host(host: str) -> bool:
    return host == "tiktok.com" or host.endswith(".tiktok.com")


def walk_json(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_json(item)


def extract_video_urls_from_json_text(text: str) -> list[str]:
    data = json.loads(text)
    seen: set[str] = set()
    urls: list[str] = []
    for item in walk_json(data):
        if isinstance(item, str):
            for url in extract_video_urls_from_text(item):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls
