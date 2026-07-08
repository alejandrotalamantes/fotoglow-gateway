"""Registra la Raspberry en el hosting al arrancar."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from .device import get_device_credentials
from .state import save_upload_token

log = logging.getLogger("gateway.register")


def register_with_hosting(remote_upload_url: str) -> None:
    parsed = urlparse(remote_upload_url or "")
    if not parsed.scheme or not parsed.netloc:
        log.warning("remoteUploadUrl no configurada — no se registra en FotoGlow")
        return

    device = get_device_credentials()
    origin = f"{parsed.scheme}://{parsed.netloc}"
    url = f"{origin}/api/public/raspberry/register"

    try:
        res = requests.post(
            url,
            json={
                "idRaspberry": device["idRaspberry"],
                "deviceSecret": device["deviceSecret"],
            },
            timeout=20,
        )
        data = res.json() if res.content else {}
        if res.status_code >= 400 or not data.get("ok"):
            log.warning("Registro FotoGlow: %s", data.get("message") or res.status_code)
            return
        assigned = "asignada" if data.get("assigned") else "pendiente de asignar"
        log.info("Raspberry %s registrada (%s)", device["idRaspberry"], assigned)
        if data.get("uploadToken"):
            save_upload_token(str(data["uploadToken"]), updated_by="register")
    except requests.RequestException as exc:
        log.warning("No se pudo registrar en FotoGlow: %s", exc)
