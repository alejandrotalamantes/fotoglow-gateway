"""Servidor FTP para recibir fotos de la cámara en la Raspberry."""

from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path

from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

from .utils import ensure_dir

log = logging.getLogger("gateway.ftp")

_ftp_status: dict[str, object] = {"running": False}


def get_ftp_status() -> dict[str, object]:
    return dict(_ftp_status)


def set_ftp_disabled() -> None:
    _ftp_status.update({"enabled": False, "running": False})


def _local_ipv4() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def start_ftp_server(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    root_dir: Path,
    passive_port_start: int = 53000,
    passive_port_end: int = 53099,
) -> threading.Thread | None:
    ensure_dir(root_dir)

    authorizer = DummyAuthorizer()
    authorizer.add_user(user, password, str(root_dir), perm="elradfmwMT")

    handler = FTPHandler
    handler.authorizer = authorizer
    handler.banner = "FotoGlow Gateway — FTP camara profesional"

    # Rango PASV para cámara Sony en la misma red (hotspot/LAN)
    pasv_end = max(passive_port_start, passive_port_end)
    handler.passive_ports = range(passive_port_start, pasv_end + 1)
    lan_ip = _local_ipv4()
    if lan_ip:
        handler.masquerade_address = lan_ip
        log.info(
            "FTP PASV masquerade → %s (puertos %s-%s)",
            lan_ip,
            passive_port_start,
            pasv_end,
        )

    server = FTPServer((host, port), handler)
    server.max_cons = 8
    server.max_cons_per_ip = 4

    _ftp_status.update(
        {
            "enabled": True,
            "running": True,
            "host": host,
            "port": port,
            "user": user,
            "pass": password,
            "lanIp": lan_ip,
            "rootDir": str(root_dir),
            "passivePorts": f"{passive_port_start}-{pasv_end}",
            "mode": "pasivo",
        }
    )

    def _run() -> None:
        log.info("FTP escuchando en %s:%s → %s", host, port, root_dir)
        if lan_ip:
            log.info("Configura la cámara con servidor FTP: %s:%s usuario=%s", lan_ip, port, user)
        server.serve_forever()

    thread = threading.Thread(target=_run, name="ftp-server", daemon=True)
    thread.start()
    return thread
