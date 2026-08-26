from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from core.paths import ensure_under_root, relpath
from core.settings import settings


def is_remote_url(value: str | Path | None) -> bool:
    if value is None:
        return False
    text = str(value)
    return text.startswith(("http://", "https://", "asset://", "data:"))


def public_project_url(path: str | Path) -> str:
    text = str(path)
    if is_remote_url(text):
        return text
    if not settings.public_base_url:
        raise RuntimeError("真实 APIMart 视频参考需要 PUBLIC_BASE_URL，且 /files/... 必须公网可访问。")
    local = ensure_under_root(path)
    encoded = urllib.parse.quote(relpath(local).replace("\\", "/")).replace("%2F", "/")
    return settings.public_base_url.rstrip("/") + "/files/" + encoded


class APIMartClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or settings.apimart_api_key

    def json_request(self, url: str, body: dict[str, Any] | None = None, method: str = "POST") -> dict[str, Any]:
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"APIMart API error {exc.code}: {detail}") from exc

    def upload_image(self, path: str | Path) -> str:
        if is_remote_url(path):
            return str(path)
        source = ensure_under_root(path)
        boundary = "----codex-apimart-" + uuid.uuid4().hex
        content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{source.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
        data = header + source.read_bytes() + footer
        req = urllib.request.Request(
            settings.apimart_upload_images_endpoint,
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(data)),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"APIMart image upload error {exc.code}: {detail}") from exc
        url = result.get("url") or result.get("data", {}).get("url")
        if not url:
            raise RuntimeError(f"APIMart image upload did not return url: {json.dumps(result, ensure_ascii=False)[:500]}")
        return str(url)

    def download(self, url: str, output_path: str | Path) -> Path:
        out = ensure_under_root(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=600) as resp:
            out.write_bytes(resp.read())
        return out
