from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.db import db
from services.importer import import_video_rows
from tk_automation.parsers.video_links import extract_video_urls_from_text


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
        return {
            "account_name": self.account_name,
            "username": self.username,
            "title": self.title or self.video_url,
            "video_url": self.video_url,
            "product_name": self.product_name,
            "platform": "tiktok",
            "collection_status": "completed_video_link",
            "collection_source": self.source,
        }


class CompletedVideoLinkCollector:
    def collect_text(self, text: str, account_name: str = "tk_completed", source: str = "text") -> list[CompletedVideoLink]:
        return [
            CompletedVideoLink(video_url=url, account_name=account_name, source=source)
            for url in extract_video_urls_from_text(text)
        ]

    def collect_api_data(self, data: Any, account_name: str = "tk_completed", source: str = "tk_backend_api") -> list[CompletedVideoLink]:
        rows = self._walk_dicts(data)
        records = self._rows_to_records(rows, account_name=account_name, source=source)
        if records:
            return self._dedupe(records)
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
            records.append(
                CompletedVideoLink(
                    video_url=video_url,
                    account_name=str(row.get("account_name") or account_name),
                    username=str(row.get("username") or row.get("creator_username") or "unknown_creator"),
                    title=str(row.get("title") or row.get("video_title") or video_url),
                    product_name=str(row.get("product_name") or row.get("product") or ""),
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
        if not status:
            return True
        return status in COMPLETED_VALUES or any(
            marker in status
            for marker in ("complete", "publish", "posted", "success", "finish", "已完成", "已发布", "发布成功")
        )

    def _first_video_url(self, row: dict[str, Any]) -> str:
        for field in VIDEO_URL_FIELDS:
            value = row.get(field)
            if value is not None and str(value).strip():
                urls = extract_video_urls_from_text(str(value))
                return urls[0] if urls else str(value).strip()
        return ""

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
