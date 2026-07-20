"""Estado operativo: token del cliente (sincronizado) + evento del día."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT

STATE_FILE = ROOT / "data" / "state.json"
_lock = threading.Lock()
_last_upload: dict[str, Any] = {}


def _normalize_upload_token(raw: str | None) -> str | None:
    token = re.sub(r"[^a-zA-Z0-9_-]", "", str(raw or "").strip())[:64]
    return token or None


def _default_state() -> dict[str, Any]:
    return {
        "eventoId": None,
        "uploadToken": None,
        "galeriaTitulo": None,
        "updatedAt": None,
        "updatedBy": None,
    }


def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return _default_state()
    try:
        with STATE_FILE.open(encoding="utf-8") as f:
            raw = json.load(f)
        evento = raw.get("eventoId")
        return {
            "eventoId": int(evento) if evento is not None else None,
            "uploadToken": _normalize_upload_token(raw.get("uploadToken")),
            "galeriaTitulo": raw.get("galeriaTitulo"),
            "updatedAt": raw.get("updatedAt"),
            "updatedBy": raw.get("updatedBy"),
        }
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return _default_state()


def _write_state(payload: dict[str, Any]) -> dict[str, Any]:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    return payload


def save_upload_token(upload_token: str, *, updated_by: str = "sync") -> dict[str, Any]:
    token = _normalize_upload_token(upload_token)
    if not token:
        raise ValueError("Token de cliente inválido")
    state = load_state()
    payload = {
        **state,
        "uploadToken": token,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "updatedBy": updated_by,
    }
    return _write_state(payload)


def set_daily_event(
    evento_id: int,
    *,
    galeria_titulo: str | None = None,
    updated_by: str = "web",
) -> dict[str, Any]:
    if evento_id <= 0:
        raise ValueError("ID evento inválido")
    state = load_state()
    if not state.get("uploadToken"):
        raise ValueError("Falta token del cliente — espera asignación o sincroniza la Pi")
    payload = {
        **state,
        "eventoId": int(evento_id),
        "galeriaTitulo": (galeria_titulo or "").strip() or None,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "updatedBy": updated_by,
    }
    return _write_state(payload)


def get_evento_id() -> int | None:
    eid = load_state().get("eventoId")
    if eid is None:
        return None
    try:
        n = int(eid)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def get_upload_token() -> str | None:
    return _normalize_upload_token(load_state().get("uploadToken"))


def set_event_binding(
    upload_token: str,
    *,
    evento_id: int | None = None,
    galeria_titulo: str | None = None,
    updated_by: str = "web",
) -> dict[str, Any]:
    """Compatibilidad: guarda token y opcionalmente evento."""
    save_upload_token(upload_token, updated_by=updated_by)
    if evento_id is not None:
        return set_daily_event(evento_id, galeria_titulo=galeria_titulo, updated_by=updated_by)
    return load_state()


def record_upload(*, filename: str, remote_url: str, evento_id: int | None = None) -> None:
    with _lock:
        _last_upload.clear()
        _last_upload.update(
            {
                "filename": filename,
                "eventoId": evento_id,
                "remoteUrl": remote_url,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )


def get_status(
    *,
    incoming_dir: Path,
    lan_ip: str | None,
    device: dict[str, str],
    processed_root: Path | None = None,
) -> dict[str, Any]:
    from .ftp_server import get_ftp_status
    from .gphoto_capture import get_gphoto_status

    state = load_state()
    pending = 0
    if incoming_dir.is_dir():
        pending = sum(1 for p in incoming_dir.rglob("*") if p.is_file())

    uploaded = 0
    token = _normalize_upload_token(state.get("uploadToken"))
    if processed_root is not None and token:
        processed_dir = processed_root / f"token_{token[:16]}"
        if processed_dir.is_dir():
            uploaded = sum(1 for p in processed_dir.rglob("*") if p.is_file())

    with _lock:
        last = dict(_last_upload)

    return {
        "idRaspberry": device.get("idRaspberry"),
        "eventoId": state.get("eventoId"),
        "uploadToken": state.get("uploadToken"),
        "galeriaTitulo": state.get("galeriaTitulo"),
        "updatedAt": state.get("updatedAt"),
        "lanIp": lan_ip,
        "pendingFiles": pending,
        "uploadedFiles": uploaded,
        "lastUpload": last or None,
        "ftp": get_ftp_status(),
        "gphoto": get_gphoto_status(),
    }
