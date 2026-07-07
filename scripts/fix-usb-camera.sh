#!/bin/bash
# Configura la Pi para que gphoto2 pueda usar la camara USB.
# Ejecutar una vez: sudo bash scripts/fix-usb-camera.sh

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RELEASE_BIN="/usr/local/sbin/cabina-release-usb.sh"
GATEWAY_USER="${SUDO_USER:-admin}"

echo "==> Instalando $RELEASE_BIN"
install -m 755 "$SCRIPT_DIR/cabina-release-usb.sh" "$RELEASE_BIN"

echo "==> Liberando camara ahora..."
"$RELEASE_BIN" || true

RULE_FILE="/etc/udev/rules.d/90-gphoto-gateway.rules"
echo "==> Regla udev en $RULE_FILE"
cat >"$RULE_FILE" <<'EOF'
# Evita que gvfs tome camaras PTP (Sony y otras) — deja paso a gphoto2
ATTRS{idVendor}=="054c", ENV{ID_GPHOTO2}="1", ENV{ID_MEDIA}=""
SUBSYSTEM=="usb", ATTR{bInterfaceClass}=="06", ATTR{bInterfaceSubClass}=="01", ENV{ID_GPHOTO2}="1", ENV{ID_MEDIA}=""
EOF

udevadm control --reload-rules
udevadm trigger

echo "==> Sudoers para $GATEWAY_USER (sin password)"
SUDOERS_FILE="/etc/sudoers.d/cabina-gateway-usb"
cat >"$SUDOERS_FILE" <<EOF
$GATEWAY_USER ALL=(ALL) NOPASSWD: $RELEASE_BIN
EOF
chmod 440 "$SUDOERS_FILE"

DROPIN_DIR="/etc/systemd/system/cabina-gateway.service.d"
mkdir -p "$DROPIN_DIR"
cat >"$DROPIN_DIR/release-usb.conf" <<EOF
[Service]
# + = ejecutar como root antes de arrancar el gateway
ExecStartPre=+$RELEASE_BIN
EOF

echo "==> Grupo plugdev (si existe)..."
if getent group plugdev >/dev/null; then
  usermod -aG plugdev "$GATEWAY_USER" 2>/dev/null || true
fi

systemctl daemon-reload

echo ""
echo "Listo."
echo "  1) Desconecta y reconecta el cable USB de la camara"
echo "  2) sudo systemctl restart cabina-gateway"
echo "  3) gphoto2 --auto-detect"
echo ""
echo "Si sigue fallando, con el servicio DETENIDO prueba:"
echo "  sudo systemctl stop cabina-gateway"
echo "  gphoto2 --capture-tethered --filename /tmp/test_%n.%C"
