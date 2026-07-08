"""Estado en tiempo de ejecución (eventoId desde el panel web del celular)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT

STATE_FILE = ROOT / "data" / "state.json"
_lock = threading.Lock()

_last_upload: dict[str, Any] = {}


def _default_state() -> dict[str, Any]:
    return {
        "eventoId": None,
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
            "updatedAt": raw.get("updatedAt"),
            "updatedBy": raw.get("updatedBy"),
        }
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return _default_state()


def save_state(evento_id: int, *, updated_by: str = "web") -> dict[str, Any]:
    payload = {
        "eventoId": int(evento_id),
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "updatedBy": updated_by,
    }
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        with STATE_FILE.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    return payload


def get_evento_id() -> int | None:
    with _lock:
        eid = load_state().get("eventoId")
    if eid is None:
        return None
    try:
        n = int(eid)
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def set_evento_id(evento_id: int, *, updated_by: str = "web") -> dict[str, Any]:
    n = int(evento_id)
    if n <= 0:
        raise ValueError("eventoId debe ser un entero positivo")
    return save_state(n, updated_by=updated_by)


def record_upload(*, filename: str, evento_id: int, remote_url: str) -> None:
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


def get_status(*, incoming_dir: Path, lan_ip: str | None) -> dict[str, Any]:
    from .ftp_server import get_ftp_status
    from .gphoto_capture import get_gphoto_status

    state = load_state()
    pending = 0
    if incoming_dir.is_dir():
        pending = sum(1 for p in incoming_dir.rglob("*") if p.is_file())

    with _lock:
        last = dict(_last_upload)

    return {
        "eventoId": state.get("eventoId"),
        "updatedAt": state.get("updatedAt"),
        "lanIp": lan_ip,
        "pendingFiles": pending,
        "lastUpload": last or None,
        "ftp": get_ftp_status(),
        "gphoto": get_gphoto_status(),
    }
