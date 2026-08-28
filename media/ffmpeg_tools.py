from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Iterable

from core.paths import ensure_under_root
from core.settings import settings


class FFmpegError(RuntimeError):
    pass


SEEDANCE_REFERENCE_VIDEO_FILTER = (
    "scale=720:1280:force_original_aspect_ratio=decrease,"
    "pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
)


def _run(args: list[str]) -> None:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise FFmpegError(detail[-2000:] or f"command failed: {' '.join(args)}")


def probe_duration(path: str | Path) -> float:
    source = ensure_under_root(path)
    proc = subprocess.run(
        [
            settings.ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(source),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise FFmpegError((proc.stderr or proc.stdout or "").strip())
    data = json.loads(proc.stdout or "{}")
    return float(data.get("format", {}).get("duration") or 0)


def split_video(source: str | Path, output_dir: str | Path, max_duration: int = 60, segment_seconds: int = 15) -> list[Path]:
    src = ensure_under_root(source)
    out_dir = ensure_under_root(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = min(max(probe_duration(src), 0.1), max_duration)
    segments: list[Path] = []
    count = max(1, math.ceil(duration / segment_seconds))
    for index in range(count):
        start = index * segment_seconds
        length = min(segment_seconds, duration - start)
        if length <= 0:
            break
        out = out_dir / f"source_segment_{index + 1:02d}.mp4"
        _run(
            [
                settings.ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                str(src),
                "-t",
                f"{length:.3f}",
                "-c:v",
                "libx264",
                "-vf",
                SEEDANCE_REFERENCE_VIDEO_FILTER,
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
        segments.append(out)
    return segments


def extract_tail_frame(source: str | Path, output_path: str | Path) -> Path:
    src = ensure_under_root(source)
    out = ensure_under_root(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            settings.ffmpeg_bin,
            "-hide_banner",
            "-y",
            "-sseof",
            "-0.1",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out),
        ]
    )
    return out


def concat_videos(sources: Iterable[str | Path], output_path: str | Path) -> Path:
    srcs = [ensure_under_root(path) for path in sources]
    out = ensure_under_root(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    list_file = out.parent / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{path.as_posix()}'" for path in srcs),
        encoding="utf-8",
    )
    try:
        _run([settings.ffmpeg_bin, "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(out)])
    except FFmpegError:
        _run(
            [
                settings.ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(out),
            ]
        )
    return out


def make_mock_video(product_image: str | Path, output_path: str | Path, duration: int = 5, tail_frame: str | Path | None = None) -> Path:
    out = ensure_under_root(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    image = Path(product_image) if product_image else None
    if image and image.exists():
        image = ensure_under_root(image)
        vf = "scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        _run(
            [
                settings.ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-loop",
                "1",
                "-i",
                str(image),
                "-t",
                str(max(1, min(duration, 15))),
                "-vf",
                vf,
                "-r",
                "30",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-movflags",
                "+faststart",
                str(out),
            ]
        )
    else:
        _run(
            [
                settings.ffmpeg_bin,
                "-hide_banner",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x101820:s=720x1280:d={max(1, min(duration, 15))}",
                "-r",
                "30",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                str(out),
            ]
        )
    return out
