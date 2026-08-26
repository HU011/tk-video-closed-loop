from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from core.paths import ROOT_DIR, ensure_under_root


DEFAULT_TIKTOK_LOGIN_URL = "https://seller.tiktokglobalshop.com/account/login"


@dataclass(frozen=True)
class ChromeLaunchConfig:
    chrome_path: str
    profile_dir: Path
    remote_debugging_port: int = 9333
    start_url: str = DEFAULT_TIKTOK_LOGIN_URL

    @classmethod
    def from_env(cls) -> "ChromeLaunchConfig":
        chrome_path = os.environ.get("TK_CHROME_PATH", "") or find_chrome()
        raw_profile_dir = Path(os.environ.get("TK_CHROME_PROFILE_DIR", "runtime/chrome_profile"))
        profile_dir = raw_profile_dir if raw_profile_dir.is_absolute() else ROOT_DIR / raw_profile_dir
        return cls(
            chrome_path=chrome_path,
            profile_dir=ensure_under_root(profile_dir),
            remote_debugging_port=int(os.environ.get("TK_CHROME_DEBUG_PORT", "9333")),
            start_url=os.environ.get("TK_LOGIN_URL", DEFAULT_TIKTOK_LOGIN_URL),
        )


def find_chrome() -> str:
    candidates = [
        shutil.which("chrome"),
        shutil.which("chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return "chrome"


class ChromeLauncher:
    def __init__(self, config: ChromeLaunchConfig) -> None:
        self.config = config

    def command(self) -> list[str]:
        profile = ensure_under_root(self.config.profile_dir)
        profile.mkdir(parents=True, exist_ok=True)
        return [
            self.config.chrome_path,
            f"--remote-debugging-port={self.config.remote_debugging_port}",
            f"--user-data-dir={profile}",
            "--new-window",
            self.config.start_url,
        ]

    def launch(self) -> subprocess.Popen:
        return subprocess.Popen(self.command())
