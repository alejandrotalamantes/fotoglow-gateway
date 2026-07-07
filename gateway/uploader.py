"""Observa incoming/ y sube fotos a la galería online."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

import requests

from .state import get_evento_id, record_upload
from .utils import ensure_dir, is_image, is_raw, wait_for_stable_file

log = logging.getLogger("gateway.uploader")


def _resolve_evento_id(fallback: int | None) -> int | None:
    current = get_evento_id()
    if current is not None:
        return current
    return fallback


def _processed_dir(cfg: dict, evento_id: int) -> Path:
    return cfg["processedRoot"] / str(evento_id)


def _failed_dir(cfg: dict, evento_id: int) -> Path:
    return cfg["failedRoot"] / str(evento_id)


def _walk_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return sorted(out, key=lambda x: x.stat().st_mtime)


def _upload_file(path: Path, *, evento_id: int, upload_url: str) -> dict:
    with path.open("rb") as f:
        res = requests.post(
            upload_url,
            data={"evento": str(evento_id)},
            files={"foto": (path.name, f, "image/jpeg")},
            timeout=120,
        )
    res.raise_for_status()
    data = res.json()
    if data.get("status") == "error":
        raise RuntimeError(data.get("message") or "El hosting rechazó la subida")
    return data


def _unique_dest(dest_dir: Path, name: str) -> Path:
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem = Path(name).stem
    ext = Path(name).suffix
    n = 2
    while True:
        candidate = dest_dir / f"{stem}_{n}{ext}"
        if not candidate.exists():
            return candidate
        n += 1


def run_uploader_loop(cfg: dict) -> None:
    incoming: Path = cfg["incomingDir"]
    uploader = cfg["uploader"]
    fallback = cfg.get("eventoIdFallback")

    ensure_dir(incoming)

    log.info(
        "Uploader activo — incoming=%s, remoto=%s (evento vía panel web)",
        incoming,
        cfg["remoteUploadUrl"],
    )

    retry_at: dict[str, float] = {}
    processing: set[str] = set()
    last_no_evento_log = 0.0

    while True:
        try:
            evento_id = _resolve_evento_id(fallback)
            pending = _walk_files(incoming)

            if not evento_id and pending:
                now = time.monotonic()
                if now - last_no_evento_log > 30:
                    log.warning(
                        "Hay %s foto(s) en cola pero no hay eventoId — abre el panel web desde el celular",
                        len(pending),
                    )
                    last_no_evento_log = now

            for file_path in pending:
                key = str(file_path.resolve()).lower()
                if key in processing:
                    continue

                if is_raw(file_path):
                    log.warning(
                        "RAW omitido (%s): %s — configura la cámara para enviar JPEG",
                        file_path.suffix,
                        file_path.name,
                    )
                    continue

                if not is_image(file_path):
                    continue

                if not evento_id:
                    continue

                now = time.monotonic()
                if retry_at.get(key, 0) > now:
                    continue

                processing.add(key)
                try:
                    if not wait_for_stable_file(
                        file_path,
                        checks=uploader["stableChecks"],
                        interval=uploader["stableIntervalSeconds"],
                    ):
                        log.warning("Archivo inestable, se reintentará: %s", file_path.name)
                        retry_at[key] = now + uploader["retrySeconds"]
                        continue

                    processed = _processed_dir(cfg, evento_id)
                    failed = _failed_dir(cfg, evento_id)
                    ensure_dir(processed)
                    ensure_dir(failed)

                    log.info("Subiendo %s (evento %s) …", file_path.name, evento_id)
                    result = _upload_file(
                        file_path,
                        evento_id=evento_id,
                        upload_url=cfg["remoteUploadUrl"],
                    )
                    dest = _unique_dest(processed, file_path.name)
                    shutil.move(str(file_path), str(dest))
                    remote_url = result.get("url", "remoto")
                    record_upload(filename=file_path.name, evento_id=evento_id, remote_url=str(remote_url))
                    log.info("✅ Subida OK: %s → %s", file_path.name, remote_url)
                    retry_at.pop(key, None)
                except Exception as exc:
                    log.error("Error subiendo %s: %s", file_path.name, exc)
                    retry_at[key] = now + uploader["retrySeconds"]
                    if evento_id:
                        try:
                            fail_dest = _unique_dest(_failed_dir(cfg, evento_id), file_path.name)
                            if file_path.exists():
                                shutil.copy2(str(file_path), str(fail_dest))
                        except OSError:
                            pass
                finally:
                    processing.discard(key)
        except Exception as exc:
            log.error("Error en ciclo uploader: %s", exc)

        time.sleep(uploader["pollSeconds"])
