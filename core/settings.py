from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.paths import ROOT_DIR


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    database_path: Path
    public_base_url: str
    apimart_api_key: str
    apimart_base_url: str
    apimart_chat_endpoint: str
    apimart_upload_images_endpoint: str
    apimart_task_endpoint_base: str
    gemini_provider: str
    gemini_request_format: str
    gemini_endpoint: str
    gemini_api_key: str
    gemini_model: str
    seedance_provider: str
    seedance_api_key: str
    seedance_endpoint: str
    seedance_model: str
    seedance_resolution: str
    seedance_ratio: str
    seedance_generate_audio: bool
    ffmpeg_bin: str
    ffprobe_bin: str
    ytdlp_bin: str

    @classmethod
    def load(cls) -> "Settings":
        _load_dotenv(ROOT_DIR / ".env")
        config_path = ROOT_DIR / "config.json"
        file_config: dict[str, Any] = {}
        if config_path.exists():
            file_config = json.loads(config_path.read_text(encoding="utf-8"))

        def get(name: str, default: str = "") -> str:
            return str(os.environ.get(name, file_config.get(name.lower(), default)))

        return cls(
            host=get("APP_HOST", "127.0.0.1"),
            port=int(get("APP_PORT", "8765")),
            database_path=ROOT_DIR / get("DATABASE_PATH", "data/app.db"),
            public_base_url=get("PUBLIC_BASE_URL", ""),
            apimart_api_key=get("APIMART_API_KEY", ""),
            apimart_base_url=get("APIMART_BASE_URL", "https://api.apimart.ai").rstrip("/"),
            apimart_chat_endpoint=get("APIMART_CHAT_ENDPOINT", "https://api.apimart.ai/v1/chat/completions"),
            apimart_upload_images_endpoint=get("APIMART_UPLOAD_IMAGES_ENDPOINT", "https://api.apimart.ai/v1/uploads/images"),
            apimart_task_endpoint_base=get("APIMART_TASK_ENDPOINT_BASE", "https://api.apimart.ai/v1/tasks"),
            gemini_provider=get("GEMINI_PROVIDER", "mock").lower(),
            gemini_request_format=get("GEMINI_REQUEST_FORMAT", "native").lower(),
            gemini_endpoint=get("GEMINI_ENDPOINT", ""),
            gemini_api_key=get("GEMINI_API_KEY", get("APIMART_API_KEY", "")),
            gemini_model=get("GEMINI_MODEL", "gemini-2.5-flash"),
            seedance_provider=get("SEEDANCE_PROVIDER", "mock").lower(),
            seedance_api_key=get("SEEDANCE_API_KEY", get("APIMART_API_KEY", get("ARK_API_KEY", ""))),
            seedance_endpoint=get(
                "SEEDANCE_ENDPOINT",
                "https://api.apimart.ai/v1/videos/generations",
            ),
            seedance_model=get("SEEDANCE_MODEL", "seedance-2.0"),
            seedance_resolution=get("SEEDANCE_RESOLUTION", "720p"),
            seedance_ratio=get("SEEDANCE_RATIO", "9:16"),
            seedance_generate_audio=get("SEEDANCE_GENERATE_AUDIO", "false").lower() in {"1", "true", "yes"},
            ffmpeg_bin=get("FFMPEG_BIN", "ffmpeg"),
            ffprobe_bin=get("FFPROBE_BIN", "ffprobe"),
            ytdlp_bin=get("YTDLP_BIN", "yt-dlp"),
        )


settings = Settings.load()
