from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OEmbedResult:
    ok: bool
    data: dict[str, Any]
    error: str = ""


class TikTokOEmbedClient:
    endpoint = "https://www.tiktok.com/oembed"

    def fetch(self, url: str) -> OEmbedResult:
        if not url:
            return OEmbedResult(ok=False, data={}, error="empty url")
        request_url = self.endpoint + "?" + urllib.parse.urlencode({"url": url})
        req = urllib.request.Request(request_url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return OEmbedResult(ok=True, data=data)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            return OEmbedResult(ok=False, data={}, error=str(exc))


def row_from_oembed(url: str, oembed: dict[str, Any], account_name: str = "") -> dict[str, Any]:
    author_url = str(oembed.get("author_url") or "")
    username = ""
    match = re.search(r"/@([^/?#]+)", author_url)
    if match:
        username = match.group(1)
    if not username:
        username = str(oembed.get("author_name") or "unknown_creator")
    return {
        "account_name": account_name or "collected",
        "platform": "tiktok",
        "username": username,
        "nickname": str(oembed.get("author_name") or username),
        "title": str(oembed.get("title") or url),
        "video_url": url,
        "cover_path": str(oembed.get("thumbnail_url") or ""),
        "duration_seconds": 0,
        "views": 0,
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "orders": 0,
        "gmv": 0,
    }

