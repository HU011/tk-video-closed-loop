from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from core.db import upsert_account, upsert_creator, upsert_product, utc_now


def _num(value: Any, default: float = 0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def parse_csv_text(text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(text.strip()))
    return [dict(row) for row in reader]


def import_video_rows(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> dict[str, int]:
    imported = 0
    for row in rows:
        account_name = str(row.get("account_name") or row.get("account") or "default").strip() or "default"
        account_id = upsert_account(
            conn,
            name=account_name,
            handle=str(row.get("account_handle") or "").strip(),
            platform=str(row.get("platform") or "tiktok").strip() or "tiktok",
        )
        creator_id = upsert_creator(conn, row)
        product_id = upsert_product(conn, row)
        now = utc_now()
        conn.execute(
            """
            INSERT INTO videos(
                account_id, creator_id, product_id, platform, video_url, original_video_path,
                cover_path, title, duration_seconds, views, likes, comments, shares, orders,
                gmv, commission_rate, collected_at, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                creator_id,
                product_id,
                str(row.get("platform") or "tiktok").strip() or "tiktok",
                str(row.get("video_url") or row.get("url") or "").strip(),
                str(row.get("original_video_path") or row.get("local_path") or "").strip(),
                str(row.get("cover_path") or row.get("cover_url") or "").strip(),
                str(row.get("title") or "").strip(),
                _num(row.get("duration_seconds") or row.get("duration")),
                int(_num(row.get("views"))),
                int(_num(row.get("likes"))),
                int(_num(row.get("comments"))),
                int(_num(row.get("shares"))),
                int(_num(row.get("orders"))),
                _num(row.get("gmv")),
                _num(row.get("commission_rate")),
                str(row.get("collected_at") or now),
                now,
                now,
            ),
        )
        imported += 1
    return {"imported": imported}

