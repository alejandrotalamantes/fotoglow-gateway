"""Punto de entrada del gateway Raspberry."""

from __future__ import annotations

import logging
import sys

from .config import load_config
from .ftp_server import start_ftp_server
from .gphoto_capture import start_gphoto
from .state import get_evento_id, load_state, save_state
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
    if not ftp["pass"]:
        print("Error: config.json → ftp.pass no puede estar vacío", file=sys.stderr)
        sys.exit(1)

    # Migrar eventoId de config.json al estado si el panel aún no tiene valor
    if get_evento_id() is None and cfg.get("eventoIdFallback"):
        save_state(cfg["eventoIdFallback"], updated_by="config")
        logging.getLogger("gateway").info(
            "Evento inicial %s desde config.json (cámbialo en el panel web)",
            cfg["eventoIdFallback"],
        )

    admin = cfg["admin"]
    start_web_admin(
        host=admin["host"],
        port=admin["port"],
        incoming_dir=cfg["incomingDir"],
        admin_pin=admin.get("pin") or "",
    )

    start_ftp_server(
        host=ftp["host"],
        port=ftp["port"],
        user=ftp["user"],
        password=ftp["pass"],
        root_dir=cfg["incomingDir"],
    )

    # USB vía gphoto2 (opcional; convive con FTP en la misma carpeta incoming/)
    start_gphoto(cfg, cfg["incomingDir"])

    state = load_state()
    if state.get("eventoId"):
        logging.getLogger("gateway").info("Evento activo en gateway: %s", state["eventoId"])
    else:
        logging.getLogger("gateway").warning(
            "Sin eventoId — conecta el celular al hotspot y abre http://IP-PI:%s",
            admin["port"],
        )

    run_uploader_loop(cfg)


if __name__ == "__main__":
    main()
