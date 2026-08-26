from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

from core.db import db, init_db
from core.paths import ROOT_DIR, UPLOADS_DIR
from core.settings import settings
from services.analyzer import recalculate_all
from services.importer import import_video_rows


def run(args: list[str]) -> bool:
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.returncode == 0


def make_demo_media() -> tuple[str, str]:
    ffmpeg_bin = settings.ffmpeg_bin
    if not shutil.which(ffmpeg_bin) and not Path(ffmpeg_bin).exists():
        raise RuntimeError("ffmpeg is not available; set FFMPEG_BIN or install ffmpeg first.")
    video_dir = UPLOADS_DIR / "video"
    product_dir = UPLOADS_DIR / "product"
    video_dir.mkdir(parents=True, exist_ok=True)
    product_dir.mkdir(parents=True, exist_ok=True)
    video = video_dir / "demo_original_32s.mp4"
    image = product_dir / "demo_product.jpg"
    if not video.exists():
        run(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=720x1280:rate=30:duration=32",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                str(video),
            ]
        )
    if not image.exists():
        run(
            [
                ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x2d6a4f:s=720x1280",
                "-frames:v",
                "1",
                str(image),
            ]
        )
    return video.relative_to(ROOT_DIR).as_posix(), image.relative_to(ROOT_DIR).as_posix()


def main() -> None:
    init_db()
    video_path, image_path = make_demo_media()
    rows = [
        {
            "account_name": "shop_account_a",
            "username": "creator_hot_01",
            "nickname": "Hot Creator",
            "title": "32 秒厨房收纳带货视频",
            "video_url": "https://example.com/video/1",
            "original_video_path": video_path,
            "product_name": "可折叠收纳盒",
            "product_image_path": image_path,
            "duration_seconds": 32,
            "views": 280000,
            "likes": 18600,
            "comments": 940,
            "shares": 3100,
            "orders": 360,
            "gmv": 9200,
            "sample_received_count": 1,
            "posted_video_count": 2,
            "follower_count": 87000,
        },
        {
            "account_name": "shop_account_b",
            "username": "sample_risk_09",
            "nickname": "Sample Hunter",
            "title": "未回传样品达人记录",
            "video_url": "https://example.com/video/2",
            "product_name": "便携补光灯",
            "duration_seconds": 18,
            "views": 1200,
            "likes": 38,
            "comments": 2,
            "shares": 1,
            "orders": 0,
            "gmv": 0,
            "sample_received_count": 6,
            "posted_video_count": 1,
            "follower_count": 58000,
        },
    ]
    with db() as conn:
        result = import_video_rows(conn, rows)
        analyzed = recalculate_all(conn)
    print({"import": result, "analyzed": analyzed})


if __name__ == "__main__":
    main()
