"""Panel web móvil para establecer eventoId (acceso desde el celular del hotspot)."""

from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .gphoto_capture import get_gphoto_status, trigger_capture
from .state import get_evento_id, get_status, set_evento_id

log = logging.getLogger("gateway.web")


def local_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def _html_page(*, lan_ip: str | None, admin_port: int, status: dict) -> str:
    ip = lan_ip or "—"
    evento = status.get("eventoId")
    evento_label = str(evento) if evento else "No configurado"
    pending = status.get("pendingFiles", 0)
    updated = status.get("updatedAt") or "—"
    last = status.get("lastUpload") or {}
    last_line = "—"
    if last.get("filename"):
        last_line = f"{last['filename']} (evento {last.get('eventoId', '?')})"

    gphoto = status.get("gphoto") or {}
    gphoto_enabled = gphoto.get("enabled")
    if not gphoto_enabled:
        gphoto_line = "Desactivado (solo FTP)"
        gphoto_class = ""
    elif gphoto.get("running"):
        gphoto_line = f"Tethered activo — {gphoto.get('camera') or 'cámara USB'}"
        gphoto_class = "ok"
    elif gphoto.get("available"):
        mode = gphoto.get("mode") or "tethered"
        cam = gphoto.get("camera") or "sin cámara detectada"
        gphoto_line = f"{mode} — {cam}"
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
    elif gphoto_enabled and gphoto.get("running"):
        capture_btn = """
    <p style="margin-top:1rem;font-size:.88rem;color:#94a3b8">Modo tethered: dispara en la cámara y la foto se sube sola.</p>"""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <title>FotoGlow Gateway</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      margin: 0; padding: 1.25rem;
      background: #0f172a; color: #e2e8f0;
      min-height: 100vh;
    }}
    .card {{
      max-width: 28rem; margin: 0 auto;
      background: #1e293b; border-radius: 1rem;
      padding: 1.25rem 1.5rem 1.5rem;
      box-shadow: 0 8px 32px rgba(0,0,0,.35);
    }}
    h1 {{ font-size: 1.35rem; margin: 0 0 .25rem; color: #f8fafc; }}
    .sub {{ color: #94a3b8; font-size: .9rem; margin-bottom: 1.25rem; }}
    label {{ display: block; font-size: .85rem; color: #cbd5e1; margin-bottom: .35rem; }}
    input {{
      width: 100%; font-size: 1.25rem; padding: .75rem 1rem;
      border-radius: .65rem; border: 1px solid #334155;
      background: #0f172a; color: #f8fafc;
    }}
    button {{
      width: 100%; margin-top: 1rem; padding: .9rem;
      font-size: 1.05rem; font-weight: 600;
      border: none; border-radius: .65rem;
      background: linear-gradient(135deg, #0ea5e9, #0284c7);
      color: white; cursor: pointer;
    }}
    button:active {{ opacity: .9; }}
    .stats {{
      margin-top: 1.25rem; padding-top: 1rem;
      border-top: 1px solid #334155;
      font-size: .88rem; color: #94a3b8; line-height: 1.6;
    }}
    .stats strong {{ color: #e2e8f0; }}
    .ok {{ color: #4ade80; font-weight: 600; }}
    .warn {{ color: #fbbf24; }}
    .msg {{ margin-top: 1rem; padding: .75rem 1rem; border-radius: .5rem; background: #14532d; color: #bbf7d0; }}
    .err {{ background: #450a0a; color: #fecaca; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>FotoGlow Gateway</h1>
    <p class="sub">Raspberry sin pantalla — configura el evento desde el celular</p>

    <form method="post" action="/">
      <label for="eventoId">ID del evento activo en la cabina</label>
      <input id="eventoId" name="eventoId" type="number" min="1" step="1"
             placeholder="Ej. 42" value="{evento if evento else ''}" required autocomplete="off" />
      <button type="submit">Guardar evento</button>
    </form>

    <div class="stats">
      <div>Evento actual: <strong class="{'ok' if evento else 'warn'}">{evento_label}</strong></div>
      <div>IP de esta Pi: <strong>{ip}</strong></div>
      <div>Puerto panel: <strong>{admin_port}</strong></div>
      <div>Fotos en cola: <strong>{pending}</strong></div>
      <div>Último cambio: <strong>{updated}</strong></div>
      <div>Última subida: <strong>{last_line}</strong></div>
      <div>USB gphoto2: <strong class="{gphoto_class}">{gphoto_line}</strong></div>
    </div>
    {capture_btn}
  </div>
</body>
</html>"""


class AdminHandler(BaseHTTPRequestHandler):
    incoming_dir: Path
    admin_port: int = 8080
    admin_pin: str = ""

    def log_message(self, fmt: str, *args) -> None:
        log.debug("HTTP " + fmt, *args)

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

    def _parse_body_evento(self) -> tuple[int | None, str | None, str]:
        ctype = (self.headers.get("Content-Type") or "").lower()
        pin = ""
        if "application/json" in ctype:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
            pin = str(data.get("pin") or "")
            try:
                return int(data["eventoId"]), None, pin
            except (KeyError, TypeError, ValueError):
                return None, "eventoId inválido", pin

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        fields = parse_qs(raw)
        pin = (fields.get("pin") or [""])[0]
        raw_id = (fields.get("eventoId") or [""])[0].strip()
        try:
            return int(raw_id), None, pin
        except ValueError:
            return None, "eventoId inválido", pin

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        lan = local_ipv4()

        if path == "/api/status":
            st = get_status(incoming_dir=self.incoming_dir, lan_ip=lan)
            st["gphoto"] = get_gphoto_status()
            self._send_json(200, {"ok": True, **st})
            return

        if path == "/api/gphoto/status":
            self._send_json(200, {"ok": True, **get_gphoto_status()})
            return

        if path not in ("/", "/index.html"):
            self.send_error(404)
            return

        status = get_status(incoming_dir=self.incoming_dir, lan_ip=lan)
        html = _html_page(lan_ip=lan, admin_port=self.admin_port, status=status)
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
                    data = {}
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

        if path not in ("/", "/api/evento"):
            self.send_error(404)
            return

        evento_id, err, pin = self._parse_body_evento()
        if not self._check_pin(pin):
            if path == "/api/evento":
                self._send_json(401, {"ok": False, "message": "PIN incorrecto"})
            else:
                self._send_html_error("PIN incorrecto")
            return

        if err or evento_id is None or evento_id <= 0:
            if path == "/api/evento":
                self._send_json(400, {"ok": False, "message": err or "eventoId requerido"})
            else:
                self._send_html_error(err or "eventoId requerido")
            return

        try:
            saved = set_evento_id(evento_id)
        except ValueError as exc:
            if path == "/api/evento":
                self._send_json(400, {"ok": False, "message": str(exc)})
            else:
                self._send_html_error(str(exc))
            return

        log.info("Evento establecido desde panel web: %s", evento_id)

        if path == "/api/evento":
            self._send_json(200, {"ok": True, **saved})
            return

        self._redirect_with_ok(evento_id)

    def _send_html_error(self, message: str) -> None:
        lan = local_ipv4()
        status = get_status(incoming_dir=self.incoming_dir, lan_ip=lan)
        html = _html_page(lan_ip=lan, admin_port=self.admin_port, status=status)
        html = html.replace(
            "</form>",
            f'<div class="msg err">{message}</div></form>',
            1,
        )
        body = html.encode("utf-8")
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect_with_ok(self, evento_id: int) -> None:
        lan = local_ipv4()
        status = get_status(incoming_dir=self.incoming_dir, lan_ip=lan)
        html = _html_page(lan_ip=lan, admin_port=self.admin_port, status=status)
        html = html.replace(
            "</form>",
            f'<div class="msg">Evento <strong>{evento_id}</strong> guardado. Las fotos en cola se subirán solas.</div></form>',
            1,
        )
        body = html.encode("utf-8")
        self.send_response(200)
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
) -> threading.Thread:
    handler = type(
        "BoundAdminHandler",
        (AdminHandler,),
        {
            "incoming_dir": incoming_dir,
            "admin_port": port,
            "admin_pin": (admin_pin or "").strip(),
        },
    )

    server = ThreadingHTTPServer((host, port), handler)

    def _run() -> None:
        lan = local_ipv4()
        log.info("Panel web en http://%s:%s (celular en el hotspot)", lan or host, port)
        server.serve_forever()

    thread = threading.Thread(target=_run, name="web-admin", daemon=True)
    thread.start()
    return thread
