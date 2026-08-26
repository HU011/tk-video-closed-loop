from __future__ import annotations

import mimetypes
import re
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core.paths import UPLOADS_DIR, ensure_under_root, relpath
from core.settings import settings


VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


@dataclass(frozen=True)
class DownloadResult:
    status: str
    path: str = ""
    message: str = ""
    method: str = ""


def safe_filename(value: str, suffix: str = ".mp4") -> str:
    parsed = urllib.parse.urlparse(value)
    base = Path(parsed.path).stem or "video"
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", base).strip("._-")[:80] or "video"
    return base + suffix


class VideoDownloader:
    def __init__(self, ytdlp_bin: str | None = None) -> None:
        self.ytdlp_bin = ytdlp_bin or settings.ytdlp_bin

    def capabilities(self) -> dict[str, bool | str]:
        return {
            "direct_http": True,
            "yt_dlp_available": self._has_ytdlp(),
            "yt_dlp_bin": self.ytdlp_bin,
        }

    def download(self, url: str, output_dir: str | Path | None = None, preferred_name: str = "") -> DownloadResult:
        if not url:
            return DownloadResult(status="skipped", message="empty url")
        out_dir = ensure_under_root(output_dir or (UPLOADS_DIR / "video" / "downloaded"))
        out_dir.mkdir(parents=True, exist_ok=True)
        suffix = self._guess_suffix(url)
        filename = safe_filename(preferred_name or url, suffix=suffix)
        target = ensure_under_root(out_dir / filename)

        if self._looks_like_direct_video(url):
            return self._download_direct(url, target)
        if self._has_ytdlp():
            return self._download_with_ytdlp(url, target)
        return DownloadResult(
            status="skipped",
            message="yt-dlp is not available and the URL is not a direct video URL",
        )

    def _download_direct(self, url: str, target: Path) -> DownloadResult:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
            with urllib.request.urlopen(req, timeout=600) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" in content_type.lower():
                    return DownloadResult(status="skipped", message="URL returned HTML, not a video file")
                target.write_bytes(resp.read())
            return DownloadResult(status="downloaded", path=relpath(target), method="direct_http")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return DownloadResult(status="failed", message=str(exc), method="direct_http")

    def _download_with_ytdlp(self, url: str, target: Path) -> DownloadResult:
        command = [
            self.ytdlp_bin,
            "--no-playlist",
            "-f",
            "mp4/best",
            "--merge-output-format",
            "mp4",
            "-o",
            str(target),
            url,
        ]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            return DownloadResult(status="failed", message=detail[-1500:], method="yt-dlp")
        if not target.exists():
            candidates = sorted(target.parent.glob(target.stem + "*"), key=lambda item: item.stat().st_mtime, reverse=True)
            for candidate in candidates:
                if candidate.suffix.lower() in VIDEO_EXTENSIONS:
                    return DownloadResult(status="downloaded", path=relpath(candidate), method="yt-dlp")
            return DownloadResult(status="failed", message="yt-dlp finished but no output file was found", method="yt-dlp")
        return DownloadResult(status="downloaded", path=relpath(target), method="yt-dlp")

    def _has_ytdlp(self) -> bool:
        return bool(shutil.which(self.ytdlp_bin) or Path(self.ytdlp_bin).exists())

    def _looks_like_direct_video(self, url: str) -> bool:
        path = urllib.parse.urlparse(url).path.lower()
        return any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)

    def _guess_suffix(self, value: str) -> str:
        path = urllib.parse.urlparse(value).path
        suffix = Path(path).suffix.lower()
        if suffix in VIDEO_EXTENSIONS:
            return suffix
        guessed = mimetypes.guess_extension(mimetypes.guess_type(path)[0] or "") or ".mp4"
        return guessed if guessed in VIDEO_EXTENSIONS else ".mp4"

