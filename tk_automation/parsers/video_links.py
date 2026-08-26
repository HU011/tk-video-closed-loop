from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib.parse import urlparse, urlunparse


TIKTOK_VIDEO_RE = re.compile(
    r"https?://(?:www\.)?tiktok\.com/@[^/\"'\s]+/video/\d+[^\s\"'<)]*",
    flags=re.I,
)


def normalize_video_url(url: str) -> str:
    parsed = urlparse(url.strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


def extract_video_urls_from_text(text: str) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for match in TIKTOK_VIDEO_RE.finditer(text or ""):
        url = normalize_video_url(match.group(0))
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


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

