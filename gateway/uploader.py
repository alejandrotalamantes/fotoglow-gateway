"""Observa incoming/ y sube fotos autorizadas al hosting."""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

import requests

from .device import get_device_credentials
from .state import get_evento_id, get_upload_token, record_upload
from .utils import ensure_dir, is_image, is_raw, wait_for_stable_file

log = logging.getLogger("gateway.uploader")


def _storage_dir_key(upload_token: str | None) -> str:
    if upload_token:
        return f"token_{upload_token[:16]}"
    return "sin_config"


def _processed_dir(cfg: dict, dir_key: str) -> Path:
    return cfg["processedRoot"] / dir_key


def _failed_dir(cfg: dict, dir_key: str) -> Path:
    return cfg["failedRoot"] / dir_key


def _walk_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    out: list[Path] = []
    for p in root.rglob("*"):
        if p.is_file():
            out.append(p)
    return sorted(out, key=lambda x: x.stat().st_mtime)


def _upload_file(
    path: Path,
    *,
    upload_url: str,
    device: dict[str, str],
    upload_token: str,
    evento_id: int | None,
) -> dict:
    data: dict[str, str] = {
        "idRaspberry": device["idRaspberry"],
        "deviceSecret": device["deviceSecret"],
        "token": upload_token,
    }
    if evento_id is not None:
        data["evento"] = str(evento_id)

    with path.open("rb") as f:
        res = requests.post(
            upload_url,
            data=data,
            files={"foto": (path.name, f, "image/jpeg")},
            timeout=120,
        )
    res.raise_for_status()
    payload = res.json()
    if payload.get("status") == "error":
        raise RuntimeError(payload.get("message") or "El hosting rechazó la subida")
    return payload


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
    device = get_device_credentials()

    ensure_dir(incoming)

    log.info(
        "Uploader activo — id=%s, remoto=%s",
        device["idRaspberry"],
        cfg["remoteUploadUrl"],
    )

    retry_at: dict[str, float] = {}
    processing: set[str] = set()
    last_no_config_log = 0.0

    while True:
        try:
            upload_token = get_upload_token()
            evento_id = get_evento_id()
            dir_key = _storage_dir_key(upload_token)
            pending = _walk_files(incoming)

            if not upload_token and pending:
                now = time.monotonic()
                if now - last_no_config_log > 30:
                    log.warning(
                        "Hay %s foto(s) en cola pero falta token de galería — configura el evento en el panel",
                        len(pending),
                    )
                    last_no_config_log = now

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

                if not upload_token:
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

                    processed = _processed_dir(cfg, dir_key)
                    failed = _failed_dir(cfg, dir_key)
                    ensure_dir(processed)
                    ensure_dir(failed)

                    log.info("Subiendo %s …", file_path.name)
                    result = _upload_file(
                        file_path,
                        upload_url=cfg["remoteUploadUrl"],
                        device=device,
                        upload_token=upload_token,
                        evento_id=evento_id,
                    )
                    dest = _unique_dest(processed, file_path.name)
                    shutil.move(str(file_path), str(dest))
                    remote_url = result.get("url", "remoto")
                    record_upload(
                        filename=file_path.name,
                        evento_id=evento_id,
                        remote_url=str(remote_url),
                    )
                    log.info("✅ Subida OK: %s → %s", file_path.name, remote_url)
                    retry_at.pop(key, None)
                except Exception as exc:
                    log.error("Error subiendo %s: %s", file_path.name, exc)
                    retry_at[key] = now + uploader["retrySeconds"]
                    try:
                        fail_dest = _unique_dest(_failed_dir(cfg, dir_key), file_path.name)
                        if file_path.exists():
                            shutil.copy2(str(file_path), str(fail_dest))
                    except OSError:
                        pass
                finally:
                    processing.discard(key)
        except Exception as exc:
            log.error("Error en ciclo uploader: %s", exc)

        time.sleep(uploader["pollSeconds"])
