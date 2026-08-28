from __future__ import annotations

import json
import hashlib
import urllib.parse
from dataclasses import dataclass
from typing import Any

from core.db import db
from services.importer import import_video_rows
from tk_automation.parsers.video_links import extract_video_urls_from_text, looks_like_video_url, normalize_video_url


COMPLETED_VALUES = {
    "completed",
    "complete",
    "done",
    "published",
    "posted",
    "success",
    "succeeded",
    "finished",
    "approved",
    "active",
    "publish_success",
    "video_status_published",
    "已完成",
    "已发布",
    "完成",
    "发布成功",
    "成功",
}

VIDEO_URL_FIELDS = (
    "video_url",
    "url",
    "content_url",
    "video_link",
    "videoLink",
    "share_url",
    "shareUrl",
    "item_url",
    "itemUrl",
    "post_url",
    "postUrl",
    "permalink",
    "web_url",
    "webUrl",
)

STATUS_FIELDS = (
    "status",
    "video_status",
    "task_status",
    "publish_status",
    "post_status",
    "state",
    "audit_status",
)

NEGATIVE_STATUS_MARKERS = (
    "draft",
    "pending",
    "processing",
    "publishing",
    "review",
    "reject",
    "rejected",
    "fail",
    "failed",
    "cancel",
    "canceled",
    "cancelled",
    "deleted",
    "expired",
    "unpublish",
    "not_published",
    "not published",
    "草稿",
    "审核",
    "失败",
    "拒绝",
    "取消",
    "删除",
)

USERNAME_FIELDS = ("username", "creator_username", "author_unique_id", "handle", "creator_handle")
TITLE_FIELDS = ("title", "video_title", "desc", "description", "caption")
PRODUCT_FIELDS = ("product_name", "product", "product_title", "goods_name", "item_name")
VIDEO_ID_FIELDS = ("video_id", "videoId", "item_id", "itemId", "aweme_id", "awemeId")
METRIC_FIELD_ALIASES = {
    "duration_seconds": ("duration_seconds", "duration", "duration_sec", "durationSeconds", "video_duration"),
    "views": ("views", "view_count", "viewCount", "play_count", "playCount", "video_views", "vv", "impressions"),
    "likes": ("likes", "like_count", "likeCount", "digg_count", "diggCount"),
    "comments": ("comments", "comment_count", "commentCount"),
    "shares": ("shares", "share_count", "shareCount"),
    "orders": ("orders", "order_count", "orderCount", "product_order_count", "sale_count", "sales"),
    "gmv": ("gmv", "video_gmv", "gross_merchandise_value", "revenue", "sales_amount"),
    "commission_rate": ("commission_rate", "commissionRate", "commission"),
    "cover_path": ("cover_path", "cover_url", "coverUrl", "thumbnail_url", "thumbnailUrl", "poster_url", "posterUrl"),
    "follower_count": ("follower_count", "followerCount", "followers", "fans_count", "fansCount"),
    "sample_received_count": ("sample_received_count", "samples_received", "sampleReceivedCount", "sample_count", "sampleCount"),
    "posted_video_count": ("posted_video_count", "posted_videos_count", "postedVideoCount", "published_video_count"),
    "order_count": ("creator_order_count", "creatorOrderCount", "total_order_count", "totalOrderCount"),
    "creator_gmv": ("creator_gmv", "creatorGmv", "total_gmv", "totalGmv"),
}


@dataclass(frozen=True)
class CompletedVideoLink:
    video_url: str
    account_name: str = "tk_completed"
    username: str = "unknown_creator"
    title: str = ""
    product_name: str = ""
    source: str = "manual"
    raw: dict[str, Any] | None = None

    def to_video_row(self) -> dict[str, Any]:
        raw = self.raw or {}
        row = {
            "account_name": self.account_name,
            "username": self.username,
            "title": self.title or self.video_url,
            "video_url": self.video_url,
            "product_name": self.product_name,
            "platform": "tiktok",
            "collection_status": "completed_video_link",
            "collection_source": self.source,
        }
        for target, aliases in METRIC_FIELD_ALIASES.items():
            value = _first_value(raw, aliases)
            if value not in (None, ""):
                row[target] = value
        return row


class CompletedVideoLinkCollector:
    def collect_text(self, text: str, account_name: str = "tk_completed", source: str = "text") -> list[CompletedVideoLink]:
        return [
            CompletedVideoLink(
                video_url=url,
                account_name=account_name,
                username=_username_from_url(url) or _unknown_username(url),
                source=source,
            )
            for url in extract_video_urls_from_text(text)
        ]

    def collect_api_data(self, data: Any, account_name: str = "tk_completed", source: str = "tk_backend_api") -> list[CompletedVideoLink]:
        rows = self._walk_dicts(data)
        records = self._rows_to_records(rows, account_name=account_name, source=source)
        if records:
            return self._dedupe(records)
        if any(self._looks_like_video_row(row) or self._has_video_url_field(row) for row in rows):
            return []
        try:
            text = json.dumps(data, ensure_ascii=False)
        except TypeError:
            text = str(data)
        records.extend(
            CompletedVideoLink(video_url=url, account_name=account_name, source=source)
            for url in extract_video_urls_from_text(text)
        )
        return self._dedupe(records)

    def import_to_db(self, records: list[CompletedVideoLink]) -> dict[str, int]:
        rows = [record.to_video_row() for record in self._dedupe(records)]
        if not rows:
            return {"imported": 0}
        with db() as conn:
            return import_video_rows(conn, rows)

    def _rows_to_records(self, rows: list[dict[str, Any]], account_name: str, source: str) -> list[CompletedVideoLink]:
        records: list[CompletedVideoLink] = []
        for row in rows:
            if not isinstance(row, dict) or not self._is_completed(row):
                continue
            video_url = self._first_video_url(row)
            if not video_url:
                if not self._looks_like_video_row(row):
                    continue
                urls = extract_video_urls_from_text(json.dumps(row, ensure_ascii=False))
                video_url = urls[0] if urls else ""
            if not video_url:
                continue
            username = _clean_username(_first_text(row, USERNAME_FIELDS)) or _username_from_url(video_url) or _unknown_username(video_url)
            records.append(
                CompletedVideoLink(
                    video_url=video_url,
                    account_name=str(row.get("account_name") or account_name),
                    username=username,
                    title=_first_text(row, TITLE_FIELDS) or video_url,
                    product_name=_first_text(row, PRODUCT_FIELDS),
                    source=source,
                    raw=row,
                )
            )
        return records

    def _is_completed(self, row: dict[str, Any]) -> bool:
        status = ""
        for field in STATUS_FIELDS:
            value = row.get(field)
            if value is not None and str(value).strip():
                status = str(value).strip().lower()
                break
        if any(marker in status for marker in NEGATIVE_STATUS_MARKERS):
            return False
        if not status:
            return bool(self._first_video_url(row) or self._video_id_url(row))
        return status in COMPLETED_VALUES or any(marker in status for marker in ("complete", "posted", "success", "finish", "已完成", "已发布", "发布成功"))

    def _first_video_url(self, row: dict[str, Any]) -> str:
        for field in VIDEO_URL_FIELDS:
            value = row.get(field)
            if value is not None and str(value).strip():
                urls = extract_video_urls_from_text(str(value))
                if urls:
                    return urls[0]
                raw_url = str(value).strip()
                if looks_like_video_url(raw_url):
                    return normalize_video_url(raw_url)
        return self._video_id_url(row)

    def _video_id_url(self, row: dict[str, Any]) -> str:
        video_id = str(_first_value(row, VIDEO_ID_FIELDS) or "").strip()
        username = _clean_username(_first_text(row, USERNAME_FIELDS))
        if not video_id or not video_id.isdigit() or not username:
            return ""
        encoded_username = urllib.parse.quote(username, safe="._-")
        return f"https://www.tiktok.com/@{encoded_username}/video/{video_id}"

    def _looks_like_video_row(self, row: dict[str, Any]) -> bool:
        marker_fields = {
            "account_name",
            "username",
            "creator_username",
            "title",
            "video_title",
            "video_id",
            "item_id",
            "product_name",
            "product",
        }
        return any(field in row for field in STATUS_FIELDS) or any(field in row for field in marker_fields)

    def _has_video_url_field(self, row: dict[str, Any]) -> bool:
        return any(field in row for field in VIDEO_URL_FIELDS)

    def _walk_dicts(self, value: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(value, dict):
            rows.append(value)
            for item in value.values():
                rows.extend(self._walk_dicts(item))
        elif isinstance(value, list):
            for item in value:
                rows.extend(self._walk_dicts(item))
        return rows

    def _dedupe(self, records: list[CompletedVideoLink]) -> list[CompletedVideoLink]:
        seen: set[str] = set()
        result: list[CompletedVideoLink] = []
        for record in records:
            if record.video_url in seen:
                continue
            seen.add(record.video_url)
            result.append(record)
        return result


def _first_text(row: dict[str, Any], aliases: tuple[str, ...]) -> str:
    value = _first_value(row, aliases)
    return str(value).strip() if value not in (None, "") else ""


def _first_value(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    for value in row.values():
        if isinstance(value, dict):
            found = _first_value(value, aliases)
            if found not in (None, ""):
                return found
    return None


def _clean_username(value: str) -> str:
    username = str(value or "").strip()
    if username.startswith("@"):
        username = username[1:]
    if "/" in username:
        username = username.rstrip("/").rsplit("/", 1)[-1]
    return username.strip()


def _username_from_url(url: str) -> str:
    path = urllib.parse.urlparse(str(url)).path
    parts = [part for part in path.split("/") if part]
    for index, part in enumerate(parts):
        if part.startswith("@"):
            return _clean_username(part)
        if part == "@" and index + 1 < len(parts):
            return _clean_username(parts[index + 1])
    return ""


def _unknown_username(video_url: str) -> str:
    digest = hashlib.sha1(video_url.encode("utf-8")).hexdigest()[:10]
    return f"unknown_{digest}"
