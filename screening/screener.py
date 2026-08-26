from __future__ import annotations

import json
import sqlite3
from typing import Any

from core.db import rows_to_dicts
from services.analyzer import recalculate_all


class ScreeningService:
    def run(self, conn: sqlite3.Connection, hot_limit: int = 100, sample_limit: int = 100) -> dict[str, Any]:
        analyzed = recalculate_all(conn)
        hot_videos = rows_to_dicts(
            conn.execute(
                """
                SELECT v.*, c.username, c.nickname, p.name AS product_name
                FROM videos v
                LEFT JOIN creators c ON c.id = v.creator_id
                LEFT JOIN products p ON p.id = v.product_id
                WHERE v.hot_score >= 60
                ORDER BY v.hot_score DESC, v.views DESC
                LIMIT ?
                """,
                (hot_limit,),
            ).fetchall()
        )
        candidates = rows_to_dicts(
            conn.execute(
                """
                SELECT sc.*, c.username, c.nickname, c.follower_count, c.sample_received_count,
                    c.posted_video_count, c.order_count, c.gmv
                FROM sample_candidates sc
                JOIN creators c ON c.id = sc.creator_id
                ORDER BY sc.score DESC
                LIMIT ?
                """,
                (sample_limit,),
            ).fetchall()
        )
        return {
            "analyzed": analyzed,
            "hot_videos": hot_videos,
            "sample_candidates": candidates,
            "summary": {
                "hot_video_count": len(hot_videos),
                "sample_candidate_count": len(candidates),
            },
        }

    def export_summary(self, result: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False, indent=2)

