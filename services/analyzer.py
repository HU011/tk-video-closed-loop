from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from core.db import utc_now


def _safe_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def score_video(video: dict[str, Any]) -> tuple[float, str]:
    views = max(_safe_int(video.get("views")), 0)
    likes = max(_safe_int(video.get("likes")), 0)
    comments = max(_safe_int(video.get("comments")), 0)
    shares = max(_safe_int(video.get("shares")), 0)
    orders = max(_safe_int(video.get("orders")), 0)
    gmv = max(_safe_float(video.get("gmv")), 0)
    duration = max(_safe_float(video.get("duration_seconds")), 0)

    engagement = (likes + comments * 2 + shares * 3) / max(views, 1)
    view_score = min(40.0, math.log10(max(views, 1)) * 8)
    engagement_score = min(25.0, engagement * 350)
    commerce_score = min(25.0, orders * 0.8 + gmv / 80)
    duration_bonus = 10.0 if 15 <= duration <= 30 else 6.0 if duration <= 60 else 2.0
    score = round(view_score + engagement_score + commerce_score + duration_bonus, 2)

    reasons = [
        f"播放分 {view_score:.1f}",
        f"互动率 {engagement * 100:.2f}%",
        f"成交分 {commerce_score:.1f}",
        f"时长 {duration:.0f}s",
    ]
    return score, "；".join(reasons)


def score_creator(row: dict[str, Any]) -> tuple[float, list[str]]:
    sample_count = _safe_int(row.get("sample_received_count"))
    posted = _safe_int(row.get("posted_video_count"))
    orders = _safe_int(row.get("order_count"))
    gmv = _safe_float(row.get("gmv"))
    followers = _safe_int(row.get("follower_count"))

    score = 0.0
    reasons: list[str] = []
    if sample_count >= 3:
        score += min(35, sample_count * 5)
        reasons.append(f"样品领取 {sample_count} 次")
    if sample_count > 0:
        post_gap = max(sample_count - posted, 0)
        score += min(30, post_gap * 10)
        if post_gap:
            reasons.append(f"领取后未回传视频 {post_gap} 次")
    if orders <= 1:
        score += 15
        reasons.append("成交很低")
    if gmv <= 50:
        score += 10
        reasons.append("GMV 很低")
    if followers >= 50000 and posted == 0:
        score += 10
        reasons.append("粉丝量高但样品后无视频")
    return round(min(score, 100), 2), reasons


def recalculate_all(conn: sqlite3.Connection) -> dict[str, int]:
    videos = conn.execute("SELECT * FROM videos").fetchall()
    for row in videos:
        score, reason = score_video(dict(row))
        conn.execute(
            "UPDATE videos SET hot_score=?, hot_reason=?, updated_at=? WHERE id=?",
            (score, reason, utc_now(), row["id"]),
        )

    conn.execute(
        """
        UPDATE creators
        SET
            posted_video_count = MAX(
                posted_video_count,
                COALESCE((SELECT COUNT(*) FROM videos WHERE videos.creator_id = creators.id), 0)
            ),
            order_count = MAX(
                order_count,
                COALESCE((SELECT SUM(orders) FROM videos WHERE videos.creator_id = creators.id), 0)
            ),
            gmv = MAX(
                gmv,
                COALESCE((SELECT SUM(gmv) FROM videos WHERE videos.creator_id = creators.id), 0)
            ),
            updated_at = ?
        """,
        (utc_now(),),
    )
    creators = conn.execute("SELECT * FROM creators").fetchall()
    for row in creators:
        score, reasons = score_creator(dict(row))
        conn.execute(
            """
            UPDATE creators
            SET free_sample_score=?, free_sample_reasons=?, updated_at=?
            WHERE id=?
            """,
            (score, json.dumps(reasons, ensure_ascii=False), utc_now(), row["id"]),
        )
        if score >= 50:
            conn.execute(
                """
                INSERT INTO sample_candidates(creator_id, score, reasons, status, created_at, updated_at)
                VALUES (?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(creator_id) DO UPDATE SET
                    score=excluded.score,
                    reasons=excluded.reasons,
                    updated_at=excluded.updated_at
                """,
                (row["id"], score, json.dumps(reasons, ensure_ascii=False), utc_now(), utc_now()),
            )
        else:
            conn.execute("DELETE FROM sample_candidates WHERE creator_id=?", (row["id"],))
    return {"videos": len(videos), "creators": len(creators)}
