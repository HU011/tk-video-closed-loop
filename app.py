from __future__ import annotations

import base64
import json
import mimetypes
import re
import shutil
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from core.db import db, init_db, row_to_dict, rows_to_dicts, utc_now
from core.paths import OUTPUTS_DIR, ROOT_DIR, STATIC_DIR, UPLOADS_DIR, ensure_under_root, public_file_path, relpath
from core.settings import settings
from collection.collector import CollectionService
from downloading.video_downloader import VideoDownloader
from pipeline.closed_loop import ClosedLoopPipeline
from services.analyzer import recalculate_all
from services.importer import import_video_rows, parse_csv_text
from services.replicator import create_replication_job, start_job
from screening.screener import ScreeningService


MAX_JSON_BODY = 220 * 1024 * 1024


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((settings.host, settings.port), Handler)
    print(f"Serving on http://{settings.host}:{settings.port}")
    server.serve_forever()


class Handler(BaseHTTPRequestHandler):
    server_version = "TKLoop/0.1"

    def do_GET(self) -> None:  # noqa: N802
        self._handle("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._handle("POST")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self._cors_headers()
        self.end_headers()

    def _handle(self, method: str) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            if method == "GET" and path == "/":
                return self._serve_static("index.html")
            if method == "GET" and path.startswith("/static/"):
                return self._serve_static(path.removeprefix("/static/"))
            if method == "GET" and path.startswith("/files/"):
                return self._serve_project_file(unquote(path.removeprefix("/files/")))
            if not path.startswith("/api/"):
                return self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

            if method == "GET":
                return self._api_get(path, query)
            if method == "POST":
                return self._api_post(path, self._json_body())
            return self._json({"error": "method not allowed"}, status=HTTPStatus.METHOD_NOT_ALLOWED)
        except Exception as exc:  # noqa: BLE001 - API should return JSON errors
            return self._json({"error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _api_get(self, path: str, query: dict[str, str]) -> None:
        if path == "/api/health":
            return self._json(
                {
                    "ok": True,
                    "root": str(ROOT_DIR),
                    "seedance_provider": settings.seedance_provider,
                    "gemini_configured": bool(settings.gemini_api_key),
                    "apimart_configured": bool(settings.apimart_api_key),
                    "ffmpeg_available": command_available(settings.ffmpeg_bin),
                    "ffprobe_available": command_available(settings.ffprobe_bin),
                    "yt_dlp_available": command_available(settings.ytdlp_bin),
                }
            )
        if path == "/api/modules":
            return self._json(get_module_status())
        if path == "/api/dashboard":
            return self._json(get_dashboard())
        if path == "/api/accounts":
            return self._json(list_rows("accounts", order="updated_at DESC"))
        if path == "/api/products":
            return self._json(list_rows("products", order="updated_at DESC"))
        if path == "/api/creators":
            return self._json(list_creators(query))
        if path == "/api/videos":
            return self._json(list_videos(query))
        if path == "/api/hot-videos":
            return self._json(list_videos({"hot": "1", **query}))
        if path == "/api/free-sample-candidates":
            return self._json(list_candidates(query))
        if path == "/api/jobs":
            return self._json(list_jobs())
        match = re.fullmatch(r"/api/jobs/(\d+)", path)
        if match:
            return self._json(get_job(int(match.group(1))))
        return self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _api_post(self, path: str, body: dict[str, Any]) -> None:
        if path == "/api/import/videos":
            rows = body.get("rows")
            if rows is None and body.get("csv"):
                rows = parse_csv_text(str(body["csv"]))
            if not isinstance(rows, list):
                return self._json({"error": "rows or csv is required"}, status=HTTPStatus.BAD_REQUEST)
            with db() as conn:
                result = import_video_rows(conn, rows)
                result["analyzed"] = recalculate_all(conn)
            return self._json(result)
        if path == "/api/videos":
            with db() as conn:
                result = import_video_rows(conn, [body])
                recalculate_all(conn)
            return self._json(result, status=HTTPStatus.CREATED)
        if path == "/api/analyze":
            with db() as conn:
                result = recalculate_all(conn)
            return self._json(result)
        if path == "/api/collect":
            return self._json(CollectionService().collect(body), status=HTTPStatus.CREATED)
        if path == "/api/closed-loop/collect-screen":
            return self._json(ClosedLoopPipeline().collect_and_screen(body), status=HTTPStatus.CREATED)
        if path == "/api/screen":
            with db() as conn:
                result = ScreeningService().run(conn)
            return self._json(result)
        if path == "/api/download-video":
            return self._json(download_video(body))
        if path == "/api/upload":
            return self._json(save_upload(body), status=HTTPStatus.CREATED)
        if path == "/api/replicate":
            video_id = int(body.get("video_id") or 0)
            product_image_path = str(body.get("product_image_path") or "").strip()
            if not product_image_path:
                return self._json({"error": "product_image_path is required"}, status=HTTPStatus.BAD_REQUEST)
            with db() as conn:
                job_id = create_replication_job(
                    conn,
                    video_id=video_id,
                    product_image_path=product_image_path,
                    max_duration_seconds=int(body.get("max_duration_seconds") or 60),
                )
            start_job(job_id)
            return self._json({"job_id": job_id}, status=HTTPStatus.CREATED)
        return self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_JSON_BODY:
            raise ValueError("request body is too large")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _serve_static(self, relative: str) -> None:
        relative = relative.strip("/") or "index.html"
        target = ensure_under_root(STATIC_DIR / relative)
        if not str(target).lower().startswith(str(STATIC_DIR.resolve()).lower()):
            return self._json({"error": "file access denied"}, status=HTTPStatus.FORBIDDEN)
        if not target.exists() or not target.is_file():
            return self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        self._send_file(target)

    def _serve_project_file(self, relative: str) -> None:
        target = public_file_path(relative)
        allowed_roots = (UPLOADS_DIR.resolve(), OUTPUTS_DIR.resolve())
        if not any(str(target).lower().startswith(str(root).lower()) for root in allowed_roots):
            return self._json({"error": "file access denied"}, status=HTTPStatus.FORBIDDEN)
        if not target.exists() or not target.is_file():
            return self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
        self._send_file(target)

    def _send_file(self, target: Path) -> None:
        raw = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self._cors_headers()
        self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


def save_upload(body: dict[str, Any]) -> dict[str, str]:
    filename = str(body.get("filename") or "upload.bin")
    content = str(body.get("content_base64") or "")
    kind = re.sub(r"[^a-zA-Z0-9_-]", "", str(body.get("kind") or "files")) or "files"
    if "," in content and content.startswith("data:"):
        content = content.split(",", 1)[1]
    if not content:
        raise ValueError("content_base64 is required")
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", Path(filename).name)[:120] or "upload.bin"
    target_dir = ensure_under_root(UPLOADS_DIR / kind)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = ensure_under_root(target_dir / f"{utc_now().replace(':', '').replace('+', '_')}_{safe_name}")
    target.write_bytes(base64.b64decode(content))
    return {"path": relpath(target), "url": "/files/" + relpath(target)}


def list_rows(table: str, order: str = "id DESC", limit: int = 200) -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY {order} LIMIT ?", (limit,)).fetchall()
    return {"items": rows_to_dicts(rows)}


def get_module_status() -> dict[str, Any]:
    downloader = VideoDownloader()
    return {
        "collection": {
            "ready": True,
            "sources": ["csv", "json", "url_text", "rows", "tiktok_oembed"],
            "download_capabilities": downloader.capabilities(),
        },
        "screening": {
            "ready": True,
            "hot_video_threshold": 60,
            "sample_candidate_threshold": 50,
        },
        "replication": {
            "ready": True,
            "max_duration_seconds": 60,
            "segment_seconds": 15,
            "seedance_provider": settings.seedance_provider,
            "return_last_frame": True,
        },
    }


def download_video(body: dict[str, Any]) -> dict[str, Any]:
    video_id = int(body.get("video_id") or 0)
    url = str(body.get("url") or "").strip()
    preferred = str(body.get("preferred_name") or "").strip()
    if video_id:
        with db() as conn:
            row = conn.execute("SELECT id, video_url, title FROM videos WHERE id=?", (video_id,)).fetchone()
            if not row:
                return {"error": "video not found"}
            url = url or str(row["video_url"] or "")
            preferred = preferred or str(row["title"] or f"video_{video_id}")
        if not url:
            return {"error": "video has no video_url"}
    result = VideoDownloader().download(url, output_dir=UPLOADS_DIR / "video" / "downloaded", preferred_name=preferred)
    if video_id and result.path:
        with db() as conn:
            conn.execute(
                "UPDATE videos SET original_video_path=?, updated_at=? WHERE id=?",
                (result.path, utc_now(), video_id),
            )
    return result.__dict__


def list_creators(query: dict[str, str]) -> dict[str, Any]:
    limit = min(int(query.get("limit") or 200), 500)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.*, COUNT(v.id) AS video_count, MAX(v.hot_score) AS best_hot_score
            FROM creators c
            LEFT JOIN videos v ON v.creator_id = c.id
            GROUP BY c.id
            ORDER BY c.free_sample_score DESC, best_hot_score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def list_videos(query: dict[str, str]) -> dict[str, Any]:
    limit = min(int(query.get("limit") or 200), 500)
    hot_only = query.get("hot") == "1"
    where = "WHERE v.hot_score >= 60" if hot_only else ""
    with db() as conn:
        rows = conn.execute(
            f"""
            SELECT
                v.*, a.name AS account_name, c.username, c.nickname, c.free_sample_score,
                p.name AS product_name, p.image_path AS product_image_path
            FROM videos v
            LEFT JOIN accounts a ON a.id = v.account_id
            LEFT JOIN creators c ON c.id = v.creator_id
            LEFT JOIN products p ON p.id = v.product_id
            {where}
            ORDER BY v.hot_score DESC, v.views DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def list_candidates(query: dict[str, str]) -> dict[str, Any]:
    limit = min(int(query.get("limit") or 200), 500)
    with db() as conn:
        rows = conn.execute(
            """
            SELECT sc.*, c.username, c.nickname, c.follower_count, c.sample_received_count,
                c.posted_video_count, c.order_count, c.gmv
            FROM sample_candidates sc
            JOIN creators c ON c.id = sc.creator_id
            ORDER BY sc.score DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def list_jobs() -> dict[str, Any]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT j.*, v.title, c.username
            FROM replication_jobs j
            JOIN videos v ON v.id = j.video_id
            JOIN creators c ON c.id = v.creator_id
            ORDER BY j.id DESC
            LIMIT 100
            """
        ).fetchall()
    return {"items": rows_to_dicts(rows)}


def get_job(job_id: int) -> dict[str, Any]:
    with db() as conn:
        job = row_to_dict(
            conn.execute(
                """
                SELECT j.*, v.title, c.username
                FROM replication_jobs j
                JOIN videos v ON v.id = j.video_id
                JOIN creators c ON c.id = v.creator_id
                WHERE j.id=?
                """,
                (job_id,),
            ).fetchone()
        )
        segments = rows_to_dicts(
            conn.execute(
                "SELECT * FROM replication_segments WHERE job_id=? ORDER BY segment_index",
                (job_id,),
            ).fetchall()
        )
    if not job:
        return {"error": "not found"}
    job["segments"] = segments
    return job


def get_dashboard() -> dict[str, Any]:
    with db() as conn:
        counts = {
            "accounts": conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "creators": conn.execute("SELECT COUNT(*) FROM creators").fetchone()[0],
            "videos": conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0],
            "hot_videos": conn.execute("SELECT COUNT(*) FROM videos WHERE hot_score >= 60").fetchone()[0],
            "sample_candidates": conn.execute("SELECT COUNT(*) FROM sample_candidates").fetchone()[0],
            "jobs": conn.execute("SELECT COUNT(*) FROM replication_jobs").fetchone()[0],
        }
    return {
        "counts": counts,
        "hot_videos": list_videos({"hot": "1", "limit": "8"})["items"],
        "sample_candidates": list_candidates({"limit": "8"})["items"],
        "jobs": list_jobs()["items"][:8],
        "config": {
            "seedance_provider": settings.seedance_provider,
            "gemini_configured": bool(settings.gemini_api_key),
            "gemini_provider": settings.gemini_provider,
            "apimart_configured": bool(settings.apimart_api_key),
            "public_base_url": settings.public_base_url,
            "ffmpeg_available": command_available(settings.ffmpeg_bin),
            "ffprobe_available": command_available(settings.ffprobe_bin),
            "yt_dlp_available": command_available(settings.ytdlp_bin),
        },
    }


def command_available(command: str) -> bool:
    return bool(shutil.which(command) or Path(command).exists())


if __name__ == "__main__":
    main()
