from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from collection.tiktok_oembed import TikTokOEmbedClient, row_from_oembed
from core.db import db
from core.paths import UPLOADS_DIR, ensure_under_root
from downloading.video_downloader import VideoDownloader
from services.analyzer import recalculate_all
from services.importer import import_video_rows, parse_csv_text


class CollectionService:
    def __init__(self) -> None:
        self.oembed = TikTokOEmbedClient()
        self.downloader = VideoDownloader()

    def collect(self, payload: dict[str, Any]) -> dict[str, Any]:
        rows = self._extract_rows(payload)
        account_name = str(payload.get("account_name") or "").strip()
        urls = [str(item).strip() for item in payload.get("urls") or [] if str(item).strip()]
        for raw in str(payload.get("url_text") or "").splitlines():
            raw = raw.strip()
            if raw:
                urls.append(raw)

        for url in urls:
            fetched = self.oembed.fetch(url)
            if fetched.ok:
                row = row_from_oembed(url, fetched.data, account_name=account_name)
                row["collection_status"] = "metadata_collected"
            else:
                row = {
                    "account_name": account_name or "collected",
                    "platform": "tiktok",
                    "username": "unknown_creator",
                    "title": url,
                    "video_url": url,
                    "collection_status": "metadata_failed",
                    "collection_error": fetched.error,
                }
            rows.append(row)

        download = bool(payload.get("download"))
        download_results: list[dict[str, Any]] = []
        if download:
            for index, row in enumerate(rows, start=1):
                if row.get("original_video_path") or not row.get("video_url"):
                    continue
                result = self.downloader.download(
                    str(row["video_url"]),
                    output_dir=UPLOADS_DIR / "video" / "collected",
                    preferred_name=f"{row.get('username') or 'creator'}_{index}",
                )
                download_results.append({"url": row["video_url"], **result.__dict__})
                if result.path:
                    row["original_video_path"] = result.path

        if not rows:
            return {"imported": 0, "download_results": download_results, "message": "no rows or urls"}

        with db() as conn:
            imported = import_video_rows(conn, rows)
            analyzed = recalculate_all(conn)
        return {
            **imported,
            "analyzed": analyzed,
            "download_results": download_results,
            "capabilities": self.downloader.capabilities(),
        }

    def _extract_rows(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if isinstance(payload.get("rows"), list):
            rows.extend(dict(item) for item in payload["rows"] if isinstance(item, dict))
        if payload.get("csv"):
            rows.extend(parse_csv_text(str(payload["csv"])))
        if payload.get("json"):
            parsed = json.loads(str(payload["json"]))
            if isinstance(parsed, list):
                rows.extend(dict(item) for item in parsed if isinstance(item, dict))
            elif isinstance(parsed, dict) and isinstance(parsed.get("rows"), list):
                rows.extend(dict(item) for item in parsed["rows"] if isinstance(item, dict))
        if payload.get("file_path"):
            source = ensure_under_root(Path(str(payload["file_path"])))
            text = source.read_text(encoding="utf-8")
            if source.suffix.lower() == ".csv":
                rows.extend(parse_csv_text(text))
            else:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    rows.extend(dict(item) for item in parsed if isinstance(item, dict))
        return rows
