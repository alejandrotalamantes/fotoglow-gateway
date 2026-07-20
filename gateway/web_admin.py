"""Panel hub kiosko: estado del evento, cola y fotos enviadas."""

from __future__ import annotations

import json
import logging
import html as html_lib
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


def _esc(value: object) -> str:
    return html_lib.escape("" if value is None else str(value), quote=True)


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


def _html_page(
    *,
    lan_ip: str | None,
    admin_port: int,
    status: dict,
    cloud: dict,
    flash: str | None = None,
    flash_err: bool = False,
) -> str:
    id_rpi = status.get("idRaspberry") or "—"
    upload_token = status.get("uploadToken") or ""
    galeria_titulo = status.get("galeriaTitulo") or ""
    evento = status.get("eventoId")
    pending = int(status.get("pendingFiles") or 0)
    uploaded = int(status.get("uploadedFiles") or 0)
    last = status.get("lastUpload") or {}
    last_line = last.get("filename") or "—"

    if cloud.get("assigned"):
        assign_line = cloud.get("usuarioNombre") or "Cliente OK"
        cloud_dot = "on"
    elif cloud.get("registered"):
        assign_line = "Sin cliente"
        cloud_dot = "warn"
    else:
        assign_line = "Sin nube"
        cloud_dot = "off"

    token_dot = "on" if upload_token else "warn"

    event_ready = bool(evento)
    event_title = galeria_titulo if galeria_titulo else (f"Evento {evento}" if evento else "Sin evento")
    event_sub = f"ID {evento}" if evento else "Esperando evento remoto"

    gphoto = status.get("gphoto") or {}
    ftp = status.get("ftp") or {}
    ftp_dot = "on" if ftp.get("running") else ("off" if ftp.get("enabled") is False else "warn")
    ftp_line = "FTP on" if ftp.get("running") else "FTP off"

    gphoto_enabled = bool(gphoto.get("enabled"))
    if not gphoto_enabled:
        usb_dot, usb_line = "off", "USB off"
    elif gphoto.get("running"):
        usb_dot, usb_line = "on", "USB on"
    elif gphoto.get("available") and gphoto.get("camera"):
        usb_dot, usb_line = "warn", "USB"
    else:
        usb_dot, usb_line = "warn", "USB ?"

    queue_dot = "warn" if pending else "on"
    uploaded_dot = "on" if uploaded else "off"

    flash_html = ""
    if flash:
        kind = "err" if flash_err else "ok"
        flash_html = f'<div class="flash {kind}">{_esc(flash)}</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=320, height=480, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <meta http-equiv="refresh" content="8" />
  <title>FotoGlow Hub</title>
  <style>
    :root {{
      --bg: #0c0e12;
      --panel: #141820;
      --line: #232a36;
      --text: #e8edf5;
      --muted: #8b95a8;
      --accent: #3dd6c6;
      --accent-dim: #1a3d3a;
      --ok: #3dd68c;
      --warn: #e6b84d;
      --off: #4a5568;
      --err: #e85d5d;
      --err-bg: #2a1414;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      width: 100%; height: 100%;
      overflow: hidden;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
      -webkit-tap-highlight-color: transparent;
      touch-action: manipulation;
    }}
    body {{
      display: flex;
      flex-direction: column;
      min-height: 100dvh;
      max-width: 320px;
      margin: 0 auto;
      padding: 12px 14px 10px;
      background:
        radial-gradient(120% 80% at 50% -10%, #1a2433 0%, transparent 55%),
        var(--bg);
      gap: 10px;
    }}
    .top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .brand {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .14em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .dots {{ display: flex; gap: 6px; align-items: center; }}
    .dot {{
      width: 8px; height: 8px; border-radius: 50%;
      background: var(--off);
    }}
    .dot.on {{ background: var(--ok); box-shadow: 0 0 6px rgba(61,214,140,.45); }}
    .dot.warn {{ background: var(--warn); box-shadow: 0 0 6px rgba(230,184,77,.4); }}
    .dot.off {{ background: var(--off); }}

    .hero {{
      text-align: center;
      padding: 16px 10px 14px;
      border-radius: 14px;
      background: var(--panel);
      border: 1px solid var(--line);
    }}
    .hero .label {{
      font-size: 10px;
      letter-spacing: .12em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .hero .title {{
      font-size: 20px;
      font-weight: 650;
      line-height: 1.2;
      color: var(--text);
      max-height: 2.4em;
      overflow: hidden;
      word-break: break-word;
    }}
    .hero .title.empty {{ color: var(--warn); }}
    .hero .sub {{
      margin-top: 8px;
      font-size: 12px;
      color: var(--muted);
    }}

    .metrics {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      flex: 1 1 auto;
      min-height: 120px;
    }}
    .metric {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      border-radius: 14px;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 12px 8px;
    }}
    .metric .num {{
      font-size: 48px;
      font-weight: 700;
      line-height: 1;
      letter-spacing: -0.03em;
      font-variant-numeric: tabular-nums;
    }}
    .metric .num.warn {{ color: var(--warn); }}
    .metric .num.on {{ color: var(--ok); }}
    .metric .num.off {{ color: var(--muted); }}
    .metric .lbl {{
      margin-top: 8px;
      font-size: 11px;
      letter-spacing: .14em;
      text-transform: uppercase;
      color: var(--muted);
    }}

    .status {{
      display: grid;
      grid-template-columns: 1fr 1fr 1fr;
      gap: 6px;
    }}
    .pill {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 5px;
      padding: 8px 4px;
      border-radius: 9px;
      background: #0a0c10;
      border: 1px solid var(--line);
      font-size: 11px;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .pill .d {{
      width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
      background: var(--off);
    }}
    .pill .d.on {{ background: var(--ok); }}
    .pill .d.warn {{ background: var(--warn); }}
    .pill .d.off {{ background: var(--off); }}

    .last {{
      border-radius: 12px;
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 10px 12px;
      text-align: center;
    }}
    .last .lbl {{
      font-size: 9px;
      letter-spacing: .12em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    .last .name {{
      font-size: 13px;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}

    .foot {{
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 2px;
      margin-top: auto;
      padding-top: 2px;
    }}
    .foot .id {{
      font-family: ui-monospace, Consolas, monospace;
      font-size: 10px;
      color: var(--accent);
      word-break: break-all;
      text-align: center;
      line-height: 1.3;
      max-width: 100%;
    }}
    .foot .meta {{
      font-size: 9px;
      color: #5c6678;
    }}
    .flash {{
      padding: 8px 10px;
      border-radius: 8px;
      font-size: 12px;
      line-height: 1.3;
      text-align: center;
    }}
    .flash.ok {{ background: var(--accent-dim); color: var(--accent); }}
    .flash.err {{ background: var(--err-bg); color: var(--err); }}
  </style>
</head>
<body>
  <div class="top">
    <div class="brand">FotoGlow</div>
    <div class="dots" title="Nube · Token · USB · FTP · Cola">
      <span class="dot {cloud_dot}"></span>
      <span class="dot {token_dot}"></span>
      <span class="dot {usb_dot}"></span>
      <span class="dot {ftp_dot}"></span>
      <span class="dot {queue_dot}"></span>
    </div>
  </div>

  {flash_html}

  <div class="hero">
    <div class="label">Evento activo</div>
    <div class="title{" empty" if not event_ready else ""}">{_esc(event_title)}</div>
    <div class="sub">{_esc(event_sub)}</div>
  </div>

  <div class="metrics">
    <div class="metric">
      <div class="num {queue_dot}">{pending}</div>
      <div class="lbl">Cola</div>
    </div>
    <div class="metric">
      <div class="num {uploaded_dot}">{uploaded}</div>
      <div class="lbl">Enviadas</div>
    </div>
  </div>

  <div class="status">
    <div class="pill"><span class="d {cloud_dot}"></span>{_esc(assign_line)}</div>
    <div class="pill"><span class="d {usb_dot}"></span>{_esc(usb_line)}</div>
    <div class="pill"><span class="d {ftp_dot}"></span>{_esc(ftp_line)}</div>
  </div>

  <div class="last">
    <div class="lbl">Última subida</div>
    <div class="name">{_esc(last_line)}</div>
  </div>

  <div class="foot">
    <div class="id">{_esc(id_rpi)}</div>
    <div class="meta">remoto · refresh 8s · :{admin_port}</div>
  </div>
</body>
</html>"""



class AdminHandler(BaseHTTPRequestHandler):
    incoming_dir: Path
    processed_root: Path | None = None
    admin_port: int = 8080
    admin_pin: str = ""
    remote_upload_url: str = ""

    def log_message(self, fmt: str, *args) -> None:
        log.debug("HTTP " + fmt, *args)

    def _device(self) -> dict[str, str]:
        return get_device_credentials()

    def _status(self, *, lan_ip: str | None = None) -> dict:
        lan = lan_ip if lan_ip is not None else local_ipv4()
        return get_status(
            incoming_dir=self.incoming_dir,
            lan_ip=lan,
            device=self._device(),
            processed_root=self.processed_root,
        )

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
        status = self._status(lan_ip=lan)
        cloud = {}
        try:
            cloud = _fetch_raspberry_status(self.remote_upload_url, device["idRaspberry"])
        except requests.RequestException:
            cloud = {"registered": False, "assigned": False}
        return status, cloud

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        lan = local_ipv4()

        if path == "/api/status":
            st = self._status(lan_ip=lan)
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
        titulo = meta.get("titulo") or f"Evento {evento_id}"
        html = _html_page(
            lan_ip=lan,
            admin_port=self.admin_port,
            status=status,
            cloud=cloud,
            flash=f"Listo: {titulo}",
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
        html = _html_page(
            lan_ip=lan,
            admin_port=self.admin_port,
            status=status,
            cloud=cloud,
            flash=message,
            flash_err=True,
        )
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
    processed_root: Path | None = None,
    admin_pin: str = "",
    remote_upload_url: str = "",
) -> threading.Thread:
    handler = type(
        "BoundAdminHandler",
        (AdminHandler,),
        {
            "incoming_dir": incoming_dir,
            "processed_root": processed_root,
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
