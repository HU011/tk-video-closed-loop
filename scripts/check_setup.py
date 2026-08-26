from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT_FOR_IMPORTS = Path(__file__).resolve().parents[1]
if str(ROOT_FOR_IMPORTS) not in sys.path:
    sys.path.insert(0, str(ROOT_FOR_IMPORTS))

from core.db import init_db
from core.paths import DATA_DIR, OUTPUTS_DIR, ROOT_DIR, UPLOADS_DIR, ensure_dirs
from core.settings import settings


def command_ok(command: str) -> bool:
    executable = shutil.which(command) or (command if Path(command).exists() else "")
    if not executable:
        return False
    proc = subprocess.run([executable, "-version"], capture_output=True, text=True, timeout=10)
    return proc.returncode == 0


def writable(path: Path) -> bool:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write_check"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local setup for the closed-loop project.")
    parser.add_argument("--mode", choices=["basic", "real"], default="basic")
    args = parser.parse_args()

    ensure_dirs()
    init_db()

    checks: list[dict[str, object]] = []

    def add(name: str, ok: bool, required: bool, detail: str = "") -> None:
        checks.append({"name": name, "ok": ok, "required": required, "detail": detail})

    add("project root exists", ROOT_DIR.exists(), True, str(ROOT_DIR))
    add("data dir writable", writable(DATA_DIR), True, str(DATA_DIR))
    add("uploads dir writable", writable(UPLOADS_DIR), True, str(UPLOADS_DIR))
    add("outputs dir writable", writable(OUTPUTS_DIR), True, str(OUTPUTS_DIR))
    video_required = args.mode == "real"
    add("ffmpeg available", command_ok(settings.ffmpeg_bin), video_required, settings.ffmpeg_bin)
    add("ffprobe available", command_ok(settings.ffprobe_bin), video_required, settings.ffprobe_bin)
    add("yt-dlp available", bool(shutil.which(settings.ytdlp_bin) or Path(settings.ytdlp_bin).exists()), False, settings.ytdlp_bin)

    real_required = args.mode == "real"
    add("APIMart API key configured", bool(settings.apimart_api_key), real_required, "APIMART_API_KEY")
    add("Gemini provider is apimart", settings.gemini_provider == "apimart", real_required, settings.gemini_provider)
    add("Seedance provider is apimart", settings.seedance_provider == "apimart", real_required, settings.seedance_provider)
    parsed_public = urlparse(settings.public_base_url)
    public_ok = parsed_public.scheme in {"http", "https"} and bool(parsed_public.netloc)
    add("PUBLIC_BASE_URL configured", public_ok, real_required, settings.public_base_url or "not set")

    failed = [item for item in checks if item["required"] and not item["ok"]]
    print(json.dumps({"mode": args.mode, "ok": not failed, "checks": checks}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
