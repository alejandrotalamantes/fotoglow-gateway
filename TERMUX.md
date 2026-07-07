# Gateway FotoGlow en Android (Termux)

Mismo software que la Raspberry: FTP + panel web + subida al hosting.

## Requisitos

- Android 8+
- [Termux](https://f-droid.org/en/packages/com.termux/) desde **F-Droid** (no uses la versión de Play Store, está desactualizada)
- Celular con hotspot y datos móviles
- Cámara Sony en **JPEG** por FTP (o USB con gphoto2 en Raspberry; en Termux el USB suele no estar soportado)

## 1. Instalar Termux y paquetes

Abre Termux y ejecuta:

```bash
pkg update -y && pkg upgrade -y
pkg install -y python python-pip git termux-api
termux-setup-storage
```

(Acepta permiso de almacenamiento si lo pide.)

## 2. Copiar el proyecto al teléfono

### Opción A — Desde tu PC por SSH (si Termux tiene `sshd`)

En Termux:

```bash
pkg install openssh
sshd
# Anota la IP del celular en WiFi; usuario por defecto sin contraseña o configura passwd
```

Desde PC (PowerShell):

```powershell
scp -r "C:\sistema cabina\raspberry" u0_aXXX@IP-CELULAR:~/fotoglow-gateway
```

### Opción B — ZIP / USB / Drive

1. Comprime la carpeta `raspberry` en tu PC.
2. Pásala al celular (Drive, cable, etc.).
3. En Termux:

```bash
mkdir -p ~/fotoglow-gateway
cp -r /sdcard/Download/raspberry/* ~/fotoglow-gateway/
cd ~/fotoglow-gateway
```

### Opción C — Git (si subes el repo)

```bash
git clone TU_REPO_URL fotoglow-gateway
cd fotoglow-gateway/raspberry
```

## 3. Entorno Python

```bash
cd ~/fotoglow-gateway
# o cd ~/fotoglow-gateway/raspberry si copiaste solo esa carpeta

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Configuración

```bash
cp config.example.json config.json
nano config.json
```

Ejemplo mínimo:

```json
{
  "eventoId": null,
  "remoteUploadUrl": "https://fotofotoglow.com/upload_profesional.php",
  "paths": {
    "incoming": "./data/incoming",
    "processed": "./data/processed",
    "failed": "./data/failed"
  },
  "ftp": {
    "host": "0.0.0.0",
    "port": 2121,
    "user": "fotoglow",
    "pass": "TU_CONTRASEÑA"
  },
  "admin": {
    "host": "0.0.0.0",
    "port": 8080,
    "pin": ""
  },
  "uploader": {
    "pollSeconds": 2,
    "stableChecks": 3,
    "stableIntervalSeconds": 0.5,
    "retrySeconds": 30
  }
}
```

## 5. Permisos Android (importante)

1. **Ajustes → Apps → Termux → Batería** → Sin restricciones / No optimizar.
2. Mantén Termux en primer plano durante el evento, o usa `termux-wake-lock` (ver script abajo).
3. Activa el **hotspot** antes de arrancar el gateway.

## 6. Arrancar el gateway

```bash
cd ~/fotoglow-gateway
source .venv/bin/activate
bash scripts/termux-start.sh
```

O manualmente:

```bash
termux-wake-lock
python -m gateway
```

## 7. IP para la cámara Sony

Con el **hotspot activo**, en otra sesión de Termux:

```bash
ip -4 addr show | grep inet
```

Busca algo como **`192.168.43.1`** o **`192.168.137.1`** (interfaz `ap0`, `wlan1` o `rndis0`).

En la cámara:

| Campo | Valor |
|-------|--------|
| Servidor FTP | Esa IP (ej. `192.168.43.1`) |
| Puerto | `2121` |
| Usuario | `fotoglow` |
| Contraseña | la de `config.json` |
| Modo | Pasivo si la cámara lo permite |
| Formato | **JPEG** |

## 8. Panel del evento (mismo celular)

Con el gateway corriendo, abre **Chrome** en el teléfono:

```
http://127.0.0.1:8080
```

Pon el **ID del evento** de la cabina y guarda.

(Otro dispositivo en el hotspot: `http://192.168.43.1:8080`)

## 9. Comprobar que funciona

Logs en Termux:

```
Subiendo DSC01234.JPG (evento 1) …
✅ Subida OK: …
```

URL directa (desde cualquier navegador):

```
https://fotofotoglow.com/fotos/1/profesional/NOMBRE.jpg
```

## 10. Segundo plano con `tmux`

Para que no se corte al cerrar Termux:

```bash
pkg install tmux
tmux new -s gateway
cd ~/fotoglow-gateway && source .venv/bin/activate
termux-wake-lock
python -m gateway
```

Desconectar sesión: `Ctrl+B` luego `D`  
Volver: `tmux attach -t gateway`

## Problemas frecuentes

| Problema | Qué hacer |
|----------|-----------|
| Cámara no conecta FTP | Revisa IP del hotspot; prueba modo FTP activo en la Sony |
| Termux se cierra solo | Batería sin restricciones + `termux-wake-lock` + tmux |
| Puerto 8080 ocupado | Cambia `admin.port` a `8081` en config.json |
| Subida falla | Comprueba datos móviles; prueba abrir la URL del hosting en el navegador |
| `pip install` falla | `pkg install python-pip` y `pip install --upgrade pip` |

## Red del evento

```
Hotspot (celular)
  ├── Cámara → FTP → celular:2121
  └── Celular → 4G → hosting

Cabina (otra red) → sync automático → tab Profesional
```

La cabina **no** necesita ver el celular; solo internet hacia el hosting.
