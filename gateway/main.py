"""Punto de entrada del gateway Raspberry."""

from __future__ import annotations

import logging
import sys

from .config import load_config
from .ftp_server import set_ftp_disabled, start_ftp_server
from .gphoto_capture import start_gphoto
from .state import load_state
from .register import register_with_hosting
from .sync import sync_client_token
from .device import get_device_credentials
from .uploader import run_uploader_loop
from .web_admin import start_web_admin


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        cfg = load_config()
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        sys.exit(1)

    ftp = cfg["ftp"]
    if ftp.get("enabled", True):
        if not ftp["pass"]:
            print("Error: config.json → ftp.pass no puede estar vacío", file=sys.stderr)
            sys.exit(1)
        start_ftp_server(
            host=ftp["host"],
            port=ftp["port"],
            user=ftp["user"],
            password=ftp["pass"],
            root_dir=cfg["incomingDir"],
            passive_port_start=ftp.get("passivePortStart", 53000),
            passive_port_end=ftp.get("passivePortEnd", 53099),
        )
    else:
        logging.getLogger("gateway").info("FTP deshabilitado en config (solo USB)")
        set_ftp_disabled()
    if cfg.get("eventoIdFallback"):
        logging.getLogger("gateway").info(
            "eventoIdFallback en config ignorado — usa token de galería en el panel",
        )

    register_with_hosting(cfg.get("remoteUploadUrl") or "")
    sync_client_token(cfg.get("remoteUploadUrl") or "")

    admin = cfg["admin"]
    start_web_admin(
        host=admin["host"],
        port=admin["port"],
        incoming_dir=cfg["incomingDir"],
        processed_root=cfg["processedRoot"],
        admin_pin=admin.get("pin") or "",
        remote_upload_url=cfg.get("remoteUploadUrl") or "",
    )

    # USB vía gphoto2 (opcional; convive con FTP en la misma carpeta incoming/)
    start_gphoto(cfg, cfg["incomingDir"])

    device = get_device_credentials()
    state = load_state()
    logging.getLogger("gateway").info("ID Raspberry: %s", device["idRaspberry"])
    if state.get("uploadToken"):
        logging.getLogger("gateway").info(
            "Evento activo: %s",
            state.get("galeriaTitulo") or state.get("uploadToken"),
        )
    else:
        logging.getLogger("gateway").warning(
            "Sin evento configurado — abre http://IP-PI:%s y pega el token de galería",
            admin["port"],
        )

    run_uploader_loop(cfg)


if __name__ == "__main__":
    main()
