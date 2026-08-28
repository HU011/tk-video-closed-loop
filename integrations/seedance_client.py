from __future__ import annotations

import json
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import ensure_under_root
from core.settings import settings
from integrations.apimart_client import APIMartClient, is_remote_url, public_project_url
from media.ffmpeg_tools import extract_tail_frame, make_mock_video


@dataclass(frozen=True)
class SeedanceResult:
    video_path: Path
    tail_frame_path: Path | None
    video_url: str = ""
    tail_frame_url: str = ""


class SeedanceClient:
    def __init__(self) -> None:
        self.provider = settings.seedance_provider
        self.endpoint = settings.seedance_endpoint
        self.api_key = settings.seedance_api_key
        self.model = settings.seedance_model
        self.apimart = APIMartClient(self.api_key)

    def generate_segment(
        self,
        prompt: str,
        source_segment_path: str | Path,
        product_image_path: str | Path,
        output_path: str | Path,
        duration: int,
        first_frame_path: str | Path | None = None,
        tail_frame_output_path: str | Path | None = None,
    ) -> SeedanceResult:
        out = ensure_under_root(output_path)
        tail_out = ensure_under_root(tail_frame_output_path) if tail_frame_output_path else None
        if self.provider == "mock":
            make_mock_video(product_image_path, out, duration=duration, tail_frame=first_frame_path)
            if tail_out:
                extract_tail_frame(out, tail_out)
            return SeedanceResult(video_path=out, tail_frame_path=tail_out)

        if self.provider != "apimart":
            raise ValueError("real Seedance calls currently require SEEDANCE_PROVIDER=apimart")
        if not self.api_key:
            raise ValueError("SEEDANCE_API_KEY or APIMART_API_KEY is required when SEEDANCE_PROVIDER=apimart")

        video_url, tail_frame_url = self._submit_and_wait_apimart(
            prompt=prompt,
            source_segment_path=source_segment_path,
            product_image_path=product_image_path,
            duration=duration,
            first_frame_path=first_frame_path,
        )
        self.apimart.download(video_url, out)
        downloaded_tail: Path | None = None
        if tail_frame_url and tail_out:
            downloaded_tail = self.apimart.download(tail_frame_url, tail_out)
        elif tail_out:
            extract_tail_frame(out, tail_out)
            downloaded_tail = tail_out
        return SeedanceResult(
            video_path=out,
            tail_frame_path=downloaded_tail,
            video_url=video_url,
            tail_frame_url=tail_frame_url,
        )

    def _submit_and_wait_apimart(
        self,
        prompt: str,
        source_segment_path: str | Path,
        product_image_path: str | Path,
        duration: int,
        first_frame_path: str | Path | None,
    ) -> tuple[str, str]:
        image_urls = [self.apimart.upload_image(product_image_path)]
        if first_frame_path:
            image_urls.insert(0, self.apimart.upload_image(first_frame_path))

        video_urls = [public_project_url(source_segment_path)]
        if first_frame_path:
            prompt_prefix = "参考图1是上一段视频返回的尾帧，请让当前段开场构图、主体位置、产品位置和动作方向与其连续；参考图2是要替换进画面的产品图。"
        else:
            prompt_prefix = "参考图1是要替换进画面的产品图。"
        body = {
            "model": self.model,
            "prompt": (prompt_prefix + "\n" + prompt)[:4000],
            "video_urls": video_urls,
            "image_urls": image_urls,
            "resolution": settings.seedance_resolution,
            "size": settings.seedance_ratio,
            "duration": max(4, min(int(duration), 15)),
            "generate_audio": settings.seedance_generate_audio,
            "return_last_frame": True,
        }
        task = self.apimart.json_request(self.endpoint, body, "POST")
        task_id = self._extract_task_id(task)
        if not task_id:
            video_url = self._extract_video_url(task)
            tail_frame_url = self._extract_tail_frame_url(task)
            if video_url:
                return video_url, tail_frame_url
            raise RuntimeError(f"APIMart Seedance did not return task_id: {json.dumps(task, ensure_ascii=False)[:800]}")

        status_base = settings.apimart_task_endpoint_base.rstrip("/")
        status_url = f"{status_base}/{urllib.parse.quote(str(task_id))}?language=zh"
        for _ in range(120):
            data = self.apimart.json_request(status_url, None, "GET")
            payload = data.get("data", data)
            status = str(payload.get("status") or "").lower()
            if status in {"completed", "succeeded", "success", "done"}:
                video_url = self._extract_video_url(data)
                tail_frame_url = self._extract_tail_frame_url(data)
                if not video_url:
                    raise RuntimeError(f"APIMart Seedance completed without video url: {json.dumps(data, ensure_ascii=False)[:800]}")
                return video_url, tail_frame_url
            if status in {"failed", "error", "cancelled", "canceled", "expired"}:
                raise RuntimeError(f"APIMart Seedance task failed: {json.dumps(data, ensure_ascii=False)[:1200]}")
            time.sleep(8)
        raise TimeoutError(f"APIMart Seedance task timeout: {task_id}")

    def _extract_task_id(self, data: dict[str, Any]) -> str:
        candidates = [data.get("task_id"), data.get("id")]
        payload = data.get("data")
        if isinstance(payload, list) and payload:
            first = payload[0]
            if isinstance(first, dict):
                candidates.extend([first.get("task_id"), first.get("id")])
        elif isinstance(payload, dict):
            candidates.extend([payload.get("task_id"), payload.get("id")])
        for value in candidates:
            if value:
                return str(value)
        return ""

    def _extract_video_url(self, data: Any) -> str:
        for key, value in self._walk(data):
            if key.lower() in {"video_url", "result_url", "url"}:
                url = self._coerce_url(value)
                if url and self._looks_like_video(url):
                    return url
        for _key, value in self._walk(data):
            url = self._coerce_url(value)
            if url and self._looks_like_video(url):
                return url
        return ""

    def _extract_tail_frame_url(self, data: Any) -> str:
        for key, value in self._walk(data):
            key_lower = key.lower()
            if "last" in key_lower and "frame" in key_lower:
                url = self._coerce_url(value)
                if url and self._looks_like_image(url):
                    return url
        for key, value in self._walk(data):
            key_lower = key.lower()
            if key_lower in {"image_url", "cover_url", "thumbnail_url", "url"}:
                url = self._coerce_url(value)
                if url and self._looks_like_image(url):
                    return url
        return ""

    def _walk(self, value: Any, key: str = "") -> list[tuple[str, Any]]:
        items: list[tuple[str, Any]] = [(key, value)]
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                items.extend(self._walk(child_value, str(child_key)))
        elif isinstance(value, list):
            for child in value:
                items.extend(self._walk(child, key))
        return items

    def _coerce_url(self, value: Any) -> str:
        if isinstance(value, str) and is_remote_url(value):
            return value
        if isinstance(value, list):
            for item in value:
                url = self._coerce_url(item)
                if url:
                    return url
        if isinstance(value, dict):
            for nested_key in ("url", "video_url", "image_url", "last_frame_url"):
                url = self._coerce_url(value.get(nested_key))
                if url:
                    return url
        return ""

    def _looks_like_video(self, url: str) -> bool:
        lower = urllib.parse.urlparse(url).path.lower()
        return lower.endswith((".mp4", ".mov", ".webm", ".m4v")) or "/video/" in lower

    def _looks_like_image(self, url: str) -> bool:
        lower = urllib.parse.urlparse(url).path.lower()
        return lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")) or "/image/" in lower
