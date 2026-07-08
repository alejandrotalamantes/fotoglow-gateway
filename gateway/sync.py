"""Sincroniza token del cliente desde el hosting."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import requests

from .device import get_device_credentials
from .state import get_upload_token, save_upload_token, set_daily_event

log = logging.getLogger("gateway.sync")


def _origin_from_upload_url(remote_upload_url: str) -> str | None:
    parsed = urlparse(remote_upload_url or "")
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def sync_client_token(remote_upload_url: str) -> bool:
    """Obtiene el token del cliente asignado. Devuelve True si hay token."""
    origin = _origin_from_upload_url(remote_upload_url)
    if not origin:
        return bool(get_upload_token())

    device = get_device_credentials()
    url = f"{origin}/api/public/raspberry/sync-config"
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
            log.debug("Sync token: %s", data.get("message") or res.status_code)
            return bool(get_upload_token())
        token = data.get("uploadToken")
        if token:
            save_upload_token(str(token), updated_by="sync")
            log.info("Token de cliente sincronizado (%s)", data.get("usuarioNombre") or "cliente")
        evento_id = data.get("eventoIdRemoto")
        titulo = data.get("galeriaRemotasTitulo")
        if evento_id:
            try:
                eid = int(evento_id)
                if eid > 0:
                    set_daily_event(eid, galeria_titulo=str(titulo) if titulo else None, updated_by="sync")
                    log.info("Evento remoto sincronizado: ID %s (%s)", eid, titulo or "galería")
            except (TypeError, ValueError):
                pass
        if token:
            return True
    except requests.RequestException as exc:
        log.debug("No se pudo sincronizar token: %s", exc)
    return bool(get_upload_token())
