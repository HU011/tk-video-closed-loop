from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
UPLOADS_DIR = ROOT_DIR / "uploads"
OUTPUTS_DIR = ROOT_DIR / "outputs"
STATIC_DIR = ROOT_DIR / "static"


def ensure_dirs() -> None:
    for path in (DATA_DIR, UPLOADS_DIR, OUTPUTS_DIR):
        path.mkdir(parents=True, exist_ok=True)


def project_path(*parts: str) -> Path:
    path = (ROOT_DIR.joinpath(*parts)).resolve()
    ensure_under_root(path)
    return path


def ensure_under_root(path: str | Path) -> Path:
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(ROOT_DIR)
    except ValueError as exc:
        raise ValueError(f"path is outside project root: {resolved}") from exc
    return resolved


def public_file_path(relative_path: str) -> Path:
    cleaned = relative_path.replace("\\", "/").lstrip("/")
    return ensure_under_root(ROOT_DIR / cleaned)


def relpath(path: str | Path) -> str:
    resolved = ensure_under_root(path)
    return resolved.relative_to(ROOT_DIR).as_posix()

