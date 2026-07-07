# Gateway Raspberry — Fotos profesionales

La Raspberry actúa como **gateway** entre la cámara (FTP y/o USB) y la galería online.  
**No reemplaza** el FTP local de la cabina: ambos pueden usarse en paralelo.

## Red típica en evento

```
LAN1 (hotspot celular):  Cámara + Raspberry Pi
LAN2 (cabina):           PC cabina
WAN:                     Hosting (fotofotoglow.com)
```

La Pi **no ve** la cabina directamente. El **eventoId** se configura desde el **celular** conectado al mismo hotspot.

## Flujo

```
Cámara ──FTP──► Raspberry ──4G/WiFi──► Galería online
    │                ▲
    └── USB ─────────┘   (gphoto2, opcional)
         ▲              ▲
         │              └── Celular: http://IP-PI:8080 (panel web)
         └── Misma red hotspot o cable USB a la Pi
```

## Instalación (una vez)

```bash
cd ~/raspberry
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Solo si usarás USB con gphoto2:
sudo apt install -y gphoto2 libgphoto2-6
cp config.example.json config.json
nano config.json   # ftp.pass, remoteUploadUrl, gphoto.enabled
```

## En cada evento (desde el celular)

1. Conecta el celular al **mismo hotspot** que la Pi y la cámara.
2. Abre en el navegador: **`http://192.168.x.x:8080`** (la IP sale en los logs al arrancar).
3. Escribe el **ID del evento** de la cabina y pulsa **Guardar**.
4. Listo — las fotos se suben solas al hosting con ese evento.

La cámara **no se toca** (misma IP FTP siempre).

## Ejecutar

```bash
source .venv/bin/activate
python -m gateway
```

Logs esperados:
```
Panel web en http://192.168.43.100:8080
FTP escuchando en 0.0.0.0:2121
```

## Configuración (`config.json`)

| Campo | Descripción |
|-------|-------------|
| `remoteUploadUrl` | URL de subida al hosting |
| `ftp.user` / `ftp.pass` | Credenciales FTP para la cámara |
| `admin.port` | Puerto del panel web (8080) |
| `admin.pin` | PIN opcional para proteger el panel |
| `eventoId` | Opcional, solo fallback inicial |
| `gphoto.enabled` | `true` para captura USB con gphoto2 |
| `gphoto.mode` | `tethered` (al disparar en cámara) o `manual` (solo API/botón) |

El evento del día se guarda en `data/state.json` (panel web).

## Cámara Sony — FTP (WiFi)

- Servidor FTP: **IP de la Pi** (ej. `192.168.43.100`)
- Puerto: `2121`
- Usuario/contraseña: los de `config.json`
- Formato: **JPEG**

## Cámara Sony — USB (gphoto2)

Alternativa o complemento al FTP: conecta la cámara por **USB** a la Raspberry.

1. En `config.json`: `"gphoto": { "enabled": true, "mode": "tethered" }`
2. Instala dependencias: `sudo apt install gphoto2 libgphoto2-6`
3. Si Linux “secuestra” la cámara (error **Could not claim the USB device**):

```bash
cd ~/raspberry
sudo bash scripts/fix-usb-camera.sh
# Desconecta y reconecta el cable USB
sudo systemctl restart cabina-gateway
```

También puedes matar gvfs a mano:

```bash
sudo killall gvfs-gphoto2-volume-monitor 2>/dev/null
gphoto2 --auto-detect
```

4. Arranca el gateway. En modo **tethered**, cada disparo en la cámara guarda el JPEG en `data/incoming/` y el uploader lo sube al hosting.
5. Desde el panel web (`:8080`) puedes usar **Disparar por USB** o `POST /api/gphoto/capture`.

**FTP y USB pueden estar activos a la vez** — ambos escriben en `incoming/`.

Si solo usas USB sin FTP, puedes dejar el FTP activo igualmente (no molesta) o apagar el FTP en la cámara.

## Servicio systemd

```ini
[Unit]
Description=Cabina Gateway FTP + Uploader + Panel
After=network-online.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/raspberry
ExecStart=/home/admin/raspberry/.venv/bin/python -m gateway
Restart=always

[Install]
WantedBy=multi-user.target
```

## API del panel (opcional)

- `GET /api/status` — estado JSON (incluye `gphoto`)
- `POST /api/evento` — `{"eventoId": 42}`
- `GET /api/gphoto/status` — estado de captura USB
- `POST /api/gphoto/capture` — disparo único por USB

## Carpetas

```
data/
  state.json           ← eventoId actual (panel web)
  incoming/            ← FTP de la cámara + fotos USB (gphoto2)
  processed/{eventoId}/ ← ya subidas
  failed/{eventoId}/   ← respaldo si falló subida
```
