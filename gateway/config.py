"""Carga y validación de config.json del gateway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.json"


def _resolve_path(base: Path, value: str) -> Path:
    p = Path(value)
    if not p.is_absolute():
        p = (base / p).resolve()
    return p


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"No se encontró {cfg_path}. Copia config.example.json → config.json y edítalo."
        )

    with cfg_path.open(encoding="utf-8") as f:
        raw = json.load(f)

    upload_url = str(raw.get("remoteUploadUrl") or "").strip()
    if not upload_url:
        raise ValueError("config.json: remoteUploadUrl es obligatorio")

    paths = raw.get("paths") or {}
    incoming = _resolve_path(ROOT, str(paths.get("incoming") or "./data/incoming"))
    processed = _resolve_path(ROOT, str(paths.get("processed") or "./data/processed"))
    failed = _resolve_path(ROOT, str(paths.get("failed") or "./data/failed"))

    ftp = raw.get("ftp") or {}
    uploader = raw.get("uploader") or {}
    admin = raw.get("admin") or {}
    gphoto = raw.get("gphoto") or {}

    pasv_start = int(ftp.get("passivePortStart") or 53000)
    pasv_end = int(ftp.get("passivePortEnd") or 53099)
    if pasv_end < pasv_start:
        pasv_end = pasv_start

    ftp_enabled = ftp.get("enabled")
    if ftp_enabled is None:
        ftp_enabled = True

    # eventoId en config es opcional (fallback); lo normal es usar el panel web
    fallback_evento = raw.get("eventoId")
    try:
        fallback_evento = int(fallback_evento) if fallback_evento is not None else None
        if fallback_evento is not None and fallback_evento <= 0:
            fallback_evento = None
    except (TypeError, ValueError):
        fallback_evento = None

    return {
        "eventoIdFallback": fallback_evento,
        "remoteUploadUrl": upload_url,
        "incomingDir": incoming,
        "processedRoot": processed,
        "failedRoot": failed,
        "ftp": {
            "enabled": bool(ftp_enabled),
            "host": str(ftp.get("host") or "0.0.0.0"),
            "port": int(ftp.get("port") or 2121),
            "user": str(ftp.get("user") or "camara"),
            "pass": str(ftp.get("pass") or ""),
            "passivePortStart": pasv_start,
            "passivePortEnd": pasv_end,
        },
        "admin": {
            "host": str(admin.get("host") or "0.0.0.0"),
            "port": int(admin.get("port") or 8080),
            "pin": str(admin.get("pin") or "").strip(),
        },
        "uploader": {
            "pollSeconds": float(uploader.get("pollSeconds") or 2),
            "stableChecks": int(uploader.get("stableChecks") or 3),
            "stableIntervalSeconds": float(uploader.get("stableIntervalSeconds") or 0.5),
            "retrySeconds": float(uploader.get("retrySeconds") or 30),
        },
        "gphoto": {
            "enabled": bool(gphoto.get("enabled")),
            "mode": str(gphoto.get("mode") or "tethered").lower(),
            "binary": str(gphoto.get("binary") or "gphoto2"),
            "filenamePrefix": str(gphoto.get("filenamePrefix") or "usb_"),
            "captureTimeoutSeconds": float(gphoto.get("captureTimeoutSeconds") or 45),
            "restartSeconds": float(gphoto.get("restartSeconds") or 5),
            "releaseUsbBeforeCapture": gphoto.get("releaseUsbBeforeCapture", True) is not False,
        },
    }
