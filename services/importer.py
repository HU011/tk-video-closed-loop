from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from typing import Any
from urllib.parse import urlparse, urlunparse

from core.db import upsert_account, upsert_creator, upsert_product, utc_now


FIELD_ALIASES = {
    "video_url": ("video_url", "url", "video_link", "videoLink", "share_url", "shareUrl", "post_url", "postUrl", "permalink", "web_url", "webUrl"),
    "original_video_path": ("original_video_path", "local_path", "video_path"),
    "cover_path": ("cover_path", "cover_url", "coverUrl", "thumbnail_url", "thumbnailUrl", "poster_url", "posterUrl"),
    "title": ("title", "video_title", "desc", "description", "caption"),
    "duration_seconds": ("duration_seconds", "duration", "duration_sec", "durationSeconds", "video_duration"),
    "views": ("views", "view_count", "viewCount", "play_count", "playCount", "video_views", "vv", "impressions"),
    "likes": ("likes", "like_count", "likeCount", "digg_count", "diggCount"),
    "comments": ("comments", "comment_count", "commentCount"),
    "shares": ("shares", "share_count", "shareCount"),
    "orders": ("orders", "order_count", "orderCount", "product_order_count", "sale_count", "sales"),
    "gmv": ("gmv", "video_gmv", "gross_merchandise_value", "revenue", "sales_amount"),
    "commission_rate": ("commission_rate", "commissionRate", "commission"),
    "collected_at": ("collected_at", "collect_time", "collectedAt", "created_time", "createdTime"),
}


def _num(value: Any, default: float = 0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def _first(row: dict[str, Any], field: str) -> Any:
    for alias in FIELD_ALIASES.get(field, (field,)):
        if alias in row and row[alias] not in (None, ""):
            return row[alias]
    return None


def _text(row: dict[str, Any], field: str) -> str:
    value = _first(row, field)
    return str(value).strip() if value not in (None, "") else ""


def _video_url(row: dict[str, Any]) -> str:
    raw = _text(row, "video_url")
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if (host == "tiktok.com" or host.endswith(".tiktok.com")) and "/video/" in parsed.path.lower():
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
    return raw


def _creator_username(row: dict[str, Any], video_url: str, original_video_path: str) -> str:
    raw = str(row.get("username") or row.get("creator_username") or "").strip()
    if raw.startswith("@"):
        raw = raw[1:]
    if raw:
        return raw
    parsed = urlparse(video_url)
    for part in parsed.path.split("/"):
        if part.startswith("@") and len(part) > 1:
            return part[1:]
    seed = video_url or original_video_path or "unknown"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"unknown_{digest}"


def parse_csv_text(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.strip()))
    return [dict(row) for row in reader]


def import_video_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    updated = 0
    skipped = 0
    for raw_row in rows:
        row = dict(raw_row)
        account_name = str(row.get("account_name") or row.get("account") or "default").strip() or "default"
        platform = str(row.get("platform") or "tiktok").strip() or "tiktok"
        video_url = _video_url(row)
        original_video_path = _text(row, "original_video_path")
        if not video_url and not original_video_path:
            skipped += 1
            continue
        if not str(row.get("username") or row.get("creator_username") or "").strip():
            row["username"] = _creator_username(row, video_url, original_video_path)
        account_id = upsert_account(
            conn,
            name=account_name,
            handle=str(row.get("account_handle") or "").strip(),
            platform=platform,
        )
        creator_id = upsert_creator(conn, row)
        product_id = upsert_product(conn, row)
        now = utc_now()
        values = {
            "account_id": account_id,
            "creator_id": creator_id,
            "product_id": product_id,
            "platform": platform,
            "video_url": video_url,
            "original_video_path": original_video_path,
            "cover_path": _text(row, "cover_path"),
            "title": _text(row, "title"),
            "duration_seconds": _num(_first(row, "duration_seconds")),
            "views": int(_num(_first(row, "views"))),
            "likes": int(_num(_first(row, "likes"))),
            "comments": int(_num(_first(row, "comments"))),
            "shares": int(_num(_first(row, "shares"))),
            "orders": int(_num(_first(row, "orders"))),
            "gmv": _num(_first(row, "gmv")),
            "commission_rate": _num(_first(row, "commission_rate")),
            "collected_at": _text(row, "collected_at") or now,
            "created_at": now,
            "updated_at": now,
        }
        existing_id = _find_existing_video(conn, platform, video_url, original_video_path)
        if existing_id:
            _update_video(conn, existing_id, values)
            updated += 1
        else:
            _insert_video(conn, values)
            imported += 1
    return {"imported": imported, "updated": updated, "skipped": skipped}


def _find_existing_video(conn: sqlite3.Connection, platform: str, video_url: str, original_video_path: str) -> int | None:
    if video_url:
        row = conn.execute(
            "SELECT id FROM videos WHERE platform=? AND video_url=? LIMIT 1",
            (platform, video_url),
        ).fetchone()
        if row:
            return int(row[0])
    if original_video_path:
        row = conn.execute(
            "SELECT id FROM videos WHERE platform=? AND original_video_path=? LIMIT 1",
            (platform, original_video_path),
        ).fetchone()
        if row:
            return int(row[0])
    return None


def _insert_video(conn: sqlite3.Connection, values: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO videos(
            account_id, creator_id, product_id, platform, video_url, original_video_path,
            cover_path, title, duration_seconds, views, likes, comments, shares, orders,
            gmv, commission_rate, collected_at, created_at, updated_at
        )
        VALUES (
            :account_id, :creator_id, :product_id, :platform, :video_url, :original_video_path,
            :cover_path, :title, :duration_seconds, :views, :likes, :comments, :shares, :orders,
            :gmv, :commission_rate, :collected_at, :created_at, :updated_at
        )
        """,
        values,
    )


def _update_video(conn: sqlite3.Connection, video_id: int, values: dict[str, Any]) -> None:
    conn.execute(
        """
        UPDATE videos
        SET
            account_id=:account_id,
            creator_id=:creator_id,
            product_id=COALESCE(:product_id, product_id),
            original_video_path=COALESCE(NULLIF(:original_video_path, ''), original_video_path),
            cover_path=COALESCE(NULLIF(:cover_path, ''), cover_path),
            title=COALESCE(NULLIF(:title, ''), title),
            duration_seconds=CASE WHEN :duration_seconds > 0 THEN :duration_seconds ELSE duration_seconds END,
            views=MAX(views, :views),
            likes=MAX(likes, :likes),
            comments=MAX(comments, :comments),
            shares=MAX(shares, :shares),
            orders=MAX(orders, :orders),
            gmv=MAX(gmv, :gmv),
            commission_rate=CASE WHEN :commission_rate > 0 THEN :commission_rate ELSE commission_rate END,
            collected_at=COALESCE(NULLIF(:collected_at, ''), collected_at),
            updated_at=:updated_at
        WHERE id=:id
        """,
        {**values, "id": video_id},
    )
