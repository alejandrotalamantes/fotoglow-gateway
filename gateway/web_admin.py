"""Panel web móvil: muestra idRaspberry y configura el evento del día."""

from __future__ import annotations

import json
import logging
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import requests

from .device import get_device_credentials
from .gphoto_capture import get_gphoto_status, trigger_capture
from .state import get_status, get_upload_token, set_daily_event
from .sync import sync_client_token

log = logging.getLogger("gateway.web")


def local_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _origin_from_upload_url(remote_upload_url: str) -> str:
    parsed = urlparse(remote_upload_url or "")
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("remoteUploadUrl no configurada en config.json")
    return f"{parsed.scheme}://{parsed.netloc}"


def _normalize_token(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "", str(raw or "").strip())[:64]


def _fetch_raspberry_status(remote_upload_url: str, id_raspberry: str) -> dict:
    origin = _origin_from_upload_url(remote_upload_url)
    url = f"{origin}/api/public/raspberry/status?idRaspberry={quote(id_raspberry)}"
    res = requests.get(url, timeout=15)
    data = res.json() if res.content else {}
    if res.status_code >= 400:
        return {"registered": False, "assigned": False, "usuarioNombre": None}
    return {
        "registered": True,
        "assigned": bool(data.get("assigned")),
        "activo": data.get("activo", True),
        "usuarioNombre": data.get("usuarioNombre"),
    }


def _validate_evento(remote_upload_url: str, token: str, evento_id: int) -> dict:
    origin = _origin_from_upload_url(remote_upload_url)
    url = (
        f"{origin}/api/public/subida/validate"
        f"?token={quote(token)}&evento={quote(str(evento_id))}"
    )
    res = requests.get(url, timeout=20)
    data = res.json() if res.content else {}
    if res.status_code >= 400 or not data.get("ok"):
        raise ValueError(data.get("message") or "ID evento no válido para este cliente")
    return data


def _html_page(*, lan_ip: str | None, admin_port: int, status: dict, cloud: dict) -> str:
    ip = lan_ip or "—"
    id_rpi = status.get("idRaspberry") or "—"
    upload_token = status.get("uploadToken") or ""
    galeria_titulo = status.get("galeriaTitulo") or "—"
    evento = status.get("eventoId")
    pending = status.get("pendingFiles", 0)
    updated = status.get("updatedAt") or "—"
    last = status.get("lastUpload") or {}
    last_line = last.get("filename") or "—"

    if cloud.get("assigned"):
        assign_line = cloud.get("usuarioNombre") or "Cliente asignado"
        assign_class = "ok"
    elif cloud.get("registered"):
        assign_line = "Sin cliente — da este ID al administrador"
        assign_class = "warn"
    else:
        assign_line = "Sin conexión al hosting"
        assign_class = "warn"

    token_ok = "ok" if upload_token else "warn"
    token_line = "Sincronizado" if upload_token else "Pendiente — asigna la Pi al cliente"

    bind_class = "ok" if evento and galeria_titulo else "warn"
    bind_label = galeria_titulo if evento else "Sin evento del día"

    gphoto = status.get("gphoto") or {}
    ftp = status.get("ftp") or {}
    if ftp.get("running"):
        ftp_ip = ftp.get("lanIp") or ip
        ftp_line = f"Activo — {ftp_ip}:{ftp.get('port')} usuario {ftp.get('user')}"
        ftp_class = "ok"
    elif ftp.get("enabled") is False:
        ftp_line = "Desactivado"
        ftp_class = ""
    else:
        ftp_line = "No iniciado"
        ftp_class = "warn"

    gphoto_enabled = gphoto.get("enabled")
    if not gphoto_enabled:
        gphoto_line = "Desactivado"
        gphoto_class = ""
    elif gphoto.get("running"):
        gphoto_line = f"Tethered activo — {gphoto.get('camera') or 'cámara USB'}"
        gphoto_class = "ok"
    elif gphoto.get("available"):
        gphoto_line = f"{gphoto.get('mode') or 'tethered'} — {gphoto.get('camera') or 'sin cámara'}"
        gphoto_class = "warn" if not gphoto.get("camera") else "ok"
    else:
        gphoto_line = gphoto.get("lastError") or "gphoto2 no disponible"
        gphoto_class = "warn"

    capture_btn = ""
    if gphoto_enabled and gphoto.get("available") and (gphoto.get("mode") or "").lower() == "manual":
        capture_btn = """
    <form method="post" action="/api/gphoto/capture" style="margin-top:1rem">
      <button type="submit" style="background:linear-gradient(135deg,#8b5cf6,#6d28d9)">Disparar por USB</button>
    </form>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>FotoGlow Gateway</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 1.25rem; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
    .card {{ max-width: 28rem; margin: 0 auto; background: #1e293b; border-radius: 1rem; padding: 1.25rem 1.5rem; }}
    h1 {{ font-size: 1.35rem; margin: 0 0 .25rem; color: #f8fafc; }}
    .sub {{ color: #94a3b8; font-size: .9rem; margin-bottom: 1rem; }}
    .id-box {{ background: #0f172a; border: 1px solid #334155; border-radius: .65rem; padding: .75rem 1rem; margin-bottom: 1rem; word-break: break-all; font-family: monospace; font-size: 1.1rem; color: #38bdf8; }}
    label {{ display: block; font-size: .85rem; color: #cbd5e1; margin-bottom: .35rem; margin-top: .75rem; }}
    input {{ width: 100%; font-size: 1rem; padding: .75rem 1rem; border-radius: .65rem; border: 1px solid #334155; background: #0f172a; color: #f8fafc; }}
    button {{ width: 100%; margin-top: 1rem; padding: .9rem; font-size: 1.05rem; font-weight: 600; border: none; border-radius: .65rem; background: linear-gradient(135deg, #0ea5e9, #0284c7); color: white; }}
    .stats {{ margin-top: 1.25rem; padding-top: 1rem; border-top: 1px solid #334155; font-size: .88rem; color: #94a3b8; line-height: 1.6; }}
    .ok {{ color: #4ade80; font-weight: 600; }}
    .warn {{ color: #fbbf24; }}
    .msg {{ margin-top: 1rem; padding: .75rem 1rem; border-radius: .5rem; background: #14532d; color: #bbf7d0; }}
    .err {{ background: #450a0a; color: #fecaca; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>FotoGlow Gateway</h1>
    <p class="sub">ID único de esta Raspberry — el administrador lo asigna a un cliente</p>
    <div class="id-box">{id_rpi}</div>

    <form method="post" action="/">
      <label for="eventoId">ID evento cabina (del día)</label>
      <input id="eventoId" name="eventoId" type="number" min="1" step="1" value="{evento if evento else ''}" placeholder="Ej. 42" required />
      <button type="submit">Activar evento del día</button>
    </form>

    <div class="stats">
      <div>Cliente: <strong class="{assign_class}">{assign_line}</strong></div>
      <div>Token cliente: <strong class="{token_ok}">{token_line}</strong></div>
      <div>Evento activo: <strong class="{bind_class}">{bind_label}</strong></div>
      <div>IP Pi: <strong>{ip}</strong> · Panel: <strong>{admin_port}</strong></div>
      <div>Cola: <strong>{pending}</strong> · Última subida: <strong>{last_line}</strong></div>
      <div>FTP: <strong class="{ftp_class}">{ftp_line}</strong></div>
      <div>USB: <strong class="{gphoto_class}">{gphoto_line}</strong></div>
    </div>
    {capture_btn}
  </div>
</body>
</html>"""


class AdminHandler(BaseHTTPRequestHandler):
    incoming_dir: Path
    admin_port: int = 8080
    admin_pin: str = ""
    remote_upload_url: str = ""

    def log_message(self, fmt: str, *args) -> None:
        log.debug("HTTP " + fmt, *args)

    def _device(self) -> dict[str, str]:
        return get_device_credentials()

    def _check_pin(self, pin: str) -> bool:
        if not self.admin_pin:
            return True
        return pin.strip() == self.admin_pin

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_event_form(self) -> tuple[int | None, str | None, str]:
        ctype = (self.headers.get("Content-Type") or "").lower()
        pin = ""
        if "application/json" in ctype:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            pin = str(data.get("pin") or "")
            evento_raw = data.get("eventoId") or data.get("evento")
        else:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            fields = parse_qs(raw)
            pin = (fields.get("pin") or [""])[0]
            evento_raw = (fields.get("eventoId") or fields.get("evento") or [""])[0].strip()

        if evento_raw in (None, ""):
            return None, "ID evento requerido", pin
        try:
            evento_id = int(evento_raw)
            if evento_id <= 0:
                return None, "ID evento inválido", pin
        except (TypeError, ValueError):
            return None, "ID evento inválido", pin
        return evento_id, None, pin

    def _page_context(self) -> tuple[dict, dict]:
        sync_client_token(self.remote_upload_url)
        lan = local_ipv4()
        device = self._device()
        status = get_status(incoming_dir=self.incoming_dir, lan_ip=lan, device=device)
        cloud = {}
        try:
            cloud = _fetch_raspberry_status(self.remote_upload_url, device["idRaspberry"])
        except requests.RequestException:
            cloud = {"registered": False, "assigned": False}
        return status, cloud

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        lan = local_ipv4()
        device = self._device()

        if path == "/api/status":
            st = get_status(incoming_dir=self.incoming_dir, lan_ip=lan, device=device)
            st["gphoto"] = get_gphoto_status()
            self._send_json(200, {"ok": True, **st})
            return

        if path == "/api/gphoto/status":
            self._send_json(200, {"ok": True, **get_gphoto_status()})
            return

        if path not in ("/", "/index.html"):
            self.send_error(404)
            return

        status, cloud = self._page_context()
        html = _html_page(lan_ip=lan, admin_port=self.admin_port, status=status, cloud=cloud)
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path

        if path == "/api/gphoto/capture":
            pin = ""
            ctype = (self.headers.get("Content-Type") or "").lower()
            if "application/json" in ctype:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    data = json.loads(raw.decode("utf-8") or "{}")
                    pin = str(data.get("pin") or "")
                except json.JSONDecodeError:
                    pass
            else:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                fields = parse_qs(raw)
                pin = (fields.get("pin") or [""])[0]

            if not self._check_pin(pin):
                self._send_json(401, {"ok": False, "message": "PIN incorrecto"})
                return
            try:
                result = trigger_capture()
                self._send_json(200, {"ok": True, **result})
            except Exception as exc:
                self._send_json(500, {"ok": False, "message": str(exc)})
            return

        if path not in ("/", "/api/evento", "/api/galeria"):
            self.send_error(404)
            return

        evento_id, err, pin = self._parse_event_form()
        if not self._check_pin(pin):
            self._send_html_error("PIN incorrecto")
            return
        if err or evento_id is None:
            self._send_html_error(err or "ID evento requerido")
            return

        try:
            cloud = _fetch_raspberry_status(self.remote_upload_url, self._device()["idRaspberry"])
            if not cloud.get("assigned"):
                raise ValueError("Raspberry sin cliente asignado. Contacta al administrador con tu ID.")
            sync_client_token(self.remote_upload_url)
            token = get_upload_token()
            if not token:
                raise ValueError("Token del cliente no disponible. Espera unos segundos o reinicia la Pi.")
            meta = _validate_evento(self.remote_upload_url, token, evento_id)
            saved = set_daily_event(evento_id, galeria_titulo=meta.get("titulo"))
        except (ValueError, requests.RequestException) as exc:
            self._send_html_error(str(exc))
            return

        log.info("Evento configurado: %s", meta.get("titulo"))
        if path in ("/api/evento", "/api/galeria"):
            self._send_json(200, {"ok": True, "titulo": meta.get("titulo"), **saved})
            return

        lan = local_ipv4()
        status, cloud = self._page_context()
        html = _html_page(lan_ip=lan, admin_port=self.admin_port, status=status, cloud=cloud)
        html = html.replace(
            "</form>",
            f'<div class="msg">Evento <strong>{meta.get("titulo")}</strong> listo.</div></form>',
            1,
        )
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html_error(self, message: str) -> None:
        lan = local_ipv4()
        status, cloud = self._page_context()
        html = _html_page(lan_ip=lan, admin_port=self.admin_port, status=status, cloud=cloud)
        html = html.replace("</form>", f'<div class="msg err">{message}</div></form>', 1)
        body = html.encode("utf-8")
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_web_admin(
    *,
    host: str,
    port: int,
    incoming_dir: Path,
    admin_pin: str = "",
    remote_upload_url: str = "",
) -> threading.Thread:
    handler = type(
        "BoundAdminHandler",
        (AdminHandler,),
        {
            "incoming_dir": incoming_dir,
            "admin_port": port,
            "admin_pin": (admin_pin or "").strip(),
            "remote_upload_url": (remote_upload_url or "").strip(),
        },
    )
    server = ThreadingHTTPServer((host, port), handler)

    def _run() -> None:
        lan = local_ipv4()
        log.info("Panel web en http://%s:%s", lan or host, port)
        server.serve_forever()

    thread = threading.Thread(target=_run, name="web-admin", daemon=True)
    thread.start()
    return thread
