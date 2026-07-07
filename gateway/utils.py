"""Utilidades compartidas del gateway."""

from __future__ import annotations

import time
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}
SKIP_EXT = {".arw", ".cr2", ".cr3", ".nef", ".raf", ".dng"}


def is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXT


def is_raw(path: Path) -> bool:
    return path.suffix.lower() in SKIP_EXT


def wait_for_stable_file(
    path: Path,
    *,
    checks: int = 3,
    interval: float = 0.5,
    timeout: float = 60.0,
) -> bool:
    """Espera a que el archivo deje de crecer (transferencia FTP completa)."""
    start = time.monotonic()
    last_size = -1
    stable = 0

    while time.monotonic() - start < timeout:
        if not path.is_file():
            return False
        size = path.stat().st_size
        if size > 0 and size == last_size:
            stable += 1
            if stable >= checks:
                return True
        else:
            stable = 0
            last_size = size
        time.sleep(interval)

    return False


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
