"""Captura USB con gphoto2 (Sony u otras PTP) hacia incoming/."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .utils import ensure_dir

log = logging.getLogger("gateway.gphoto")

# Ruido habitual de PTP / gphoto2 en stderr
_PTP_NOISE = (
    "UNKNOWN PTP",
    "PTP Property 0x",
    "Waiting for events from camera",
    "Press Ctrl-C to abort",
)


@dataclass
class GphotoState:
    enabled: bool = False
    mode: str = "tethered"
    running: bool = False
    available: bool = False
    camera: str | None = None
    last_error: str | None = None
    last_capture: str | None = None
    captures: int = 0
    started_at: str | None = None


_lock = threading.Lock()
_state = GphotoState()
_process: subprocess.Popen[str] | None = None
_stop_event = threading.Event()
_monitor_thread: threading.Thread | None = None
_cfg: dict[str, Any] | None = None
_claim_fail_streak = 0
RELEASE_USB_SCRIPT = Path("/usr/local/sbin/cabina-release-usb.sh")


def _is_noise(line: str) -> bool:
    return any(token in line for token in _PTP_NOISE)


def _run_cmd(args: list[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LANG": "C"}
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _binary(cfg: dict[str, Any]) -> str:
    return str(cfg.get("binary") or "gphoto2")


def _filename_pattern(incoming_dir: Path, cfg: dict[str, Any]) -> str:
    prefix = str(cfg.get("filenamePrefix") or "usb_")
    # %n = contador, %C = extensión (JPG, etc.)
    return str(incoming_dir / f"{prefix}%n.%C")


def _usb_device_path(camera_line: str | None) -> str | None:
    if not camera_line:
        return None
    match = re.search(r"usb:(\d+),(\d+)", camera_line, re.IGNORECASE)
    if not match:
        return None
    bus = int(match.group(1))
    dev = int(match.group(2))
    return f"/dev/bus/usb/{bus:03d}/{dev:03d}"


def release_usb_device(cfg: dict[str, Any] | None = None) -> None:
    """Libera la cámara si gvfs u otro proceso la tiene ocupada."""
    cfg = cfg or {}
    if cfg.get("releaseUsbBeforeCapture") is False:
        return

    with _lock:
        camera_line = _state.camera
    usb_path = _usb_device_path(camera_line)

    if RELEASE_USB_SCRIPT.is_file():
        args = ["sudo", "-n", str(RELEASE_USB_SCRIPT)]
        if usb_path:
            args.append(usb_path)
        try:
            subprocess.run(args, capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        for name in (
            "gvfs-gphoto2-volume-monitor",
            "gphoto2-volume-monitor",
            "gvfs-mtp-volume-monitor",
            "gvfsd-gphoto2",
        ):
            for cmd in (["pkill", "-x", name], ["sudo", "-n", "killall", name]):
                try:
                    subprocess.run(cmd, capture_output=True, timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    pass

    time.sleep(0.8)


def _claim_error_hint(stderr: str) -> str:
    if "Could not claim" in stderr or "Device or resource busy" in stderr:
        return (
            f"{stderr}\n\n"
            "La cámara está ocupada por otro proceso (suele ser gvfs). "
            "En la Pi ejecuta: sudo bash scripts/fix-usb-camera.sh "
            "y reinicia: sudo systemctl restart cabina-gateway"
        )
    return stderr

def probe_gphoto(cfg: dict[str, Any]) -> tuple[bool, str | None]:
    """Comprueba si gphoto2 está instalado y detecta cámara."""
    binary = _binary(cfg)
    if not shutil.which(binary):
        return False, None

    try:
        ver = _run_cmd([binary, "--version"], timeout=8)
        if ver.returncode != 0:
            return False, None
    except (OSError, subprocess.TimeoutExpired):
        return False, None

    camera = None
    try:
        det = _run_cmd([binary, "--auto-detect"], timeout=12)
        for line in (det.stdout or "").splitlines():
            line = line.strip()
            if not line or line.startswith("Model") or line.startswith("-"):
                continue
            if "usb:" in line.lower() or "ptp" in line.lower() or len(line) > 3:
                camera = line
                break
    except (OSError, subprocess.TimeoutExpired):
        pass

    return True, camera


def get_gphoto_status() -> dict[str, Any]:
    with _lock:
        s = _state
        return {
            "enabled": s.enabled,
            "mode": s.mode,
            "running": s.running,
            "available": s.available,
            "camera": s.camera,
            "lastError": s.last_error,
            "lastCapture": s.last_capture,
            "captures": s.captures,
            "startedAt": s.started_at,
        }


def _set_state(**kwargs: Any) -> None:
    with _lock:
        for key, value in kwargs.items():
            if hasattr(_state, key):
                setattr(_state, key, value)


def _on_capture_filename(name: str) -> None:
    from datetime import datetime, timezone

    with _lock:
        _state.last_capture = name
        _state.captures += 1
        _state.last_error = None
    log.info("Foto USB guardada en incoming: %s", name)


def capture_once(cfg: dict[str, Any], incoming_dir: Path) -> dict[str, Any]:
    """Disparo único vía USB (útil desde el panel web)."""
    binary = _binary(cfg)
    if not shutil.which(binary):
        raise RuntimeError("gphoto2 no está instalado en el sistema")

    with _lock:
        if _state.running:
            raise RuntimeError(
                "Modo tethered activo: dispara en la cámara (el botón solo aplica en modo manual)"
            )

    release_usb_device(cfg)
    ensure_dir(incoming_dir)
    pattern = _filename_pattern(incoming_dir, cfg)
    cmd = [
        binary,
        "--quiet",
        "--force-overwrite",
        "--capture-image-and-download",
        "--keep",
        "--filename",
        pattern,
    ]

    try:
        result = _run_cmd(cmd, timeout=float(cfg.get("captureTimeoutSeconds") or 45))
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Tiempo de espera agotado al capturar con la cámara") from exc

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(_claim_error_hint(err) if err else f"gphoto2 salió con código {result.returncode}")

    # Buscar el archivo más reciente en incoming (gphoto reemplaza %n)
    candidates = sorted(
        (p for p in incoming_dir.glob(f"{cfg.get('filenamePrefix') or 'usb_'}*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        _on_capture_filename(candidates[0].name)
        return {"ok": True, "filename": candidates[0].name}

    _on_capture_filename(Path(pattern).name)
    return {"ok": True, "filename": None, "message": "Captura OK (revisa incoming/)"}


def _tethered_loop(cfg: dict[str, Any], incoming_dir: Path) -> None:
    global _process, _claim_fail_streak

    binary = _binary(cfg)
    pattern = _filename_pattern(incoming_dir, cfg)
    cmd = [
        binary,
        "--quiet",
        "--force-overwrite",
        "--capture-tethered",
        "--filename",
        pattern,
    ]
    env = {**os.environ, "LANG": "C"}

    while not _stop_event.is_set():
        wait = float(cfg.get("restartSeconds") or 5)
        try:
            release_usb_device(cfg)
            log.info("Iniciando captura tethered USB → %s", incoming_dir)
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
            with _lock:
                _process = proc
                _state.running = True
                _state.last_error = None

            assert proc.stdout is not None
            assert proc.stderr is not None

            while not _stop_event.is_set():
                if proc.poll() is not None:
                    break

                line = proc.stderr.readline()
                if line:
                    line = line.strip()
                    if line and not _is_noise(line):
                        if "saving file" in line.lower() or "downloaded" in line.lower():
                            log.info("[gphoto2] %s", line)
                        elif "error" in line.lower() or "could not" in line.lower():
                            log.warning("[gphoto2] %s", line)
                            hint = _claim_error_hint(line)
                            _set_state(last_error=hint[:500])

                # Detectar archivo nuevo por mtime (gphoto no siempre avisa en stderr)
                for p in sorted(incoming_dir.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True)[:3]:
                    if not p.is_file():
                        continue
                    age = time.time() - p.stat().st_mtime
                    if age < 3 and p.name != _state.last_capture:
                        _on_capture_filename(p.name)

            code = proc.wait(timeout=5)
            with _lock:
                _process = None
                _state.running = False

            if _stop_event.is_set():
                break

            err_tail = proc.stderr.read() if proc.stderr else ""
            msg = (err_tail or "").strip()
            base_wait = float(cfg.get("restartSeconds") or 5)
            wait = base_wait

            if code not in (0, -15) and msg and not _is_noise(msg):
                if "Could not claim" in msg or "Device or resource busy" in msg:
                    _claim_fail_streak += 1
                    wait = min(60.0, base_wait * _claim_fail_streak)
                    if _claim_fail_streak == 1 or _claim_fail_streak % 6 == 0:
                        log.error(
                            "USB ocupado (intento %s). Ejecuta en la Pi: "
                            "sudo bash scripts/fix-usb-camera.sh — reintento en %ss",
                            _claim_fail_streak,
                            int(wait),
                        )
                else:
                    _claim_fail_streak = 0
                    log.warning("gphoto2 tethered terminó (código %s): %s", code, msg[:200])
                _set_state(last_error=_claim_error_hint(msg)[:500])
            else:
                _claim_fail_streak = 0
                log.info("gphoto2 tethered reiniciando en %ss …", int(base_wait))

        except Exception as exc:
            log.error("Error en tethered gphoto2: %s", exc)
            _set_state(running=False, last_error=str(exc))
            with _lock:
                _process = None
            wait = float(cfg.get("restartSeconds") or 5)

        if _stop_event.wait(wait):
            break

    with _lock:
        _process = None
        _state.running = False
    log.info("Captura tethered USB detenida")


def start_gphoto(cfg: dict[str, Any], incoming_dir: Path) -> threading.Thread | None:
    """Arranca gphoto2 si está habilitado en config."""
    global _cfg, _monitor_thread

    gphoto = cfg.get("gphoto") or {}
    if not gphoto.get("enabled"):
        log.info("gphoto2 deshabilitado en config (solo FTP)")
        return None

    _cfg = cfg
    mode = str(gphoto.get("mode") or "tethered").lower()
    available, camera = probe_gphoto(gphoto)

    from datetime import datetime, timezone

    with _lock:
        _state.enabled = True
        _state.mode = mode
        _state.available = available
        _state.camera = camera
        _state.started_at = datetime.now(timezone.utc).isoformat()

    if not available:
        log.warning(
            "gphoto2 habilitado pero no encontrado — instala: sudo apt install gphoto2 libgphoto2-6"
        )
        _set_state(last_error="gphoto2 no instalado o no en PATH")
        return None

    if camera:
        log.info("Cámara USB detectada: %s", camera)
    else:
        log.warning(
            "gphoto2 OK pero sin cámara USB — conecta la Sony por USB y reinicia el gateway"
        )
        _set_state(last_error="Sin cámara USB detectada")

    ensure_dir(incoming_dir)
    _stop_event.clear()

    if mode == "tethered":
        _monitor_thread = threading.Thread(
            target=_tethered_loop,
            args=(gphoto, incoming_dir),
            name="gphoto-tethered",
            daemon=True,
        )
        _monitor_thread.start()
        log.info("Modo tethered USB activo — dispara en la cámara y la foto irá a incoming/")
        return _monitor_thread

    if mode == "manual":
        log.info("Modo manual USB — usa POST /api/gphoto/capture o el botón del panel")
        return None

    log.warning("gphoto.mode desconocido %r — usa tethered o manual", mode)
    return None


def stop_gphoto() -> None:
    global _process

    _stop_event.set()
    with _lock:
        proc = _process

    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass

    with _lock:
        _process = None
        _state.running = False


def trigger_capture() -> dict[str, Any]:
    if _cfg is None:
        raise RuntimeError("gphoto2 no está configurado")
    incoming = _cfg["incomingDir"]
    gphoto = _cfg.get("gphoto") or {}
    return capture_once(gphoto, incoming)
