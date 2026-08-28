from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from core.paths import ensure_dirs, ensure_under_root
from core.settings import settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _first(data: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = data.get(name)
        if value not in (None, ""):
            return value
    return None


def _number(value: Any, default: float = 0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _connect() -> sqlite3.Connection:
    ensure_dirs()
    db_path = ensure_under_root(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL DEFAULT 'tiktok',
                name TEXT NOT NULL,
                handle TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(platform, name)
            );

            CREATE TABLE IF NOT EXISTS creators (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                nickname TEXT,
                region TEXT,
                category TEXT,
                follower_count INTEGER NOT NULL DEFAULT 0,
                sample_received_count INTEGER NOT NULL DEFAULT 0,
                posted_video_count INTEGER NOT NULL DEFAULT 0,
                order_count INTEGER NOT NULL DEFAULT 0,
                gmv REAL NOT NULL DEFAULT 0,
                free_sample_score REAL NOT NULL DEFAULT 0,
                free_sample_reasons TEXT NOT NULL DEFAULT '[]',
                tags_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sku TEXT,
                image_path TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(name, sku)
            );

            CREATE TABLE IF NOT EXISTS videos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                creator_id INTEGER NOT NULL,
                product_id INTEGER,
                platform TEXT NOT NULL DEFAULT 'tiktok',
                video_url TEXT,
                original_video_path TEXT,
                cover_path TEXT,
                title TEXT,
                duration_seconds REAL NOT NULL DEFAULT 0,
                views INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                comments INTEGER NOT NULL DEFAULT 0,
                shares INTEGER NOT NULL DEFAULT 0,
                orders INTEGER NOT NULL DEFAULT 0,
                gmv REAL NOT NULL DEFAULT 0,
                commission_rate REAL NOT NULL DEFAULT 0,
                hot_score REAL NOT NULL DEFAULT 0,
                hot_reason TEXT NOT NULL DEFAULT '',
                collected_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL,
                FOREIGN KEY(creator_id) REFERENCES creators(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS sample_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id INTEGER NOT NULL UNIQUE,
                score REAL NOT NULL DEFAULT 0,
                reasons TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(creator_id) REFERENCES creators(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS replication_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id INTEGER NOT NULL,
                product_id INTEGER,
                product_image_path TEXT NOT NULL,
                original_video_path TEXT NOT NULL,
                max_duration_seconds INTEGER NOT NULL DEFAULT 60,
                status TEXT NOT NULL DEFAULT 'queued',
                progress REAL NOT NULL DEFAULT 0,
                output_video_path TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS replication_segments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                segment_index INTEGER NOT NULL,
                source_segment_path TEXT,
                prompt TEXT,
                generated_video_path TEXT,
                tail_frame_path TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, segment_index),
                FOREIGN KEY(job_id) REFERENCES replication_jobs(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    for key in ("tags_json", "free_sample_reasons", "reasons"):
        if key in result and isinstance(result[key], str):
            try:
                result[key] = json.loads(result[key])
            except json.JSONDecodeError:
                pass
    return result


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) or {} for row in rows]


def upsert_account(conn: sqlite3.Connection, name: str, handle: str = "", platform: str = "tiktok") -> int:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO accounts(platform, name, handle, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(platform, name) DO UPDATE SET
            handle=excluded.handle,
            updated_at=excluded.updated_at
        """,
        (platform, name.strip() or "default", handle.strip(), now, now),
    )
    return int(conn.execute("SELECT id FROM accounts WHERE platform=? AND name=?", (platform, name.strip() or "default")).fetchone()[0])


def upsert_creator(conn: sqlite3.Connection, data: dict[str, Any]) -> int:
    username = str(data.get("username") or data.get("creator_username") or "").strip()
    if not username:
        raise ValueError("creator username is required")
    now = utc_now()
    values = {
        "username": username,
        "nickname": str(data.get("nickname") or data.get("creator_nickname") or "").strip(),
        "region": str(data.get("region") or "").strip(),
        "category": str(data.get("category") or "").strip(),
        "follower_count": int(_number(_first(data, "follower_count", "followerCount", "followers", "fans_count", "fansCount"))),
        "sample_received_count": int(
            _number(_first(data, "sample_received_count", "samples_received", "sampleReceivedCount", "sample_count", "sampleCount"))
        ),
        "posted_video_count": int(
            _number(_first(data, "posted_video_count", "posted_videos_count", "postedVideoCount", "published_video_count"))
        ),
        "order_count": int(_number(_first(data, "creator_order_count", "creatorOrderCount", "order_count", "orders"))),
        "gmv": _number(_first(data, "creator_gmv", "creatorGmv", "total_gmv", "totalGmv", "gmv")),
        "tags_json": json.dumps(data.get("tags") or [], ensure_ascii=False),
    }
    conn.execute(
        """
        INSERT INTO creators(
            username, nickname, region, category, follower_count, sample_received_count,
            posted_video_count, order_count, gmv, tags_json, created_at, updated_at
        )
        VALUES (:username, :nickname, :region, :category, :follower_count, :sample_received_count,
            :posted_video_count, :order_count, :gmv, :tags_json, :created_at, :updated_at)
        ON CONFLICT(username) DO UPDATE SET
            nickname=COALESCE(NULLIF(excluded.nickname, ''), creators.nickname),
            region=COALESCE(NULLIF(excluded.region, ''), creators.region),
            category=COALESCE(NULLIF(excluded.category, ''), creators.category),
            follower_count=MAX(creators.follower_count, excluded.follower_count),
            sample_received_count=MAX(creators.sample_received_count, excluded.sample_received_count),
            posted_video_count=MAX(creators.posted_video_count, excluded.posted_video_count),
            order_count=MAX(creators.order_count, excluded.order_count),
            gmv=MAX(creators.gmv, excluded.gmv),
            tags_json=CASE WHEN excluded.tags_json != '[]' THEN excluded.tags_json ELSE creators.tags_json END,
            updated_at=excluded.updated_at
        """,
        {**values, "created_at": now, "updated_at": now},
    )
    return int(conn.execute("SELECT id FROM creators WHERE username=?", (username,)).fetchone()[0])


def upsert_product(conn: sqlite3.Connection, data: dict[str, Any]) -> int | None:
    name = str(data.get("product_name") or data.get("name") or "").strip()
    if not name:
        return None
    sku = str(data.get("sku") or data.get("product_sku") or "").strip()
    now = utc_now()
    conn.execute(
        """
        INSERT INTO products(name, sku, image_path, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(name, sku) DO UPDATE SET
            image_path=COALESCE(NULLIF(excluded.image_path, ''), products.image_path),
            notes=COALESCE(NULLIF(excluded.notes, ''), products.notes),
            updated_at=excluded.updated_at
        """,
        (name, sku, str(data.get("product_image_path") or data.get("image_path") or "").strip(), str(data.get("product_notes") or "").strip(), now, now),
    )
    row = conn.execute("SELECT id FROM products WHERE name=? AND sku=?", (name, sku)).fetchone()
    return int(row[0]) if row else None

