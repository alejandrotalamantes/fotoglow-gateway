"""Identidad única de la Raspberry (generada una sola vez)."""

from __future__ import annotations

import json
import secrets
import threading
from pathlib import Path
from typing import Any

from .config import ROOT

DEVICE_FILE = ROOT / "data" / "device.json"
_lock = threading.Lock()


def _default_device() -> dict[str, Any]:
    return {
        "idRaspberry": f"rpi-{secrets.token_hex(8)}",
        "deviceSecret": secrets.token_urlsafe(32),
    }


def get_or_create_device() -> dict[str, str]:
    with _lock:
        if DEVICE_FILE.exists():
            try:
                with DEVICE_FILE.open(encoding="utf-8") as f:
                    raw = json.load(f)
                id_r = str(raw.get("idRaspberry") or "").strip().lower()
                secret = str(raw.get("deviceSecret") or "").strip()
                if id_r and secret and len(secret) >= 16:
                    return {"idRaspberry": id_r, "deviceSecret": secret}
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                pass

        payload = _default_device()
        DEVICE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with DEVICE_FILE.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        return payload


def get_device_credentials() -> dict[str, str]:
    return get_or_create_device()
