from __future__ import annotations

import math
import sqlite3
import threading
from pathlib import Path
from typing import Any

from core.db import db, row_to_dict, utc_now
from core.paths import OUTPUTS_DIR, ensure_under_root, relpath
from integrations.gemini_client import GeminiClient
from integrations.seedance_client import SeedanceClient
from media.ffmpeg_tools import concat_videos, probe_duration, split_video


_running_jobs: set[int] = set()
_lock = threading.Lock()


def create_replication_job(
    conn: sqlite3.Connection,
    video_id: int,
    product_image_path: str,
    max_duration_seconds: int = 60,
) -> int:
    video = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if not video:
        raise ValueError(f"video not found: {video_id}")
    original = str(video["original_video_path"] or "").strip()
    if not original:
        raise ValueError("video.original_video_path is required for replication")
    ensure_under_root(original)
    ensure_under_root(product_image_path)
    max_duration_seconds = max(1, min(int(max_duration_seconds or 60), 60))
    now = utc_now()
    conn.execute(
        """
        INSERT INTO replication_jobs(
            video_id, product_id, product_image_path, original_video_path,
            max_duration_seconds, status, progress, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, 'queued', 0, ?, ?)
        """,
        (video_id, video["product_id"], relpath(product_image_path), relpath(original), max_duration_seconds, now, now),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def start_job(job_id: int) -> bool:
    with _lock:
        if job_id in _running_jobs:
            return False
        _running_jobs.add(job_id)
    thread = threading.Thread(target=_run_job_safely, args=(job_id,), daemon=True)
    thread.start()
    return True


def _run_job_safely(job_id: int) -> None:
    try:
        run_replication_job(job_id)
    except Exception as exc:  # noqa: BLE001 - job errors must be persisted
        _mark_job_failed(job_id, str(exc))
    finally:
        with _lock:
            _running_jobs.discard(job_id)


def run_replication_job(job_id: int) -> None:
    with db() as conn:
        job = row_to_dict(conn.execute("SELECT * FROM replication_jobs WHERE id=?", (job_id,)).fetchone())
        if not job:
            raise ValueError(f"job not found: {job_id}")
        _update_job(conn, job_id, status="running", progress=2)

    original = ensure_under_root(job["original_video_path"])
    product_image = ensure_under_root(job["product_image_path"])
    max_duration = max(1, min(int(job["max_duration_seconds"]), 60))
    job_dir = ensure_under_root(OUTPUTS_DIR / f"replication_job_{job_id:05d}")
    job_dir.mkdir(parents=True, exist_ok=True)

    source_segments = split_video(original, job_dir / "source_segments", max_duration=max_duration, segment_seconds=15)
    total_segments = len(source_segments)
    if total_segments > 4:
        source_segments = source_segments[:4]
        total_segments = 4
    if not source_segments:
        raise RuntimeError("no source segments generated")

    gemini = GeminiClient()
    seedance = SeedanceClient()
    generated_segments: list[Path] = []
    previous_tail: Path | None = None

    for idx, source_segment in enumerate(source_segments, start=1):
        with db() as conn:
            _upsert_segment(conn, job_id, idx, source_segment_path=source_segment, status="prompting")
            _update_job(conn, job_id, status="running", progress=_progress(idx - 1, total_segments, 10))

        prompt_data = gemini.build_segment_prompt(
            segment_index=idx,
            total_segments=total_segments,
            source_segment_path=source_segment,
            original_video_path=original,
            product_image_path=product_image,
            previous_tail_frame_path=previous_tail,
        )
        prompt = str(prompt_data.get("prompt") or "")
        if not prompt:
            raise RuntimeError(f"empty prompt for segment {idx}")

        generated_path = job_dir / "generated_segments" / f"generated_segment_{idx:02d}.mp4"
        duration = max(4, min(15, int(math.ceil(probe_duration(source_segment)))))

        with db() as conn:
            _upsert_segment(conn, job_id, idx, prompt=prompt, status="generating")
            _update_job(conn, job_id, status="running", progress=_progress(idx - 1, total_segments, 35))

        tail_path = job_dir / "tail_frames" / f"tail_frame_{idx:02d}.jpg"
        result = seedance.generate_segment(
            prompt=prompt,
            source_segment_path=source_segment,
            product_image_path=product_image,
            first_frame_path=previous_tail,
            output_path=generated_path,
            duration=duration,
            tail_frame_output_path=tail_path,
        )
        generated_segments.append(result.video_path)
        previous_tail = result.tail_frame_path or tail_path

        with db() as conn:
            _upsert_segment(
                conn,
                job_id,
                idx,
                generated_video_path=result.video_path,
                tail_frame_path=previous_tail,
                status="succeeded",
            )
            _update_job(conn, job_id, status="running", progress=_progress(idx, total_segments, 70))

    final_output = job_dir / "final_replicated_video.mp4"
    concat_videos(generated_segments, final_output)
    with db() as conn:
        _update_job(conn, job_id, status="succeeded", progress=100, output_video_path=final_output, error="")


def _progress(segment_done: int, total: int, base: float) -> float:
    if total <= 0:
        return base
    return round(min(98, base + (segment_done / total) * 60), 2)


def _update_job(conn: sqlite3.Connection, job_id: int, **fields: Any) -> None:
    allowed = {"status", "progress", "output_video_path", "error"}
    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key.endswith("_path") and value:
            value = relpath(value)
        assignments.append(f"{key}=?")
        values.append(value)
    assignments.append("updated_at=?")
    values.append(utc_now())
    values.append(job_id)
    conn.execute(f"UPDATE replication_jobs SET {', '.join(assignments)} WHERE id=?", values)


def _upsert_segment(conn: sqlite3.Connection, job_id: int, segment_index: int, **fields: Any) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO replication_segments(job_id, segment_index, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(job_id, segment_index) DO UPDATE SET updated_at=excluded.updated_at
        """,
        (job_id, segment_index, now, now),
    )
    allowed = {"source_segment_path", "prompt", "generated_video_path", "tail_frame_path", "status", "error"}
    assignments: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key.endswith("_path") and value:
            value = relpath(value)
        assignments.append(f"{key}=?")
        values.append(value)
    if assignments:
        assignments.append("updated_at=?")
        values.append(now)
        values.extend([job_id, segment_index])
        conn.execute(
            f"UPDATE replication_segments SET {', '.join(assignments)} WHERE job_id=? AND segment_index=?",
            values,
        )


def _mark_job_failed(job_id: int, error: str) -> None:
    with db() as conn:
        conn.execute(
            """
            UPDATE replication_segments
            SET status='failed', error=?, updated_at=?
            WHERE job_id=? AND status IN ('prompting', 'generating')
            """,
            (error[:4000], utc_now(), job_id),
        )
        _update_job(conn, job_id, status="failed", error=error[:4000])
